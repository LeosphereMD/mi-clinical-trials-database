"""Download every trial matching SPEC.md from ClinicalTrials.gov and load it into the database.

Usage:
    .venv\\Scripts\\python scripts\\fetch_trials.py --count   # only print how many trials match
    .venv\\Scripts\\python scripts\\fetch_trials.py           # download and load

What it does (full run):
  1. Asks the ClinicalTrials.gov API v2 for all matching trials, page by page,
     waiting briefly between requests.
  2. Saves each trial's raw API record to data/raw/<NCT ID>.json before reading it.
  3. Checks each trial against the SPEC.md inclusion rules again, locally.
  4. Loads it into data/ami_trials.db. A trial already in the database is
     updated (matched by NCT ID), never added twice.
The whole load is one transaction: if anything goes wrong, the script stops
with a clear message and the database is left exactly as it was.

Inclusion rules (SPEC.md decisions 1-4):
  - MeSH condition term "Myocardial Infarction" (or a child term, i.e. a term
    whose ancestor is "Myocardial Infarction") or "Acute Coronary Syndrome"
  - Phase 3 or Phase 2/3
  - The conditions list or the title must name MI or ACS in words (SPEC.md
    "Inclusion criteria", added 2026-11-16): the MeSH term alone is not enough,
    because the registry also assigns MeSH terms from keywords and synonyms.
  - Not on the project owner's manual exclusion list (review/manual_exclusions.csv)
  - At least one DRUG or BIOLOGICAL intervention
  - Start date (actual or estimated) on or after 2010-01-01; trials without a
    start date are excluded and counted
A trial already in the database that now fails a rule is skipped and listed;
run scripts\\apply_inclusion_rule.py to remove it.
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from create_database import DB_PATH, connect

API_URL = "https://clinicaltrials.gov/api/v2/studies"
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PAGE_SIZE = 100
WAIT_SECONDS = 1.0
TIMEOUT_SECONDS = 60

CONDITION_RULE = (
    '(AREA[ConditionMeshTerm]"Myocardial Infarction"'
    ' OR AREA[ConditionAncestorTerm]"Myocardial Infarction"'
    ' OR AREA[ConditionMeshTerm]"Acute Coronary Syndrome")'
)
BASE_RULE = (CONDITION_RULE
             + " AND AREA[Phase]PHASE3"
             + " AND AREA[InterventionType](DRUG OR BIOLOGICAL)")
QUERY = BASE_RULE + " AND AREA[StartDate]RANGE[2010-01-01,MAX]"
NO_START_DATE_QUERY = BASE_RULE + " AND AREA[StartDate]MISSING"


class StopError(Exception):
    """A problem that must stop the script, with a message for the user."""


# ---------------------------------------------------------------- API access

_first_request = True


def get_json(params):
    """One API request. Waits briefly before every request except the first."""
    global _first_request
    if not _first_request:
        time.sleep(WAIT_SECONDS)
    _first_request = False
    try:
        response = requests.get(API_URL, params=params, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise StopError(f"Could not reach ClinicalTrials.gov: {e}")
    if response.status_code != 200:
        raise StopError(f"ClinicalTrials.gov answered with error {response.status_code}: "
                        f"{response.text[:300]}")
    try:
        return response.json()
    except ValueError:
        raise StopError("ClinicalTrials.gov sent a reply that is not valid JSON.")


def count_matches(query):
    data = get_json({"filter.advanced": query, "countTotal": "true", "pageSize": 1})
    if "totalCount" not in data:
        raise StopError("The API reply did not include a total count.")
    return data["totalCount"]


def download_all():
    """Download every matching trial, saving each raw record before parsing."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    studies, total, token, page = [], None, None, 0
    while True:
        params = {"filter.advanced": QUERY, "pageSize": PAGE_SIZE, "countTotal": "true"}
        if token:
            params["pageToken"] = token
        data = get_json(params)
        page += 1
        if total is None:
            total = data.get("totalCount")
        for study in data.get("studies", []):
            nct_id = (study.get("protocolSection", {})
                      .get("identificationModule", {}).get("nctId"))
            if not nct_id:
                raise StopError(f"A trial on page {page} has no NCT ID.")
            (RAW_DIR / f"{nct_id}.json").write_text(
                json.dumps(study, ensure_ascii=False, indent=2), encoding="utf-8")
            studies.append((nct_id, study))
        print(f"  page {page}: {len(studies)} of {total} trials downloaded")
        token = data.get("nextPageToken")
        if not token:
            break
    if total is not None and len(studies) != total:
        raise StopError(f"The API said {total} trials match but {len(studies)} were "
                        "downloaded. The registry may have changed during the download; "
                        "please run the script again.")
    return studies


