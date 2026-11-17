# MI and ACS drug trials: a reviewed database built with AI agents

> **DRAFT** (2026-11-17), not yet approved by the project owner. All numbers come from
> `data/ami_trials.db` and the Quality log in `SPEC.md` on that date.

A SQLite database of **Phase 3 and Phase 2/3 drug trials in MI and ACS patients started on or
after 2010-01-01, labelled by timing (acute / recent / prior MI)**. It currently holds 140 trials,
built from the public ClinicalTrials.gov registry. Results from the published papers are added by
AI agents and checked by a second agent, by code and by a human reviewer.

*Author: [name], medical sciences graduate. [one line on background and goals]*

## Why this project

Registry records say what a trial planned; papers say what it found. Comparing the two at scale
takes careful reading. This project tests a workflow where AI agents do the reading and every
number stays traceable to a page and an exact quote, so a human can check it quickly. The human
reviewer has the final say.

## What is in the database (registry snapshot of 2026-11-15)

| | Trials |
|---|---|
| All | 140 |
| Phase 3 / Phase 2/3 | 122 / 18 |
| Timing after MI: acute / recent / prior | 115 / 18 / 7 |
| Population: STEMI / STEMI + NSTEMI / NSTEMI / ACS mixed / MI unspecified | 64 / 23 / 3 / 41 / 9 |
| Status: completed / terminated / withdrawn / other (recruiting, unknown, ...) | 74 / 7 / 2 / 57 |
| Lead sponsor: industry / academic and other / government | 32 / 102 / 6 |

Each trial carries:
- registry fields: phase, status, dates, enrollment, sponsor, arms, interventions, outcomes,
  countries
- cleaned fields: generic drug names, sponsor groups, why-stopped categories, primary outcome
  type, population and timing labels
- a record of where each label came from: a rule, a draft, or owner approved

## First registry findings

From `review/registry_analyses.md`. The 2 withdrawn trials (no patients enrolled) are left out,
so these figures cover 138 trials.

- **Primary outcome type:** 88 of 138 trials (64%) have only surrogate primary outcomes, such as
  infarct size, biomarkers or imaging. 40 (29%) have only clinical-event primary outcomes.
- **Phase 2/3 trials:** 16 of 17 have only surrogate primary outcomes.
- **Small surrogate-only trials:** 81 trials (59%) are surrogate-only and enrol fewer than 500
  patients.
- **Acute-only trials (114):** the picture is similar. 69% are surrogate-only, and 64% are small
  surrogate-only trials.
- **Terminated (7) and withdrawn (2) trials:** reported separately. The most common reasons are
  lack of efficacy or futility (2) and COVID-19 (2).

## How it was built

| Step | What happens | Who |
|---|---|---|
| 1-2 | Download from the ClinicalTrials.gov API, apply the inclusion rules, load into SQLite | Python scripts |
| 2a | Clean drug names, sponsors, stop reasons and outcome types: scripts draft, the owner approves | scripts + owner |
| 2b | Hand-check a random sample of registry values against the website | owner |
| 3 | Pick the 10 largest completed or terminated trials with a main results paper; the owner places the PDFs | owner |
| 3b-5 | Three AI agents (Claude Code): an outcome-checker reads the primary endpoint; an extractor pulls the results with an exact quote, page and confidence for every value; a verifier finds the key numbers on its own, then judges every value | AI agents |
| 6 | Code checks: every quote must be found word for word on its stated page; the verifier's independent numbers are compared with the extractor's | Python scripts |
| 7 | The owner reviews **every** extracted value in a spreadsheet | owner |

Every decision is written down in `SPEC.md` (34 numbered decisions so far), and every data
problem in its Quality log.

## Quality controls (examples from the Quality log)

- **Registry hand-check:** 0 of 70 sampled registry values were wrong (95% CI 0-5%). Population
  labels had 3 errors in 46 checks. The cause was found in the labelling rules, the rules were
  changed, and every affected label was re-checked.
- **Exclusions:** 196 downloaded trials became 140 after documented exclusion rounds, each trial
  with its reason, for example MI named only as an outcome, or a population with no MI.
- **Two AI agents can make the same mistake.** In one trial, the extractor and the verifier both
  dropped the same word from a quote, in two separate runs. Only the code quote check caught it.
  This is why code checks and full human review sit on top of the agents.
- **The registry is not always up to date.** One trial is "completed" in the registry, but its
  paper reports it was stopped early for futility. The paper value is recorded, and the registry
  snapshot is left unchanged.

## Results from the papers

*Placeholder: filled in after the owner's review of the extracted values (pilot: 10 trials, 11
papers).*

## Tech

- Python, using only the standard library, `requests`, `pandas`, `pypdf` and `openpyxl`
- SQLite
- Claude Code agents, defined in `.claude/agents/`

## Reproduce

1. Create the virtual environment and install `requirements.txt`.
2. Run the scripts in `scripts/` in pipeline order, starting with `create_database.py` and
   `fetch_trials.py`. *[exact commands to be added]*

Every script prints how many records came in, went out and were skipped.

## Data and privacy

- Committed: the registry data and the review decisions.
- Never committed: paper PDFs, paper quotes, the full database and the agent outputs.
- A public export without quotes is planned.

## Limitations

- **Snapshot date:** the registry data is a snapshot from 2026-11-15.
- **Unreviewed drafts:** some labels are drafts that were not individually reviewed: 77 of 140
  timing labels and 137 of 184 primary-outcome types. Review samples are documented in the
  Quality log.
- **Pilot size:** paper results so far cover a pilot of the 10 largest trials, and no paper
  supplements have been used yet.
