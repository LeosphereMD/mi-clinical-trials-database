"""Write the small input files the three paper agents read (SPEC.md decisions 26, 31-33).

Usage:
    .venv\\Scripts\\python scripts\\prepare_agent_inputs.py NCT01225562 [NCT... ...]
    .venv\\Scripts\\python scripts\\prepare_agent_inputs.py --all   # every trial on the paper list

For each trial (registry and review files only; no paper text):
  - outcome_checks/inputs/<NCT>.json (outcome-checker): paper files and PMIDs, the
    registered primary outcomes (id, measure, time frame, description) and which of
    them each paper covers (decision 31). Not written if extractions/<NCT>.json
    already exists: the outcome-checker must run before the extractor (decision 26).
  - extractions/inputs/<NCT>.json (extractor): paper files and PMIDs, the registry
    arm labels with each arm's drugs and doses as the registry gives them, the
    factorial comparison names (decision 31) and whether the trial was terminated.
    No registered outcome text and no population or timing label (decision 33).
  - verifications/inputs/<NCT>.json (verifier): paper files and PMIDs, the arms (as
    above), the registry population label and timing label, each with its source.
All three folders are git-ignored. Nothing is written to the database.
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from create_database import DB_PATH, connect
from review_files import REVIEW_DIR, read_csv

ROOT = Path(__file__).resolve().parent.parent
PAPER_LIST = REVIEW_DIR / "paper_list.csv"
PAPERS_DIR = ROOT / "papers"
OUT = {"outcome-checker": ROOT / "outcome_checks" / "inputs",
       "extractor": ROOT / "extractions" / "inputs",
       "verifier": ROOT / "verifications" / "inputs"}

# Factorial trials (decision 31): the comparison each main paper reports and the
# registered primary outcomes it covers. Each outcome id is checked against the
# registry description (it must name the comparison), so a renumbered outcome after
# a new download stops the script instead of being linked to the wrong paper.
FACTORIAL = {
    "NCT03048825": {
        "papers": {
            "39555814": {"comparison": "spironolactone vs placebo", "outcome_ids": [650, 651],
                         "must_mention": "spironolactone comparison"},
            "39555823": {"comparison": "colchicine vs placebo", "outcome_ids": [649],
                         "must_mention": "colchicine comparison"},
        },
        "not_assessed": {648: "not assessed (stent performance-goal comparison; no drug "
                              "paper covers it)"},
    },
}


class StopError(Exception):
    pass


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main_papers(nct_id, paper_rows):
    """[{file, pmid, title, owner_decision}] for the trial's main papers."""
    papers = []
    for r in paper_rows:
        if r["nct_id"] == nct_id and (r.get("file_name") or "").strip():
            pdf = PAPERS_DIR / r["file_name"].strip()
            if not pdf.exists():
                raise StopError(f"{nct_id}: {pdf.name} is not in papers/.")
            papers.append({"file": f"papers/{pdf.name}", "pmid": r["pmid"], "title": r["title"],
                           "owner_decision": (r.get("decision") or "").strip() or "not reviewed"})
    if not papers:
        raise StopError(f"{nct_id}: no main paper with a file name in {PAPER_LIST.name}.")
    return papers


def arms_with_drugs(con, nct_id, raw):
    """Registry arms, each with its type, description and linked interventions
    (name, generic name, role and the registry description), as the registry gives them."""
    module = raw["protocolSection"].get("armsInterventionsModule", {})
    stored = {r[0]: r for r in con.execute(
        "SELECT name, intervention_type, generic_name, intervention_role FROM interventions "
        "WHERE nct_id = ?", (nct_id,))}
    links = {}
    for i in module.get("interventions", []):
        name = (i.get("name") or "").strip()
        s = stored.get(name)
        item = {"type": i.get("type"), "name": name,
                "generic_name": s[2] if s else None, "role": s[3] if s else None,
                "registry_description": " ".join((i.get("description") or "").split()) or None}
        for label in i.get("armGroupLabels", []):
            links.setdefault(label, []).append(item)
    return [{"arm_label": label, "arm_type": arm_type,
             "registry_description": " ".join((desc or "").split()) or None,
             "interventions": links.get(label, [])}
            for label, arm_type, desc in con.execute(
                "SELECT arm_label, arm_type, description FROM arms WHERE nct_id = ? "
                "ORDER BY arm_id", (nct_id,))]


