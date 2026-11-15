# Specification: AMI Phase 3 Drug Trials Database

## Goal
Build a SQLite database of Phase 3 drug trials in acute myocardial infarction
that started on or after 1 January 2010. The trial data comes from the
ClinicalTrials.gov registry. Then add results from the published papers: AI
agents extract them, a second step verifies them, and the project owner reviews
every value. This is a portfolio project, so it should be reproducible and
transparent.

## Data source
- ClinicalTrials.gov API v2: `https://clinicaltrials.gov/api/v2/studies`
  (public, no login, returns JSON, paged with `pageToken`).
- Papers: PDFs the project owner finds and places in `papers/` by hand. The
  project never downloads papers automatically.

## Inclusion criteria (settled; see Decisions 1-5)
- Condition: MeSH condition terms include "Myocardial Infarction" (or a child
  term) or "Acute Coronary Syndrome"
- Phase: Phase 3 or Phase 2/3
- Intervention: at least one DRUG or BIOLOGICAL intervention
- Start date: 2010-01-01 or later (actual or anticipated); trials with no start
  date are excluded and counted
- Status: all statuses (paper extraction only for completed and terminated)

## Pipeline
| # | Stage | Output folder | Who |
|---|---|---|---|
| 1 | Fetch trials from the API | `data/` (raw JSON) | script |
| 2 | Load into SQLite | `data/` | script |
| 2a | Registry cleaning: generic drug names, sponsor names and groups, why_stopped categories (see "Registry cleaning") | `review/` | script drafts, project owner approves, script loads |
| 2b | Registry hand-check: a sample of registry values checked against the ClinicalTrials.gov website (see "Registry hand-check") | `review/` | script makes the sheet, project owner checks |
| 3 | Find the papers and place the PDFs | `papers/` | project owner, by hand |
| 4 | Extract results from the PDFs | `extractions/` | AI agent |
| 5 | Verify each extracted value against the PDF | `verifications/` | second AI agent |
| 6 | Automatic consistency checks | `checks/` | script |
| 7 | Human review: accept, reject or correct | `review/` | project owner |
| 8 | Load reviewed results into SQLite | `data/` | script |
| 9 | Outcome-switch check: registered vs. reported primary outcome (Phase 3 of the build, after the extractor and verifier exist; see "Outcome-switch check") | `outcome_checks/` | AI agent + script, then project owner |

## Ground rules
- A missing value stays empty. It is never guessed.
- Every script prints records in / out / skipped.
- Every extracted value must be traceable to its source (paper, page, quote).

## Decisions
Settled by the project owner on 2026-11-14.

1. **Condition definition.** AMI only, or also STEMI, NSTEMI and acute coronary
   syndrome (ACS) in general? Which search terms or MeSH terms count?
   Choice: Acute MI and acute coronary syndrome. Keep a trial if its MeSH condition
   terms include "Myocardial Infarction" (or a child term) or "Acute Coronary
   Syndrome". Add a population column: STEMI / NSTEMI / MI unspecified /
   ACS (mixed). Every analysis can be run for all trials and for MI-only trials.
   Updated 2026-11-15: five population labels with a source column; see
   "Population label".
2. **Phase.** Phase 3 only, or also combined "Phase 2/Phase 3" trials?
   Choice: Phase 3 and Phase 2/3. Store the phase label so Phase 2/3 can be
   filtered out later.
3. **What counts as a drug trial.** Intervention type DRUG only, or also
   BIOLOGICAL and COMBINATION_PRODUCT? Exclude trials that also test devices or
   procedures, or only trials with no drug arm at all?
   Choice: Keep trials with at least one DRUG or BIOLOGICAL intervention. Keep
   them even if they also include a device or procedure, with a flag
   has_device_or_procedure. Exclude trials with no drug or biological arm.
4. **Start date.** Use actual and anticipated start dates, or actual only? What
   happens to trials with no start date?
   Choice: Start date on or after 2010-01-01, actual or anticipated. Store the
   date type. Exclude trials with no start date and report how many were
   excluded.
