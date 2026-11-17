# Myocardial infarction (MI) and acute coronary syndrome (ACS) drug trials: a database built with AI-assisted extraction and full human review

This project builds a database of **Phase 3 and Phase 2/3 drug trials in myocardial infarction
(MI) and acute coronary syndrome (ACS) patients started on or after 2010-01-01, labelled by timing
(acute / recent / prior MI)**, from the public ClinicalTrials.gov registry: 140 trials as of the 2026-11-15 snapshot. For the 10 largest trials,
results were extracted from the published papers by AI agents, checked by a second, independent
agent and by code, and then reviewed value by value by a human. Every number stays traceable to a
page and an exact quote in the paper, so any value can be checked against its source.

## Key findings from the registry

The 2 withdrawn trials (no patients enrolled) are left out, so these figures cover 138 trials;
the 7 terminated trials are included.

![Primary outcome type by phase](figures/outcome_type_by_phase.png)

- **Most trials rely on surrogate outcomes.** 88 of 138 trials (64%) have only surrogate primary
  outcomes, such as infarct size, biomarkers or imaging; 40 (29%) have only clinical-event
  primary outcomes.
- **Phase 2/3 trials almost never measure clinical events.** 16 of 17 (94%) have only surrogate
  primary outcomes; none has only clinical-event outcomes.
- **Surrogate-only trials are small.** 81 of the 88 surrogate-only trials (92%) enrol fewer than
  500 patients; that is 59% of all 138 trials.
- **Acute-only trials (114) show the same pattern:** 79 (69%) are surrogate-only, and 73 (64%)
  are small surrogate-only trials.
- **Most tested drug classes** (study drugs only): antiplatelets (35 trials, 25%; P2Y12
  inhibitors, e.g. clopidogrel or ticagrelor, in 32), glucose-lowering drugs (19 trials, 14%;
  SGLT2 (sodium-glucose cotransporter 2) inhibitors in 13),
  anti-inflammatory and lipid-modifying drugs (11 trials each), and anticoagulants and
  fibrinolytics (9 each). Classes are named by mechanism ("parent: mechanism", e.g.
  "antiplatelet: P2Y12 inhibitor"): 73 drugs in 27 parent classes, each reviewed by hand.
- **Terminated trials (7)** stopped for lack of efficacy or futility (2), COVID-19 (2), a
  healthcare system change (1), an unclear reason (1) or no stated reason (1).

What the database holds (registry snapshot of 2026-11-15):

| | Trials |
|---|---|
| All | 140 |
| Phase 3 / Phase 2/3 | 122 / 18 |
| Timing after MI: acute / recent / prior | 115 / 18 / 7 |
| Population: ST-elevation MI (STEMI) / STEMI + non-ST-elevation MI (NSTEMI) / NSTEMI / ACS mixed / MI unspecified | 64 / 23 / 3 / 41 / 9 |
| Status: completed / terminated / withdrawn / other (recruiting, unknown, ...) | 74 / 7 / 2 / 57 |
| Lead sponsor: industry / academic and other / government | 32 / 102 / 6 |

Each trial has its registry fields (phase, status, dates, enrollment, sponsor, arms,
interventions, outcomes, countries), cleaned fields (generic drug names, drug classes, sponsor
groups, reasons for stopping, primary outcome type, population and timing labels), and a record of
where each label came from: a rule, an AI draft, or a human decision.

## How it was built

**Registry part**

1. Download all matching trials from the ClinicalTrials.gov API (its public data interface),
   apply the inclusion rules and load them into SQLite (a single-file database).
2. Clean the registry fields (drug names, drug classes, sponsors, reasons for stopping, outcome
   types, population and timing): code or an AI model drafts each value, and a human approves it.
   Each value records whether it was decided individually or went in as a draft.
3. Hand-check a random sample of registry values against the ClinicalTrials.gov website.

**Paper part** (pilot: the 10 largest completed or terminated trials with a main results paper; 11
papers, because one factorial trial reports each comparison in its own paper; 8 of the 10 are
industry-sponsored)

```
paper PDF
  -> outcome-checker   reads the primary endpoint on its own, before any extraction
  -> extractor         pulls every result with an exact quote, page and confidence
  -> verifier          finds the key numbers independently, then judges every value
  -> code checks       every quote found word for word on its page; numbers compared
  -> human review      every value approved or corrected; decisions are permanent
  -> database
```

- The **extractor** collects the number of patients (N) per arm, events, effect size, 95%
  confidence interval (CI), p-value, endpoint
  definitions, a key secondary outcome and safety outcomes. A value it cannot find is marked
  "not reported", never guessed.
- The **verifier** cannot see the extraction until it has written down its own key numbers, and
  then marks each value confirmed, wrong, not in paper or unclear.
- **Human decisions** can never be edited or deleted, only superseded by a newer decision.

Every design decision and every data problem found is recorded in [SPEC.md](SPEC.md).

## Data quality

**Paper values (all 590 reviewed by a human)**