def prepare(con, nct_id, paper_rows, stats):
    row = con.execute("SELECT overall_status, population, population_source, timing_after_mi, "
                      "timing_after_mi_source, raw_json_file FROM trials WHERE nct_id = ?",
                      (nct_id,)).fetchone()
    if not row:
        raise StopError(f"{nct_id} is not in the database.")
    status, pop, pop_src, timing, timing_src, raw_file = row
    raw = json.loads((ROOT / raw_file).read_text(encoding="utf-8"))
    papers = main_papers(nct_id, paper_rows)
    arms = arms_with_drugs(con, nct_id, raw)
    outcomes = [{"registered_outcome_id": o[0], "measure": o[1], "time_frame": o[2],
                 "description": o[3]}
                for o in con.execute("SELECT registered_outcome_id, measure, time_frame, "
                                     "description FROM registered_outcomes WHERE nct_id = ? "
                                     "AND outcome_type = 'primary' ORDER BY registered_outcome_id",
                                     (nct_id,))]
    by_id = {o["registered_outcome_id"]: o for o in outcomes}
    factorial = FACTORIAL.get(nct_id)
    not_assessed = []
    for p in papers:
        if factorial:
            setting = factorial["papers"].get(p["pmid"])
            if not setting:
                raise StopError(f"{nct_id}: paper PMID {p['pmid']} is not in the factorial mapping.")
            for oid in setting["outcome_ids"]:
                text = (by_id.get(oid) or {}).get("description") or ""
                if setting["must_mention"] not in text.lower():
                    raise StopError(f"{nct_id}: registered outcome #{oid} does not mention "
                                    f"'{setting['must_mention']}'; check the factorial mapping.")
            p["comparison"] = setting["comparison"]
            p["registered_outcome_ids"] = setting["outcome_ids"]
        else:
            p["registered_outcome_ids"] = [o["registered_outcome_id"] for o in outcomes]
    if factorial:
        not_assessed = [{"registered_outcome_id": oid, "reason": reason}
                        for oid, reason in factorial["not_assessed"].items()]

    shared = {"nct_id": nct_id, "prepared_by": "scripts/prepare_agent_inputs.py"}
    # Extractor: no registered outcome text, no population or timing label (decision 33).
    write_json(OUT["extractor"] / f"{nct_id}.json", {
        **shared, "terminated": status == "TERMINATED",
        "factorial": bool(factorial),
        "papers": [{k: v for k, v in p.items() if k != "registered_outcome_ids"} for p in papers],
        "arms": arms})
    stats["extractor inputs written"] += 1
    write_json(OUT["verifier"] / f"{nct_id}.json", {
        **shared, "factorial": bool(factorial),
        "papers": [{k: v for k, v in p.items() if k != "registered_outcome_ids"} for p in papers],
        "arms": arms,
        "registry_population": {"label": pop, "source": pop_src},
        "registry_timing_after_mi": {"label": timing, "source": timing_src}})
    stats["verifier inputs written"] += 1
    if (ROOT / "extractions" / f"{nct_id}.json").exists():
        stats["outcome-checker skipped: extraction already exists"] += 1
        return f"{nct_id}: extractor + verifier inputs written; outcome-checker input SKIPPED " \
               f"(extractions/{nct_id}.json exists, decision 26)"
    write_json(OUT["outcome-checker"] / f"{nct_id}.json", {
        **shared, "papers": papers, "registered_primary_outcomes": outcomes,
        "not_assessed": not_assessed})
    stats["outcome-checker inputs written"] += 1
    return f"{nct_id}: 3 inputs written ({len(papers)} paper(s), {len(arms)} arms, " \
           f"{len(outcomes)} registered primary outcome(s))"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("nct_ids", nargs="*")
    parser.add_argument("--all", action="store_true", help="every trial on the paper list")
    args = parser.parse_args()
    if not DB_PATH.exists() or not PAPER_LIST.exists():
        raise StopError("the database or review/paper_list.csv is missing.")
    paper_rows = read_csv(PAPER_LIST)
    ids = args.nct_ids or (sorted({r["nct_id"] for r in paper_rows if r.get("file_name")})
                           if args.all else [])
    if not ids:
        raise StopError("give one or more NCT IDs, or --all.")
    con = connect()
    stats, lines = Counter(), []
    try:
        for nct_id in ids:
            lines.append(prepare(con, nct_id.strip().upper(), paper_rows, stats))
    finally:
        con.close()
    for line in lines:
        print(f"  {line}")
    print(f"Summary: records in {len(ids)} trials, out "
          f"{stats['extractor inputs written'] + stats['verifier inputs written'] + stats['outcome-checker inputs written']}"
          f" input files ({', '.join(f'{k} {v}' for k, v in stats.items())}), skipped "
          f"{stats['outcome-checker skipped: extraction already exists']} outcome-checker "
          "inputs (extraction already exists)")


if __name__ == "__main__":
    try:
        main()
    except (StopError, sqlite3.Error, OSError, KeyError) as e:
        print(f"STOPPED: {e}")
        print("Summary: stopped on error; files written before the error are listed above.")
        sys.exit(1)