5. **Recruitment status.** Include all statuses (including withdrawn, unknown,
   recruiting), or only completed and terminated trials?
   Choice: All statuses in the database. Extract from papers only for completed
   and terminated trials.
6. **Registry fields to store.** For example: NCT ID, title, sponsor, phase,
   status, start and completion dates, enrollment, arms and interventions,
   primary and secondary outcomes, countries, PMIDs listed in the record,
   whether results were posted.
   Choice: All of the listed fields, plus why_stopped, sponsor class, enrollment
   type (actual/estimated), allocation and masking, MeSH condition terms and
   last update date. Also keep the raw JSON for each trial.
7. **Results to extract from papers.** Primary outcome only, or also key
   secondary and safety outcomes? Which numbers: events per arm, N per arm,
   effect measure (HR / RR / OR / mean difference), 95% CI, p-value, follow-up
   time?
   Choice: Primary outcome, one key secondary outcome, and safety outcomes
   (major bleeding with its definition, serious adverse events, stopped drug due
   to side effects). Numbers: N randomized per arm, events per arm (n and %),
   effect measure (HR / RR / OR / mean difference) with value, 95% CI and
   p-value, median follow-up, the analysis population (e.g. ITT), the primary
   endpoint definition with each MACE component listed, and whether the primary
   endpoint was met.
8. **Finding papers.** Use the PMIDs listed in the registry record, a PubMed
   search by NCT number, or both? What if no paper exists?
   Choice: Both. Use the registry's RESULT references first, then a PubMed search
   by NCT number. If no paper exists, mark "no publication found" and keep the
   trial; the publication rate is itself a finding.
9. **Paper file naming.** For example `NCT01234567.pdf`. How to name and handle
   several papers for one trial (main results, secondary analyses)?
   Choice: Main results paper as NCT01234567.pdf, supplement as
   NCT01234567_supp.pdf. Extract only from the main results paper. List
   secondary analyses in the publications table, but don't download them.
10. **Verification.** Must every extracted value include a page number and a
    direct quote? Does the second agent work independently and get compared, or
    does it check the first agent's output?
    Choice: Yes, every value needs a page number and a direct quote, or "not
    reported". Hybrid: the verifier first finds the critical values on its own
    (N randomized, effect measure, value, 95% CI, p-value) and these are
    compared automatically. Then it checks every other field in the extractor's
    output. Code checks run after both agents.
11. **Review format.** An Excel sheet (one row per value, with
    accept / reject / correct and comment columns), or something else?
    Choice: An Excel sheet with one row per value: accept / reject / correct,
    corrected value, comment, and a column saying why the row is there (flagged
    or random sample). Include all flagged values plus a random 15% of the values
    that passed, with a fixed seed.
12. **Database layout.** Proposed tables: trials, interventions, outcomes
    (registry), publications, extracted_results, review_decisions. OK?
    Choice: OK, plus a conditions table for MeSH terms.
13. **Refresh policy.** A one-time snapshot (with the download date recorded),
    or re-runnable updates?
    Choice: Re-runnable updates. Log each run's download date. The README states
    the snapshot date the analysis used.
14. **Public sharing.** The repository will be a portfolio piece. Can quotes from
    papers appear in committed files, or should committed files hold only
    numbers and page references?
    Choice: Committed files hold numbers, page references and DOIs only. Quotes
    stay local: keep the full database and the extractions/ and verifications/
    folders out of git, and commit a public CSV export without quotes.

## Database design
Approved by the project owner on 2026-11-14. It extends decision 12 with `arms`
(decision 6) and `fetch_runs` (decision 13).

### Ground rules
- Missing means empty: a value the registry or paper doesn't give is NULL.
- Dates are stored as the registry gives them (sometimes only "2015-03"), with a
  separate column saying actual or estimated.
- The NCT ID ties everything together; every table points back to a trial.
- Quotes live only in the local database; the public CSV export leaves them out.