| | |
|---|---|
| Values extracted | 590 (73 of them "not reported") |
| Human-reviewed | 590 of 590 (100%) |
| Corrected by the reviewer | 5 |
| Flagged by the verifier or code, then reviewed | 21 (3 needed a correction) |
| Not flagged, but wrong on review | 2 of 569 (0.4%) |

![Where problems were caught](figures/quality_checks.png)

- **The 5 corrections:** No extracted number was incorrect; 2 numbers reported in the paper were
  missed (recorded as 'not reported') and 3 text values were trimmed to what their quote
  supports. The 2 missed numbers were denominators printed only in a table header; the 3 text
  values held the agent's own inference or a clause from another sentence, while the underlying
  fact was right.
- **Code catches what two agents miss.** In one trial, the extractor and the verifier dropped the
  same word from the same quote, in two separate runs. Only the code quote check caught it.
- **Agent flags point to hard cases; they are not verdicts.** The verifier marked 13 values wrong
  or unclear; on review, 3 of them needed a correction. Its flags led the reviewer to cases such
  as patients excluded after randomization.
- **The review improved the rules.** Its findings became written rules for the agents (a quote
  must contain the value and start at the beginning of a sentence; a value contains only what its
  quote says; denominators in table headers; how a testing order is read), and the quote check
  was fixed for two false alarms (en dashes; quotes that resume after a table several pages
  later).
- **Reviewer decisions are checked against the rules too.** One review decision conflicted with a
  written rule (patients excluded after randomization belong in "N analysed", not "N
  randomized"); it was caught when the decisions were loaded, and the reviewer reverted it.

**Registry data**

- **Hand-check:** 0 of 70 sampled registry values were wrong (95% CI 0-5%). Population labels had
  3 errors in 46 checks; the cause was traced to the labelling rules, the rules were changed, and
  every affected label was re-checked.
- **Exclusions:** 196 downloaded trials became 140 after documented exclusion rounds, each trial
  with its reason, for example MI named only as an outcome, or a population with no MI.
- **The registry is not always up to date.** One trial is "completed" in the registry, but its
  paper reports it was stopped early for futility. The paper value is recorded; the registry
  snapshot is left unchanged.

## Limitations

- **Snapshot:** registry data from ClinicalTrials.gov, fetched 15 Nov 2026; later changes to the
  registry are not included.
- **Drafts without individual review:** of 184 primary-outcome types, 47 were decided
  individually and 137 were high-confidence drafts that went in without individual review; a
  random check of 31 found no errors (estimated accuracy 89-100%, 95% CI). Timing labels: 63
  decided individually and 77 drafts that went in without individual review; a random check of
  10 timing labels (6 of them drafts) found no errors (estimated accuracy 69-100%, 95% CI).
- **Pilot size and selection:** paper results cover only the 10 largest trials (mostly
  industry-sponsored, 6,000-21,000 patients each). Error rates in smaller, academic trials with
  less standard reporting may differ.
- **One reviewer:** every value was reviewed by one person; there is no second human reviewer.
- **Agents not re-run:** the rules added after the review apply to future runs; the pilot values
  were corrected by hand, not re-extracted.
- **Supplements and figures:** no paper supplements were used, and the quote check cannot read
  text inside figures (2 verifier quotes from a flow-chart box could not be checked by code).
- **Drug classes** describe each study drug's main mechanism; a trial can test drugs from several
  classes.

## Next steps

1. Re-run the three agents on the pilot with the new rules and compare with the reviewed values.
2. Extend paper extraction beyond the 10 largest trials, including smaller academic trials.
3. Compare each trial's registered primary outcome with the one reported in the paper.
4. Publish a CSV export of the database without paper quotes.

## Repository layout

| Folder | Contents |
|---|---|
| `scripts/` | Python scripts for every step (each prints records in / out / skipped) |
| `.claude/agents/` | Instructions for the three AI agents (Claude Code) |
| `data/raw/` | The registry downloads (public ClinicalTrials.gov records in JSON, a machine-readable text format) |
| `review/` | The human review record: approved drug names, drug classes, sponsors, labels, registry hand-check, and the registry analyses |
| `figures/` | The charts in this README |
| `SPEC.md` | Full specification, decision record and quality log |

Paper PDFs, quotes from papers, the full database and the agents' working files are kept out of
the repository; committed files hold numbers, page references and DOIs (digital object identifiers) only.

## How to reproduce

Requires Python and the packages in `requirements.txt` (standard library plus `requests`,
`pandas`, `pypdf`, `openpyxl`, `matplotlib`) and SQLite. Run the scripts with the project's
virtual environment:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\create_database.py
.venv\Scripts\python scripts\fetch_trials.py
.venv\Scripts\python scripts\load_cleaning.py
.venv\Scripts\python scripts\load_outcome_types.py
.venv\Scripts\python scripts\load_timing.py
.venv\Scripts\python scripts\load_drug_classes.py
.venv\Scripts\python scripts\registry_analyses.py
.venv\Scripts\python scripts\make_figures.py
```

The load steps read the committed human review files in `review/`. A new download reflects the
registry on the day it runs, so counts can differ from the 2026-11-15 snapshot. The paper part
needs the PDFs, which are not included.

## Author

Nadav Fertel