# ------------------------------------------------------------ reading a trial

def clean(value):
    """Missing or blank stays empty (NULL)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return value


# MI / ACS named in words (SPEC.md "Inclusion criteria"). Whole words only;
# "MI" and "ACS" count only in capitals.
MI_ACS_WORDS = re.compile(
    r"\b(?:myocardial\s+infarctions?|infarcts?|heart\s+attacks?|N?STEMI|"
    r"ST[\s-](?:segment[\s-])?elevation|acute\s+coronary\s+syndromes?|"
    r"unstable\s+angina|angina,\s+unstable)\b", re.IGNORECASE)
MI_ACS_CAPITALS = re.compile(r"\b(?:MI|ACS)\b")
# MeSH child terms of "Myocardial Infarction" seen in the registry data.
MI_CHILD_TERMS = {"ST Elevation Myocardial Infarction", "Non-ST Elevated Myocardial Infarction",
                  "Anterior Wall Myocardial Infarction", "Inferior Wall Myocardial Infarction",
                  "Shock, Cardiogenic"}
# Whether the name of a matched child term (e.g. "cardiogenic shock") counts as
# backing on its own. No: decided by the project owner on 2026-11-16 (decision 1b).
CHILD_TERM_NAME_BACKS = False
NOT_BACKED = "MI/ACS MeSH term not backed by conditions or title"
# Trials the project owner excluded by hand, with the reason (SPEC.md "Inclusion criteria").
MANUAL_EXCLUSIONS = ROOT / "review" / "manual_exclusions.csv"


def manual_exclusions():
    """{nct_id: reason} from review/manual_exclusions.csv (empty if the file is missing)."""
    if not MANUAL_EXCLUSIONS.exists():
        return {}
    from review_files import read_csv   # accepts Excel's encodings and semicolons
    return {r["nct_id"].strip(): (r.get("reason") or "").strip()
            for r in read_csv(MANUAL_EXCLUSIONS) if (r.get("nct_id") or "").strip()}


EXCLUDED_BY_HAND = manual_exclusions()

# Population labels the project owner set by hand, applied after the rules
# (SPEC.md "Population label", rule 6; decided 2026-11-16).
POPULATION_OVERRIDES_FILE = ROOT / "review" / "population_overrides.csv"
POPULATION_LABELS = ("STEMI", "NSTEMI", "STEMI + NSTEMI", "ACS mixed", "MI unspecified")


def population_overrides():
    """{nct_id: (label, reason)} from review/population_overrides.csv (empty if missing).
    Stops with an error if a label is not one of the five population labels."""
    if not POPULATION_OVERRIDES_FILE.exists():
        return {}
    from review_files import read_csv   # accepts Excel's encodings and semicolons
    out = {}
    for r in read_csv(POPULATION_OVERRIDES_FILE):
        nct_id = (r.get("nct_id") or "").strip()
        if not nct_id:
            continue
        label = (r.get("label") or "").strip()
        if label not in POPULATION_LABELS:
            raise ValueError(f"population_overrides.csv: {nct_id} has label '{label}'; "
                             f"use one of: {', '.join(POPULATION_LABELS)}")
        out[nct_id] = (label, (r.get("reason") or "").strip())
    return out


POPULATION_OVERRIDES = population_overrides()


def backing_text(study):
    """The brief and official title plus the conditions list, as one text."""
    p = study.get("protocolSection", {})
    ident = p.get("identificationModule", {})
    return " | ".join([ident.get("briefTitle") or "", ident.get("officialTitle") or ""]
                      + p.get("conditionsModule", {}).get("conditions", []))


def names_child_term(text, meshes):
    """True if the text names one of the trial's MI child MeSH terms
    ("Shock, Cardiogenic" also matches "cardiogenic shock")."""
    for term in meshes & MI_CHILD_TERMS:
        forms = {term, " ".join(reversed(term.split(", ")))}
        if any(re.search(r"\b" + re.escape(f) + r"\b", text, re.IGNORECASE) for f in forms):
            return True
    return False


def mi_acs_backed(study):
    """True if the conditions list or title names MI or ACS in words."""
    text = backing_text(study)
    if MI_ACS_WORDS.search(text) or MI_ACS_CAPITALS.search(text):
        return True
    if CHILD_TERM_NAME_BACKS:
        browse = study.get("derivedSection", {}).get("conditionBrowseModule", {})
        return names_child_term(text, {m.get("term") for m in browse.get("meshes", [])})
    return False


def rule_failure(study):
    """Re-check the SPEC.md inclusion rules. Returns the reason it fails, or None."""
    p = study.get("protocolSection", {})
    nct_id = p.get("identificationModule", {}).get("nctId")
    if nct_id in EXCLUDED_BY_HAND:
        return f"excluded by hand: {EXCLUDED_BY_HAND[nct_id]}"
    browse = study.get("derivedSection", {}).get("conditionBrowseModule", {})
    meshes = {m.get("term") for m in browse.get("meshes", [])}
    ancestors = {a.get("term") for a in browse.get("ancestors", [])}
    if not ({"Myocardial Infarction", "Acute Coronary Syndrome"} & meshes
            or "Myocardial Infarction" in ancestors):
        return "no qualifying MeSH condition term"
    if not mi_acs_backed(study):
        return NOT_BACKED
    if "PHASE3" not in p.get("designModule", {}).get("phases", []):
        return "not Phase 3 or Phase 2/3"
    types = {i.get("type") for i in p.get("armsInterventionsModule", {})
             .get("interventions", [])}
    if not types & {"DRUG", "BIOLOGICAL"}:
        return "no drug or biological intervention"
    start = clean(p.get("statusModule", {}).get("startDateStruct", {}).get("date"))
    if start is None:
        return "no start date"
    # Dates can be "2015-03" or "2015-03-01"; comparing year-month is exact here
    # because the cutoff is the first day of a month.
    if start[:7] < "2010-01":
        return "start date before 2010-01-01"
    return None


STEMI_MESH = "ST Elevation Myocardial Infarction"
NSTEMI_MESH = "Non-ST Elevated Myocardial Infarction"
ACS_MESH = {"Acute Coronary Syndrome", "Angina, Unstable"}
# NSTEMI words: NSTEMI, N-STEMI, non-STEMI, non-ST-elevation,
# non-ST-segment elevation (hyphen or space)
NSTEMI_WORDS = re.compile(
    r"\b(?:N[\s-]?STEMI|non[\s-]?STEMI|non[\s-]?ST[\s-](?:segment[\s-])?elevation)\b",
    re.IGNORECASE)
# STEMI words: STEMI, ST-elevation, ST-segment elevation. Searched only after
# NSTEMI words are removed, so NSTEMI wording can never count as STEMI.
STEMI_WORDS = re.compile(r"\b(?:STEMI|ST[\s-](?:segment[\s-])?elevation)\b",
                         re.IGNORECASE)
EXCLUSION_HEADING = re.compile(r"exclusion\s+criteria", re.IGNORECASE)
# Rule (b), decided 2026-11-16: in the inclusion criteria, primary PCI means STEMI.
PRIMARY_PCI = re.compile(
    r"\b(?:primary\s+(?:PCI|percutaneous\s+coronary\s+intervention)|p-?PCI)\b", re.IGNORECASE)
# Rule (a), decided 2026-11-16: wording that brings unstable angina into an ACS
# population (unstable angina, UA, NSTE-ACS, non-ST-elevation ACS, "non-ST or ST").
UA_WORDS = re.compile(
    r"\bunstable\s+angina\b|\bNSTE-?ACS\b|"
    r"\bnon[\s-]?ST[\s-](?:segment[\s-])?elevation\s+(?:acute\s+coronary\s+syndromes?|ACS)\b|"
    r"\bnon[\s-]?ST\s+or\s+ST\b", re.IGNORECASE)
UA_CAPITALS = re.compile(r"\bUA\b")
# "with or without ST elevation" / "with and without ST-segment elevation" names both.
WITH_OR_WITHOUT_ST = re.compile(
    r"\bwith\s+(?:or|and)\s+without\s+ST[\s-](?:segment[\s-])?elevation\b", re.IGNORECASE)
ACS_WORDS = re.compile(r"\b(?:[Aa]cute\s+[Cc]oronary\s+[Ss]yndromes?|ACS)\b")
# "STE-ACS" / "ST-elevation ACS" is a STEMI population, not a generic ACS one.
STE_ACS = re.compile(
    r"\bSTE-?ACS\b|\bST[\s-](?:segment[\s-])?elevation\s+(?:acute\s+coronary\s+syndromes?|ACS)\b",
    re.IGNORECASE)
# ACS restricted on the spot, e.g. "ACS (STEMI or NSTEMI)", "ACS: STEMI ...",
# "ACS event (STEMI ...".
RESTRICTED_AFTER = re.compile(
    r"^[\s:(\[,-]{0,4}(?:\w+\s+){0,2}[(\[:]?\s*"
    r"(?:N?STEMI|non[\s-]?STEMI|ST[\s-](?:segment[\s-])?elevation)", re.IGNORECASE)


def generic_acs(text):
    """True if the text names ACS without ever restricting it to STEMI / NSTEMI
    ("ACS (STEMI or NSTEMI)" and "STE-ACS" are restricted). Once the criteria
    define ACS as STEMI / NSTEMI, later mentions ("the qualifying ACS event")
    refer to that definition."""
    masked = STE_ACS.sub(" ", text)
    mentions = [bool(RESTRICTED_AFTER.search(masked[m.end():m.end() + 40]))
                for m in ACS_WORDS.finditer(masked)]
    return bool(mentions) and not any(mentions)


def narrower_than_acs(inclusion):
    """Rule (a): STEMI / NSTEMI / STEMI + NSTEMI when the inclusion criteria name
    only those (no unstable angina, no unrestricted ACS); otherwise None."""
    if not inclusion or UA_WORDS.search(inclusion) or UA_CAPITALS.search(inclusion):
        return None
    if generic_acs(inclusion):
        return None
    return label_from_text(inclusion, primary_pci=True)


def label_from_text(text, primary_pci=False):
    """STEMI / NSTEMI / STEMI + NSTEMI from free text, or None if neither appears.
    primary_pci=True (inclusion criteria only, rule b): "primary PCI" counts as STEMI."""
    if not text:
        return None
    if WITH_OR_WITHOUT_ST.search(text):
        return "STEMI + NSTEMI"
    has_nstemi = bool(NSTEMI_WORDS.search(text))
    rest = NSTEMI_WORDS.sub(" ", text)
    has_stemi = bool(STEMI_WORDS.search(rest)) or (primary_pci and bool(PRIMARY_PCI.search(rest)))
    if has_stemi and has_nstemi:
        return "STEMI + NSTEMI"
    if has_stemi:
        return "STEMI"
    if has_nstemi:
        return "NSTEMI"
    return None


def inclusion_criteria(eligibility_text):
    """Text before the 'Exclusion Criteria' heading, or None if there is no heading."""
    if not eligibility_text:
        return None
    heading = EXCLUSION_HEADING.search(eligibility_text)
    return eligibility_text[:heading.start()] if heading else None


def population(study):
    """Population label and its source, following SPEC.md "Population label"."""
    p = study["protocolSection"]
    browse = study.get("derivedSection", {}).get("conditionBrowseModule", {})
    meshes = {m.get("term") for m in browse.get("meshes", [])}
    if meshes & ACS_MESH:
        # Rule (a): a narrower population in the inclusion criteria wins.
        narrower = narrower_than_acs(inclusion_criteria(
            p.get("eligibilityModule", {}).get("eligibilityCriteria")))
        return (narrower, "eligibility") if narrower else ("ACS mixed", "mesh")
    if STEMI_MESH in meshes and NSTEMI_MESH in meshes:
        return "STEMI + NSTEMI", "mesh"
    if STEMI_MESH in meshes:
        return "STEMI", "mesh"
    if NSTEMI_MESH in meshes:
        return "NSTEMI", "mesh"
    ident = p.get("identificationModule", {})
    texts = [
        ("title", " | ".join(t for t in (ident.get("briefTitle"),
                                         ident.get("officialTitle")) if t)),
        ("conditions", " | ".join(p.get("conditionsModule", {}).get("conditions", []))),
        ("eligibility", inclusion_criteria(
            p.get("eligibilityModule", {}).get("eligibilityCriteria"))),
    ]
    for source, text in texts:
        label = label_from_text(text, primary_pci=(source == "eligibility"))
        if label:
            return label, source
    return "MI unspecified", "mesh"


def population_label(study):
    """The stored population label: the owner's override if there is one (rule 6),
    otherwise the rules in population()."""
    nct_id = study["protocolSection"]["identificationModule"]["nctId"]
    if nct_id in POPULATION_OVERRIDES:
        return POPULATION_OVERRIDES[nct_id][0], "owner override"
    return population(study)


def countries(study):
    """Distinct countries from the registry's location list (sorted)."""
    locations = (study["protocolSection"].get("contactsLocationsModule", {})
                 .get("locations", []))
    return sorted({clean(loc.get("country")) for loc in locations} - {None})