### Tables
1. **`trials`**: one row per trial. nct_id (key), title, phase_label,
   overall_status, why_stopped, start_date, start_date_type, completion_date,
   completion_date_type, enrollment, enrollment_type, lead_sponsor,
   sponsor_class, population (STEMI / NSTEMI / STEMI + NSTEMI / ACS mixed /
   MI unspecified; see "Population label"), population_source (mesh / title /
   conditions / eligibility), n_countries (number of distinct countries in
   `trial_countries`; empty if the registry lists no locations),
   has_device_or_procedure, allocation, masking, has_results, last_updated,
   publication_status (found / no publication found / not yet searched),
   raw_json_file, first_seen_run, last_seen_run.
2. **`conditions`**: conditions and MeSH terms per trial, showing why each trial
   passed the inclusion rule. nct_id, condition_text, mesh_term, mesh_id,
   match_type (direct term or parent term).
3. **`interventions`**: each drug, biological, device or procedure tested.
   nct_id, intervention_type, name, other_names, description.
4. **`arms`**: each study group, so per-arm numbers have something to link to.
   nct_id, arm_label, arm_type, description.
5. **`registered_outcomes`**: outcomes as registered before results. nct_id,
   outcome_type (primary / secondary), measure, time_frame, description.
6. **`publications`**: one row per paper. publication_id (key), pmid, doi,
   pmc_id, title, journal, year (all optional).
7. **`trial_publications`**: links trials to papers (one paper can report
   several trials; one trial can have several papers). nct_id, publication_id,
   role (main results / supplement / secondary analysis), found_via (registry
   reference / PubMed search), pdf_file.
8. **`extracted_values`**: one row per value an agent pulls from a paper.
   - What it is: value_id (key), nct_id, publication_id, arm (empty for
     whole-trial values such as a hazard ratio), outcome, field.
   - Extractor: extracted_value, quote, page, not_reported.
   - Verifier: verifier_value, verifier_quote, verifier_page, verifier_verdict
     (agree / disagree / not found), independent_match (critical values only).
   - Code checks: code_check_result (pass / fail / not run), code_check_note.
   - Review: review_reason (flagged / random sample / not selected / value
     changed after decision). The decisions themselves live in
     `review_decisions` (table 10).
   - Final: final_value, filled from the project owner's latest decision in
     `review_decisions`, or automatically only when every check passed and the
     value was not sampled.
   - Each value has a fixed identity: nct_id + publication_id + arm + outcome +
     field. Re-running an extraction updates the existing row in place, so its
     value_id, and every decision attached to it, stays the same.
9. **`fetch_runs`**: log of each ClinicalTrials.gov download. run_id, run_date,
   query_used, records_in, records_kept, records_skipped (with reasons). Its
   run_date gives the README's snapshot date.
10. **`review_decisions`**: the project owner's decisions, one row per decision
    (decision 12). decision_id (key), value_id (links to `extracted_values`),
    decision (approve / correct / reject; "approve" is decision 11's
    "accept"), corrected_value (required when the decision is correct),
    comment, decided_at, value_shown (the extracted value printed on the
    review sheet the owner decided from; it comes from the sheet, not from the
    database at loading time).
    - Changing your mind adds a new row. The latest row (by decided_at) counts
      and sets `extracted_values.final_value`: approve gives the extracted value,
      correct gives corrected_value, and reject leaves it empty.
    - Stale decisions go back to review (settled by the project owner on
      2026-11-15). If the current extracted value differs from the latest
      decision's value_shown (e.g. a re-run changed it), the value's
      review_reason becomes "value changed after decision", so it returns to
      the review sheet, and final_value is left empty until a new decision is
      added. The database does this automatically. If value_shown is missing,
      the value is treated as changed, so a mistake sends it back to review
      rather than letting it through.
    - Decisions are never deleted or edited, and an extracted value that has
      decisions cannot be deleted. The database itself blocks this, so
      re-running an extraction can't remove a decision.