# ClinicalTrials.gov's own definitions of the statuses. Some sponsors type one
# of these into "Why Stopped" instead of a reason; it is then not a reason
# (SPEC.md "Registry cleaning", part 3), so why_stopped is stored as empty.
# The original text stays in the raw file.
STATUS_DEFINITIONS = [
    "enrolling participants has halted prematurely and will not resume",
    "the study has stopped early and will not start again",
    "study halted prematurely, prior to enrollment of first participant",
    "the study stopped early, before enrolling its first participant",
    "study halted prematurely but potentially will resume",
    "the study has stopped early but may start again",
]


def is_status_definition(text):
    normalized = " ".join((text or "").lower().split()).rstrip(".")
    return any(normalized.startswith(d) for d in STATUS_DEFINITIONS)


def why_stopped_value(study):
    text = clean(study["protocolSection"].get("statusModule", {}).get("whyStopped"))
    return None if is_status_definition(text) else text


def trial_row(nct_id, study):
    p = study["protocolSection"]
    status = p.get("statusModule", {})
    design = p.get("designModule", {})
    design_info = design.get("designInfo", {})
    sponsor = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
    enrollment = design.get("enrollmentInfo", {})
    types = {i.get("type") for i in p.get("armsInterventionsModule", {})
             .get("interventions", [])}
    has_results = study.get("hasResults")
    pop_label, pop_source = population_label(study)
    n_countries = len(countries(study)) or None   # no locations listed -> empty
    return {
        "population": pop_label,
        "population_source": pop_source,
        "n_countries": n_countries,
        "nct_id": nct_id,
        "title": clean(p.get("identificationModule", {}).get("briefTitle")),
        "phase_label": clean("/".join(design.get("phases", []))),
        "overall_status": clean(status.get("overallStatus")),
        "why_stopped": why_stopped_value(study),
        "start_date": clean(status.get("startDateStruct", {}).get("date")),
        "start_date_type": clean(status.get("startDateStruct", {}).get("type")),
        "completion_date": clean(status.get("completionDateStruct", {}).get("date")),
        "completion_date_type": clean(status.get("completionDateStruct", {}).get("type")),
        "enrollment": enrollment.get("count"),
        "enrollment_type": clean(enrollment.get("type")),
        "lead_sponsor": clean(sponsor.get("name")),
        "sponsor_class": clean(sponsor.get("class")),
        "has_device_or_procedure": int(bool(types & {"DEVICE", "PROCEDURE"})),
        "allocation": clean(design_info.get("allocation")),
        "masking": clean(design_info.get("maskingInfo", {}).get("masking")),
        "has_results": None if has_results is None else int(bool(has_results)),
        "last_updated": clean(status.get("lastUpdatePostDateStruct", {}).get("date")),
        "raw_json_file": f"data/raw/{nct_id}.json",
    }


def condition_rows(study):
    conds = study["protocolSection"].get("conditionsModule", {}).get("conditions", [])
    browse = study.get("derivedSection", {}).get("conditionBrowseModule", {})
    rows = [(clean(c), None, None, None) for c in conds]
    rows += [(None, clean(m.get("term")), clean(m.get("id")), "direct term")
             for m in browse.get("meshes", [])]
    rows += [(None, clean(a.get("term")), clean(a.get("id")), "parent term")
             for a in browse.get("ancestors", [])]
    return rows


def intervention_mesh_rows(study):
    browse = study.get("derivedSection", {}).get("interventionBrowseModule", {})
    rows = [(clean(m.get("term")), clean(m.get("id")), "direct term")
            for m in browse.get("meshes", [])]
    rows += [(clean(a.get("term")), clean(a.get("id")), "parent term")
             for a in browse.get("ancestors", [])]
    return rows


def intervention_rows(study):
    items = study["protocolSection"].get("armsInterventionsModule", {}).get("interventions", [])
    return [(clean(i.get("type")), clean(i.get("name")),
             clean("; ".join(i.get("otherNames", []))), clean(i.get("description")))
            for i in items]


def arm_rows(study):
    groups = study["protocolSection"].get("armsInterventionsModule", {}).get("armGroups", [])
    return [(g.get("label"), clean(g.get("type")), clean(g.get("description")))
            for g in groups if clean(g.get("label"))]