11. **`outcome_comparisons`**: one row per trial, paper and registered primary
    outcome (see "Outcome-switch check"). comparison_id (key), nct_id,
    publication_id, registered_outcome_id (links to `registered_outcomes`),
    registered_text, paper_endpoint_quote, paper_endpoint_page,
    components_comparison, time_frame_comparison, measure_comparison (each
    same / different / not reported), comparison_note, change_mentions (every
    quote and page found by the keyword search), change_mentioned (yes / no),
    quote_check_result (pass / fail / not run), agents_agree (yes / no),
    status (MATCH / POSSIBLE_EXTRACTION_ERROR / DISCLOSED_CHANGE /
    UNDISCLOSED_DIFFERENCE), history_url, checked_at, and the project owner's
    final_classification (same four values), owner_comment, classified_at.
12. **`trial_countries`**: one row per country where a trial has sites (from
    the registry's location list, each country once). nct_id, country.
13. **`registry_checks`**: the project owner's registry hand-check decisions
    (see "Registry hand-check"). check_id (key), nct_id, field, db_value,
    selection_reason (random trial / text-based population / MeSH population
    sample), fetch_run_id (the download the value came from), decision
    (approve / correct / changed since download), corrected_value (required
    when the decision is correct), comment, decided_at.
14. **`intervention_mesh`**: the registry's drug MeSH terms per trial.
    nct_id, mesh_term, mesh_id, match_type (direct term or parent term).

Registry cleaning (step 2a) adds columns to two tables. To `trials`:
sponsor_name_clean, sponsor_group and why_stopped_category. To
`interventions`: generic_name and generic_name_source (registry MeSH exact
match / owner approved).

### How the tables connect
```
fetch_runs --(first/last_seen_run)--> trials
trials --1:many--> conditions, interventions, arms, registered_outcomes
trials --many:many via trial_publications--> publications
extracted_values --> trials, publications, arms (optional)
review_decisions --many:1--> extracted_values
outcome_comparisons --> trials, publications, registered_outcomes
trials --1:many--> trial_countries, registry_checks, intervention_mesh
```

## Population label
Added on 2026-11-15. It replaces the four labels in decision 1 with five.
Each trial gets one label and a population_source that says where the label
came from, so every label can be checked. The rules apply in this order; the
first one that fits wins.

1. MeSH condition terms include "Acute Coronary Syndrome" or "Angina,
   Unstable" → **ACS mixed** (source: mesh). This is the only way a trial
   gets this label.
2. MeSH terms include both "ST Elevation Myocardial Infarction" and
   "Non-ST Elevated Myocardial Infarction" → **STEMI + NSTEMI** (mesh).
3. MeSH terms include only the STEMI term → **STEMI**; only the NSTEMI term →
   **NSTEMI** (mesh).
4. MeSH gives only "Myocardial Infarction" (or other MI terms that are neither
   STEMI nor NSTEMI): search the text instead, in this order: the title, the
   conditions list, then the eligibility text. Search terms: "STEMI",
   "ST-elevation" and "ST-segment elevation" (STEMI); "NSTEMI",
   "non-ST-elevation" and "non-ST-segment elevation" (NSTEMI). The
   "ST-segment" forms were added on 2026-11-15.
   The first of the three that mentions either one sets the label: STEMI,
   NSTEMI, or STEMI + NSTEMI if both appear. Source: title, conditions or
   eligibility.
   - "NSTEMI" never counts as a hit for "STEMI", and "non-ST-elevation" never
     counts for "ST-elevation". A hyphen or a space is accepted ("ST elevation").
     "Non-STEMI" counts as NSTEMI, the same as "non-ST-elevation".
   - "The title" means both the brief and the official title.
   - Eligibility: only the inclusion criteria are searched, i.e. the text
     before the "Exclusion Criteria" heading (settled by the project owner on
     2026-11-15). If the text has no such heading, the eligibility text is not
     used, because an excluded group could give a wrong label.
5. No hit anywhere → **MI unspecified** (source: mesh).

The text search never produces ACS mixed.

## Registry cleaning
Added on 2026-11-15. This is pipeline step 2a, after the trials are loaded and
before the registry hand-check. Steps:
1. `scripts/draft_cleaning.py` writes three review files.
2. The project owner fills in the decision columns.
3. `scripts/load_cleaning.py` copies approved values into the database.

The only values that go in without approval are exact MeSH matches for drug
names (see below).

### Review files (all in `review/`, committed to git: no paper quotes)
- Every row has: decision (approve / correct, or blank = not reviewed yet),
  a corrected value column, and a comment column.
- Re-running the draft script never changes a row that has a decision. It
  refreshes the drafts in rows without one, and adds rows for new items.
- Files are UTF-8, so Excel shows accents correctly. The loader also accepts
  files Excel saves with semicolons.
- The approved CSV files are the record of the owner's decisions. The loader
  applies them again on every run, so a new download never loses them.

### 1. Generic drug names
- The registry's drug MeSH terms are stored in `intervention_mesh`
  (`fetch_trials.py` fills it). The registry gives them per trial, not per
  intervention.
- `interventions.generic_name` is filled automatically, without review, only
  when a DRUG or BIOLOGICAL intervention name equals one of that trial's MeSH
  terms, ignoring capital letters. generic_name_source = "registry MeSH exact
  match".
- Every other DRUG or BIOLOGICAL intervention goes into
  `review/drug_names.csv`, with a column suggested_generic, clearly marked as
  a suggestion, and its suggestion_source. They are tried in this order:
  1. "placebo": the name says placebo, and the name isn't a combination
     such as "Ticagrelor + placebo".
  2. "Claude, from general knowledge: check": written by Claude in
    `review/drug_name_suggestions_claude.csv`, each with a note. It is used
    for names the registry can't explain (e.g. study codes), and to correct
    registry partial matches that are misleading (e.g. "sacubitril/valsartan"
    matched only "valsartan"). Where Claude isn't sure, the suggestion is
    left empty and the note says why.
  3. "registry MeSH, partial match": the words of one of the trial's MeSH
    terms appear in the name or other names (salt words such as
    "Hydrochloride" or "Calcium" are ignored).
  4. Otherwise no suggestion.
- Suggestions go into the database only after the owner approves or corrects
  them (generic_name_source = "owner approved"). Names are stored in lower case.

### 2. Sponsor names and groups
- All lead sponsors (127 in the first download) go into `review/sponsors.csv`.
- sponsor_name_clean merges spellings of the same organization. The draft
  removes legal-form endings (Inc., LLC, Ltd, Co., AB, AG, GmbH, A/S, S.A. ...),
  and names that are then the same, ignoring capital letters, accents and
  punctuation, get one clean name. A possible_same_as column points out
  names where one is the start of another (e.g. "University of Sao Paulo" and
  "University of Sao Paulo General Hospital"), for the owner to decide.
- sponsor_group: industry / academic or hospital / research network or
  cooperative group / government / individual investigator. The draft uses
  the registry's sponsor class and keywords in the name, in this order:
  1. class NIH or FED → government
  2. network, cooperative, consortium, society, investigator or research
     group, foundation → research network or cooperative group
  3. region, NHS, social security, ministry → government
  4. university, hospital, clinic, medical center, institute, academy,
     college, school → academic or hospital
  5. class INDUSTRY or a company ending → industry
  6. class NETWORK → research network or cooperative group
  7. no organization word at all (class OTHER or OTHER_GOV) → individual
     investigator. This comes before the registry's government class, because
     the registry gives some individual doctors that class.
  8. anything left: no draft; the owner decides

  draft_basis shows which rule applied.
- Approved values go into `trials.sponsor_name_clean` and
  `trials.sponsor_group`.

### 3. why_stopped categories
- Every trial with a why_stopped text, or with status terminated, withdrawn or
  suspended, goes into `review/why_stopped.csv`.
- One category per trial: safety / lack of efficacy or futility / slow
  enrollment / COVID-19 / funding or commercial reasons / other sponsor
  decision / new outside evidence / regulatory / unclear / not stated (no
  reason given).
- The draft uses keywords, checked in this order, and the first match wins:
  1. safety
  2. new outside evidence
  3. lack of efficacy or futility
  4. COVID-19
  5. slow enrollment
  6. funding or commercial reasons
  7. regulatory
  8. other sponsor decision
  9. otherwise unclear
- Funding or commercial keywords include "market" (e.g. "market landscape").
- When the text only says "see detailed description", the detailed
  description is shown in the file and searched too.
- Approved values go into `trials.why_stopped_category`.

## Registry hand-check
Added on 2026-11-15. This is pipeline step 2b, after the trials are loaded. The
project owner compares database values with the trial's page on the
ClinicalTrials.gov website.

### What goes on the sheet
Random draws use a fixed seed, which is recorded in the script and printed on
the sheet.
1. **15 random trials**, with all key fields: phase, overall status, start
   date, enrollment and enrollment type, lead sponsor, primary outcome, and
   population.
2. **Every population label that came from text** (source title, conditions or
   eligibility), for the population field.
3. **A random 15% of the MeSH-based labels** (source mesh, rounded up), for the
   population field.

A trial picked in more than one way appears once per field, with every reason
listed.

### The sheet
An Excel file in `review/`, one row per trial and field. It shows:
- the NCT ID and a link to the trial's page (`https://clinicaltrials.gov/study/<NCT ID>`)
- the field and the database value
- for population: the source and the matching words
- why the row was picked, and the download date of the value
- columns for the decision (approve / correct / changed since download),
  corrected value and comment

"Changed since download" is for values the registry updated after our
download. These are not errors.

### Where decisions are stored
In `registry_checks` (table 13). Like `review_decisions`, rows are never edited
or deleted; a new decision is added instead. A correction does not overwrite
`trials`, because the next download would undo it. Analyses use the latest
correction where one exists.

## Population check against the paper (Phase 3)
Added on 2026-11-15. It is built in Phase 3, together with the verifier.
- The verifier reads the paper's study population (STEMI / NSTEMI / STEMI +
  NSTEMI / ACS mixed / MI unspecified), with an exact quote and page. It is
  stored as a whole-trial value in `extracted_values` (field "population").