def outcome_rows(study):
    out = study["protocolSection"].get("outcomesModule", {})
    rows = []
    for key, kind in (("primaryOutcomes", "primary"), ("secondaryOutcomes", "secondary")):
        for o in out.get(key, []):
            rows.append((kind, clean(o.get("measure")), clean(o.get("timeFrame")),
                         clean(o.get("description"))))
    return rows


# ------------------------------------------------------------ saving a trial

TRIAL_COLUMNS = ["nct_id", "title", "phase_label", "overall_status", "why_stopped",
                 "start_date", "start_date_type", "completion_date",
                 "completion_date_type", "enrollment", "enrollment_type",
                 "lead_sponsor", "sponsor_class", "population",
                 "population_source", "n_countries", "has_device_or_procedure",
                 "allocation", "masking", "has_results", "last_updated",
                 "raw_json_file"]


def upsert_trial(con, row, run_id):
    """Insert a new trial, or update the registry fields of an existing one.
    publication_status and first_seen_run are never overwritten. Population is
    worked out again from the registry each run; the owner's corrections live
    in registry_checks, so they are not lost."""
    cols = ", ".join(TRIAL_COLUMNS)
    marks = ", ".join(f":{c}" for c in TRIAL_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in TRIAL_COLUMNS if c != "nct_id")
    con.execute(
        f"INSERT INTO trials ({cols}, publication_status, first_seen_run, last_seen_run) "
        f"VALUES ({marks}, 'not yet searched', :run_id, :run_id) "
        f"ON CONFLICT(nct_id) DO UPDATE SET {updates}, last_seen_run = excluded.last_seen_run",
        {**row, "run_id": run_id})


def sync_rows(con, table, id_col, cols, nct_id, new_rows, stats):
    """Make a trial's rows in `table` match the registry: identical rows stay as
    they are, new ones are added, ones no longer in the registry are removed,
    except rows that other tables point to, which are kept and counted."""
    col_list = ", ".join(cols)
    existing = con.execute(f"SELECT {id_col}, {col_list} FROM {table} WHERE nct_id = ?",
                           (nct_id,)).fetchall()
    wanted = Counter(new_rows)
    for row_id, *values in existing:
        values = tuple(values)
        if wanted[values] > 0:
            wanted[values] -= 1
        else:
            try:
                con.execute(f"DELETE FROM {table} WHERE {id_col} = ?", (row_id,))
                stats[table]["removed"] += 1
            except sqlite3.IntegrityError:
                stats[table]["kept (used elsewhere)"] += 1
    marks = ", ".join("?" for _ in cols)
    for values, n in wanted.items():
        for _ in range(n):
            con.execute(f"INSERT INTO {table} (nct_id, {col_list}) VALUES (?, {marks})",
                        (nct_id, *values))
            stats[table]["added"] += 1


def sync_arms(con, nct_id, new_rows, stats):
    """Arms are matched by label (extracted values point to them by label)."""
    labels = set()
    for label, arm_type, description in new_rows:
        labels.add(label)
        old = con.execute("SELECT arm_type, description FROM arms "
                          "WHERE nct_id = ? AND arm_label = ?", (nct_id, label)).fetchone()
        if old is None:
            con.execute("INSERT INTO arms (nct_id, arm_label, arm_type, description) "
                        "VALUES (?, ?, ?, ?)", (nct_id, label, arm_type, description))
            stats["arms"]["added"] += 1
        elif tuple(old) != (arm_type, description):
            con.execute("UPDATE arms SET arm_type = ?, description = ? "
                        "WHERE nct_id = ? AND arm_label = ?",
                        (arm_type, description, nct_id, label))
            stats["arms"]["updated"] += 1
    for (label,) in con.execute("SELECT arm_label FROM arms WHERE nct_id = ?",
                                (nct_id,)).fetchall():
        if label not in labels:
            try:
                con.execute("DELETE FROM arms WHERE nct_id = ? AND arm_label = ?",
                            (nct_id, label))
                stats["arms"]["removed"] += 1
            except sqlite3.IntegrityError:
                stats["arms"]["kept (used elsewhere)"] += 1