- Code compares it with `trials.population` (or the latest registry-check
  correction, if there is one). A disagreement flags the value, so it goes
  to the project owner's review sheet with both labels, the paper quote and
  page, and the registry source.

## Outcome-switch check
Added on 2026-11-14. It is built in Phase 3, after the extractor and verifier
agents. Only the `outcome_comparisons` table exists before then.

### Goal
Compare the primary outcome registered on ClinicalTrials.gov with the primary
outcome the paper reports, and classify any difference.

### Agent: outcome-checker
- Finds the paper's primary endpoint in the Methods section on its own. It
  never sees `extractions/`. It gives the exact quote and the page.
- Compares the registered and reported primary outcome on three points:
  components (e.g. each MACE component), time frame, and measure. A difference
  in wording alone is not a change.
- Searches the whole paper for "amendment", "originally", "changed" and
  "revised", and gives the quote and page for every hit.
- Writes its output to `outcome_checks/` (kept out of git, because it holds
  quotes).

### Script (no AI): assigns a status
- **MATCH**: the agents agree on what the paper says, and the paper's primary
  outcome matches the registered one.
- **POSSIBLE_EXTRACTION_ERROR**: the agents disagree on what the paper says:
  the outcome-checker's primary endpoint doesn't match the extractor's. Also
  used when the paper differs, the quotes fail the code check, and no change
  is mentioned (settled by the project owner on 2026-11-14): a quote that
  can't be found on its page can't support an UNDISCLOSED_DIFFERENCE.
- **DISCLOSED_CHANGE**: the paper differs from the registry and mentions the
  change.
- **UNDISCLOSED_DIFFERENCE**: the paper differs from the registry, the quotes
  pass the code check (each quote is found word for word on the stated page),
  and the paper doesn't mention a change.

### Review
Everything except MATCH goes on the project owner's review sheet. Each row
shows the registered text, the paper quote, the page, and a link to the trial's
history of changes on ClinicalTrials.gov
(`https://clinicaltrials.gov/study/<NCT ID>?tab=history`). The owner's final
classification is stored in `outcome_comparisons.final_classification`.