# ---------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", action="store_true",
                        help="only print how many trials match, then stop")
    args = parser.parse_args()

    if args.count:
        total = count_matches(QUERY)
        print(f"Trials matching SPEC.md: {total}")
        print("Summary: records in 0, out 0, skipped 0 (count only; nothing downloaded or saved)")
        return

    if not DB_PATH.exists():
        raise StopError(f"{DB_PATH} does not exist. Run scripts\\create_database.py first.")

    print("Downloading matching trials from ClinicalTrials.gov ...")
    no_start_date = count_matches(NO_START_DATE_QUERY)
    studies = download_all()

    con = connect()
    try:
        run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        run_id = con.execute("INSERT INTO fetch_runs (run_date, query_used) VALUES (?, ?)",
                             (run_date, QUERY)).lastrowid
        skipped, seen = Counter(), set()
        new_trials = updated_trials = 0
        stats = {t: Counter() for t in
                 ("conditions", "interventions", "arms", "registered_outcomes",
                  "trial_countries", "intervention_mesh")}
        populations = Counter()
        definition_only = []
        stored_now_failing = []
        for nct_id, study in studies:
            if nct_id in seen:
                skipped["appeared twice in the download"] += 1
                continue
            seen.add(nct_id)
            reason = rule_failure(study)
            if reason:
                skipped[f"failed local check: {reason}"] += 1
                if con.execute("SELECT 1 FROM trials WHERE nct_id = ?",
                               (nct_id,)).fetchone():
                    stored_now_failing.append(f"{nct_id} ({reason})")
                continue
            exists = con.execute("SELECT 1 FROM trials WHERE nct_id = ?",
                                 (nct_id,)).fetchone()
            row = trial_row(nct_id, study)
            upsert_trial(con, row, run_id)
            populations[f"{row['population']} (from {row['population_source']})"] += 1
            raw_why = study["protocolSection"].get("statusModule", {}).get("whyStopped")
            if is_status_definition(raw_why):
                definition_only.append(nct_id)
            if exists:
                updated_trials += 1
            else:
                new_trials += 1
            sync_rows(con, "conditions", "condition_id",
                      ["condition_text", "mesh_term", "mesh_id", "match_type"],
                      nct_id, condition_rows(study), stats)
            sync_rows(con, "interventions", "intervention_id",
                      ["intervention_type", "name", "other_names", "description"],
                      nct_id, intervention_rows(study), stats)
            sync_arms(con, nct_id, arm_rows(study), stats)
            sync_rows(con, "registered_outcomes", "registered_outcome_id",
                      ["outcome_type", "measure", "time_frame", "description"],
                      nct_id, outcome_rows(study), stats)
            sync_rows(con, "trial_countries", "rowid", ["country"],
                      nct_id, [(c,) for c in countries(study)], stats)
            sync_rows(con, "intervention_mesh", "rowid",
                      ["mesh_term", "mesh_id", "match_type"],
                      nct_id, intervention_mesh_rows(study), stats)

        kept = new_trials + updated_trials
        reasons = dict(skipped)
        reasons["excluded by the search: no start date (not downloaded)"] = no_start_date
        con.execute("UPDATE fetch_runs SET records_in = ?, records_kept = ?, "
                    "records_skipped = ?, skip_reasons = ? WHERE run_id = ?",
                    (len(studies), kept, sum(skipped.values()),
                     json.dumps(reasons), run_id))
        not_seen = con.execute("SELECT COUNT(*) FROM trials WHERE last_seen_run <> ?",
                               (run_id,)).fetchone()[0]
        con.commit()
    except Exception:
        con.rollback()
        con.close()
        raise
    con.close()

    print()
    print(f"Run {run_id} on {run_date}")
    print(f"Raw files saved in: {RAW_DIR}")
    for table, c in stats.items():
        detail = ", ".join(f"{k} {v}" for k, v in c.items()) or "no changes"
        print(f"  {table}: {detail}")
    print("Population labels:")
    for label, n in sorted(populations.items()):
        print(f"  {label}: {n}")
    if not_seen:
        print(f"Trials in the database that no longer match the search: {not_seen} "
              "(kept, not deleted)")
    if stored_now_failing:
        print(f"WARNING: {len(stored_now_failing)} trials in the database now fail a "
              "local check and were not updated: " + ", ".join(stored_now_failing))
        print("  Run scripts\\apply_inclusion_rule.py to remove them.")
    print(f"Why Stopped that only repeats a registry status definition (stored as empty): "
          f"{len(definition_only)}" + (f" ({', '.join(definition_only)})" if definition_only else ""))
    print(f"Excluded for having no start date: {no_start_date}")
    print(f"Summary: records in {len(studies)}, out {kept} "
          f"({new_trials} new, {updated_trials} updated), "
          f"skipped {sum(skipped.values())}"
          + (f" ({', '.join(f'{k}: {v}' for k, v in skipped.items())})" if skipped else ""))


if __name__ == "__main__":
    try:
        main()
    except (StopError, sqlite3.Error, OSError) as e:
        print(f"\nSTOPPED: {e}")
        print("Nothing was changed in the database.")
        print("Summary: stopped on error; see the message above.")
        sys.exit(1)
