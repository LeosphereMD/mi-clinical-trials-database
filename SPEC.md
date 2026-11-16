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

## Inclusion criteria (settled; see Decisions 1-5, 15 and 17)
- Condition: MeSH condition terms include "Myocardial Infarction" (or a child
  term) or "Acute Coronary Syndrome"
- MI/ACS named in words (added 2026-11-16, approved by the project owner):
  the conditions list or the title (brief or official) must also name MI or
  ACS in words. The MeSH term alone is not enough, because ClinicalTrials.gov
  also assigns MeSH terms from keywords (e.g. template text left in the
  Keywords field) and from synonyms (e.g. "cardiovascular stroke" is a MeSH
  synonym for Myocardial Infarction).
  - Words: "myocardial infarction", "infarct", "heart attack", "STEMI",
    "NSTEMI", "ST-elevation" / "ST-segment elevation", "acute coronary
    syndrome", "unstable angina", "MI", "ACS". Whole words only (plurals
    allowed); "MI" and "ACS" count only in capitals.
  - The name of a matched MeSH child term (e.g. "cardiogenic shock") does
    not count as backing on its own (decided 2026-11-16, decision 15): the
    conditions or title must name MI or ACS in words.
  - `fetch_trials.py` applies the rule on every download and counts failures
    as skipped ("MI/ACS MeSH term not backed by conditions or title").
    `apply_inclusion_rule.py` removes stored trials that fail it.
- Not on the manual exclusion list (decision 17): `review/manual_exclusions.csv`
  holds trials the project owner excluded by hand, each with its reason and
  date. `fetch_trials.py` reads it on every download, so a refresh can't bring
  them back.
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

## Progress
1. Current step: 2b, Registry hand-check (steps 1 and 2 are done); last updated 2026-11-16.
2. Exclusions applied on 2026-11-16: 196 → 161 trials (Phase 3 142, Phase 2/3 19); see the Quality log. Open: the owner decides on the 13 trials whose inclusion criteria never mention MI or ACS (NCT01465828, NCT01543555, NCT01755520, NCT01877915, NCT02352402, NCT03331484, NCT05473520, NCT05474053, NCT05476991, NCT05825573, NCT06286059, NCT07052799, NCT07908082; NCT06081803 also came up but is a STEMI trial described by ECG criteria).
3. 2a: drug names, sponsors and why_stopped reviewed and loaded. Primary outcome types: loaded with the owner's comments (decision 18); #1367 (NCT03122340, MoCA) changed to patient-reported under rule 2 at the owner's request; estimated error rate of unreviewed drafts 0 of 31 (Quality log); "mechanistic" threshold to be chosen (decision 19). The owner finished `review/outcome_types.csv` (now 56 rows after the exclusions; a full copy is in `review/archive/outcome_types_reviewed_20261116.csv`). Loaded on 2026-11-16 with the classification rules added to part 4: all 210 primary outcomes typed (56 owner approved, 154 Claude draft, not sampled). 
4. Timing after MI: 161 drafts; 78 sure acute loaded; `review/timing_after_mi.csv` (83 rows) waits for the owner, then run `load_timing.py`.
5. 2b: `review/registry_check.xlsx` rebuilt after the exclusions (seed 20261116; 143 rows for 53 trials). `registry_checks` is still empty. Next: owner checks the sheet against the website, then run `load_registry_check.py`.
6. Open question: `review/drug_names.csv` lines 80 (NCT02145468) and 99 (NCT02596126) had their registry columns typed over (originally "Standard therapy" and "Treatment Prevention for Secondary CV"), so they don't load: leave them blank, or another value?
7. Not built yet: the Analyses script (planned in "Analyses"), and steps 3-9.

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

Added by the project owner on 2026-11-16:

15. **MI/ACS must be named in words.** Is the MeSH match enough?
    Choice: No. The conditions list or title must also name MI or ACS in
    words, whole words only, with "MI" and "ACS" in capitals only. A matched
    MeSH child term's name (e.g. "cardiogenic shock") does not count on its
    own. Borderline trials are excluded under the rule, with no manual
    exceptions. See "Inclusion criteria" and the Quality log.
16. **Timing after MI.** Keep trials that enrol patients after the acute
    phase (e.g. prior MI), or exclude them?
    Choice: Keep them, and add `trials.timing_after_mi` (acute / recent /
    prior), based on the latest time after the index event at which the
    inclusion criteria allow enrolment. Every analysis runs for all trials and
    for acute-only trials. See "Timing after MI".
17. **Manual exclusion list.** Trials the rules let through but that are
    clearly not MI or ACS trials (e.g. MI named only as an outcome in the
    conditions list) are excluded by hand, each with its reason, through
    `review/manual_exclusions.csv`, and recorded in the Quality log.
18. **Outcome comments and split composites.** How are the owner's comments
    and split composites counted?
    Choice: `registered_outcomes.outcome_comment` stores the owner's comment
    from `review/outcome_types.csv` (it holds the rule 9 comment flags). Split
    composites are detected in code, not from comments (see "Analyses", 2).
19. **Mechanistic trials (proposed, not applied).** A code rule marks a trial
    "mechanistic" when its primary_outcome_type is surrogate only and its
    enrollment is below a threshold. The owner picks the threshold from the
    distribution in "Analyses", 3. Until then the rule is not applied.

## Database design
Approved by the project owner on 2026-11-14. It extends decision 12 with `arms`
(decision 6) and `fetch_runs` (decision 13).

### Ground rules
- Missing means empty: a value the registry or paper doesn't give is NULL.
- Dates are stored as the registry gives them (sometimes only "2015-03"), with a
  separate column saying actual or estimated.
- The NCT ID ties everything together; every table points back to a trial.
- Quotes live only in the local database; the public CSV export leaves them out.
- Changes to the table layout use `create_database.py --upgrade`. It copies
  every row into the new layout, checks that nothing is lost, and keeps the
  old file as a backup in `data/`.

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
   raw_json_file, timing_after_mi (acute / recent / prior; see "Timing after
   MI"), timing_after_mi_evidence, timing_after_mi_source, first_seen_run,
   last_seen_run.
2. **`conditions`**: conditions and MeSH terms per trial, showing why each trial
   passed the inclusion rule. nct_id, condition_text, mesh_term, mesh_id,
   match_type (direct term or parent term).
3. **`interventions`**: each drug, biological, device or procedure tested.
   nct_id, intervention_type, name, other_names, description.
4. **`arms`**: each study group, so per-arm numbers have something to link to.
   nct_id, arm_label, arm_type, description.
5. **`registered_outcomes`**: outcomes as registered before results. nct_id,
   outcome_type (primary / secondary), measure, time_frame, description,
   outcome_category, outcome_category_source, composite_with_surrogate and
   outcome_comment (primary outcomes only; see "Registry cleaning", part 4).
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
sponsor_name_clean, sponsor_group, why_stopped_category,
why_stopped_secondary_category, why_stopped_source (registry / paper) and
primary_outcome_type. To `registered_outcomes`: outcome_category,
outcome_category_source (Claude draft, not sampled / owner approved) and
composite_with_surrogate (yes / no). To
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

Primary outcome types (part 4) have their own pair of scripts,
`draft_outcome_types.py` and `load_outcome_types.py`, so they can be run
without touching the other review files.

The only values that go in without approval are exact MeSH matches for drug
names, and the sure primary outcome type drafts that were not drawn for the
random check (see part 4).

### Review files (all in `review/`, committed to git: no paper quotes)
- Every row has: decision (approve / correct, or blank = not reviewed yet),
  a corrected value column, and a comment column.
- Every file has a clickable ctgov_link column (an Excel link formula). In
  why_stopped.csv and drug_names.csv it opens the trial's page. In
  sponsors.csv it opens a ClinicalTrials.gov search for all of that
  sponsor's trials. Excel saves the link as plain text, so the draft script
  renews it on every run, even in rows that already have a decision.
- A row that disappears from the database (e.g. because the registry text
  changed) is kept if the owner wrote a decision or comment in it, and
  dropped otherwise.
- Re-running the draft script never changes a row that has a decision. It
  refreshes the drafts in rows without one, and adds rows for new items.
- Files are UTF-8, so Excel shows accents correctly. The loader also accepts
  files Excel saves with semicolons.
- The approved CSV files are the record of the owner's decisions. The loader
  applies them again on every run, so a new download never loses them.
- Exception: a trial excluded by an inclusion rule is removed from the review
  files by `apply_inclusion_rule.py` (settled by the project owner on
  2026-11-16). Every decided row it removes is first copied to
  `review/archive/excluded_trial_decisions.csv` with the date and reason. In
  sponsors.csv only sponsors left with no trials are removed.

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
- Approved category list (updated 2026-11-15 from the owner's review):
  safety / early benefit / lack of efficacy or futility / DSMB
  recommendation, reason not stated / healthcare system change / new outside
  evidence / COVID-19 / slow enrollment / funding or commercial reasons /
  regulatory / other sponsor decision / unclear / not stated.
- Each trial has one main category, plus an optional secondary_category from
  the same list (not the same as the main one).
- reason_source: registry (default) or paper.

Category rules (settled by the project owner on 2026-11-15):
- **not stated**: the registry gives no reason at all.
- **unclear**: a reason is given, but it fits no category.
- **early benefit**: a DSMB stopped the trial because the drug clearly worked.
- **Pandemic**: if the reason mentions the pandemic, the main category is
  COVID-19, with slow enrollment as the secondary category when the reason
  also mentions enrollment or recruitment.
- **Reason from a paper**: if the reason came from a paper, reason_source is
  "paper", and the comment holds the DOI and the page. The loader refuses
  such a row unless the comment contains a DOI (10.xxxx/...) and a page
  (e.g. "p. 5").
- **Status definitions are not reasons**: some sponsors type
  ClinicalTrials.gov's own definition of the status into "Why Stopped"
  instead of a reason (e.g. "Enrolling participants has halted prematurely
  and will not resume" for Terminated). `fetch_trials.py` stores such a text
  as empty (the original stays in the raw file), so the trial counts as
  "not stated". In the 2026-11-15 download this affected one trial,
  NCT02075125.

How the draft is made:
- The draft uses keywords, checked in this order, and the first match wins:
  1. safety
  2. early benefit ("early benefit", "clear benefit", "overwhelming efficacy",
     "stopped for benefit")
  3. lack of efficacy or futility
  4. DSMB recommendation, reason not stated ("DSMB", "interim analysis")
  5. healthcare system change ("healthcare system", "health system")
  6. new outside evidence
  7. COVID-19
  8. slow enrollment
  9. funding or commercial reasons
  10. regulatory
  11. other sponsor decision
  12. otherwise unclear

  Futility and safety come before DSMB, so "futility at the interim
  analysis" stays futility.
- Funding or commercial keywords include "market" (e.g. "market landscape").
- When the text only says "see detailed description", the detailed
  description is shown in the file and searched too.
- Approved values go into `trials.why_stopped_category`,
  `why_stopped_secondary_category` and `why_stopped_source`.

### 4. Primary outcome types
Added on 2026-11-15 at the project owner's request.
- **Each registered primary outcome** gets one type in
  `registered_outcomes.outcome_category`: clinical event / surrogate or lab
  measure / patient-reported / other.
  - clinical event: e.g. death, MI, stroke, heart failure hospitalization,
    revascularization, bleeding events, MACE.
  - surrogate or lab measure: lab values, imaging and other measurements,
    e.g. infarct size, LVEF, TIMI flow, platelet reactivity, LDL-C, troponin.
  - patient-reported: questionnaires or scales the patient fills in, e.g.
    pain or depression scores.
  - other: anything else, e.g. adherence, feasibility, length of stay.
  - **Composites** (settled by the project owner on 2026-11-15): a composite
    counts as a clinical event only if every component is a clinical event.
    Any imaging, ECG or lab component makes it a surrogate or lab measure.
  - **`composite_with_surrogate`** (yes / no, per outcome): yes when the
    outcome is a composite that combines clinical events with at least one
    imaging, ECG or lab component, so these can be reported separately. A
    composite made only of imaging or lab measures is "no" (it was never
    clinical). Claude marks every "yes" draft uncertain, so all of them are
    reviewed.
- **Classification rules** (added by the project owner on 2026-11-16; they
  refine the definitions above):
  1. Classify by what is measured, not by the instrument. Adherence is
     "other" even when measured by a questionnaire (e.g. Morisky-Green,
     MMAS-8). "Patient-reported" is for symptoms, function and quality of
     life.
  2. Clinician-administered or performance-based scales that measure
     symptoms, cognition or function (e.g. MoCA, NYHA class) count as
     "patient-reported".
  3. A test that only confirms an event (e.g. "unstable angina with objective
     evidence of ischemia", ECG-confirmed new AF) does not make the outcome
     surrogate: the test is the proof, not the outcome. But a component that
     is defined by a test value itself (e.g. "MI with hs-cTnT >=30x ULN" =
     infarct size by troponin) is surrogate.
  4. composite_with_surrogate applies only to a single combined endpoint
     ("any of the following", hierarchical or ordinal ranked endpoints). A
     list of separately analysed measurements is not a composite.
  5. Classify the current registered primary outcome (as fetched). If the
     registry history shows the primary was changed, note the original in the
     comment.
  6. If a single composite is registered as several separate primary rows
     (one per component), classify each row by its own measure and add the
     comment "split composite". The analysis reports how many trials have
     split composites, and whether any include a surrogate component.
  7. A composite of clinical events plus a patient-reported component (no
     lab, imaging or ECG component) is "clinical event" with
     composite_with_surrogate = no, comment "composite incl. PRO component".
  8. Organ-support or treatment-defined outcomes (vasopressor-free days, ECMO
     weaning, revascularization) are clinical events.
  9. Standard comment flags, used verbatim so they can be counted in the
     analysis: "mechanistic", "feasibility", "safety-only primary",
     "split composite", "composite incl. PRO component".
- **Each trial's `primary_outcome_type`** follows by rule from its primary
  outcomes, never by hand (updated by the project owner on 2026-11-15):
  - clinical only: every primary outcome is a clinical event
  - surrogate only: every primary outcome is a surrogate or lab measure
  - patient-reported only: every primary outcome is patient-reported
  - mixed: more than one type among the primary outcomes
  - other: every primary outcome is "other" (only when nothing else fits)
  It stays empty if any of the trial's primary outcomes has no type yet, or
  if the trial registers no primary outcome.
- **Drafts:** Claude drafts the type of every primary outcome, marked sure or
  uncertain with a note, in `review/outcome_type_suggestions_claude.csv`.
  Drafts are keyed by registered_outcome_id. A reworded outcome gets a new id,
  so it has no draft and goes on the sheet.
- **Review** (same approach as the paper review, decision 11):
  `review/outcome_types.csv` holds every uncertain draft, every outcome
  without a draft, and a random 15% (rounded up) of the sure drafts, drawn
  with a fixed seed (20261115). Each sure draft gets a fixed random number
  from the seed and its id, and the lowest 15% are drawn, so a change to a
  few drafts leaves the rest of the sample as it was. review_reason says why
  each row is there (uncertain draft / no draft yet / random check of a sure
  draft).
- **Sheet layout:** uncertain rows first, then outcomes without a draft, then
  the random checks, each sorted by trial. Columns from left to right: why
  the row is there, trial link, outcome, the draft (type, composite flag,
  note), the owner's columns (decision, corrected_category,
  corrected_composite_with_surrogate, comment), then the long registry text
  (time frame, description, flattened to one line) and the ids.
- The owner approves, or corrects the type, the flag or both. With
  "correct", a blank corrected column keeps the draft value.
- **Loading:** outcomes on the sheet get the owner's value (source "owner
  approved") and the owner's comment (`outcome_comment`, decision 18), or stay
  empty until reviewed. The loader reads the short form "surrogate" as
  "surrogate or lab measure" (the only type it can mean) and prints each use. Sure drafts not drawn go in
  automatically (source "Claude draft, not sampled").

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

## Reason for early termination from the paper (Phase 3)
Added on 2026-11-15. It is built in Phase 3, together with the extractor and
verifier.
- New extraction field "reason for early termination", for terminated trials
  only. It is extracted like every other value, with an exact quote and page,
  and stored as a whole-trial value in `extracted_values`.
- Code compares it with the trial's approved why_stopped category. A
  disagreement flags the value, so it goes on the project owner's review
  sheet with:
  - the registry text and category
  - the paper quote and page

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

## Timing after MI
Added on 2026-11-16 (decision 16). This is part of registry cleaning (step 2a).

- **`trials.timing_after_mi`**: how long after the index MI or ACS patients
  could be enrolled, judged from the latest time the inclusion criteria allow:
  - acute: during the index hospitalisation or within 7 days
  - recent: the latest allowed is 8 days to 6 months
  - prior: more than 6 months, "history of MI", or only a minimum (e.g.
    ">=30 days") with no maximum
  It stays empty while a trial waits for review, and when the inclusion
  criteria name no index MI or ACS.
- **`timing_after_mi_evidence`** holds the text from the inclusion criteria
  that decided the label. **`timing_after_mi_source`**: Claude draft, not
  reviewed / owner approved.
- **Drafts:** Claude drafts every trial in
  `review/timing_suggestions_claude.csv` (label, sure or uncertain, the
  evidence quote, a note). `draft_timing.py` checks that each quote appears
  word for word in the trial's inclusion criteria (the text before the
  "Exclusion Criteria" heading, or the whole eligibility text if there is no
  heading).
- **Review:** `review/timing_after_mi.csv` holds every draft that is not
  acute, every uncertain draft, every trial with no index MI found, and every
  trial whose quote is not found or that has no draft. The owner approves, or
  corrects with acute / recent / prior / none.
- **Loading:** `load_timing.py` stores the owner's value (source "owner
  approved"). Sure acute drafts with a found quote go in without review
  (source "Claude draft, not reviewed"). Rows still waiting stay empty.

## Quality log
Problems found in the data, and what was done about them.

Summary of 2026-11-16: 35 trials excluded in one run (196 → 161; Phase 3
142, Phase 2/3 19): the 23, 9 and 3 trials below. Database backups:
`data/ami_trials.backup-20261116-124113-before-exclusion.db` (before) and
`data/ami_trials.backup-20261116-135337.db` (before the timing columns were
added). The owner's reviewed `review/outcome_types.csv` was copied to
`review/archive/outcome_types_reviewed_20261116.csv` before its excluded rows
were removed.

### 2026-11-16: estimated error rate of the unreviewed outcome type drafts
Of Claude's sure primary outcome type drafts, a random 15% were drawn for the
owner's check (seed 20261115). On the sheet after the exclusions, the owner
approved all 31 random-check rows and corrected none: 0 of 31 = 0% corrected
(95% confidence interval 0% to 11%, Wilson method). Before the exclusions it
was 0 of 34. This is the estimated error rate for the 154 sure drafts that
went in without review (source "Claude draft, not sampled").

### 2026-11-16: false MI/ACS matches excluded (23 trials)
Found by the project owner: NCT01090310 (AIN457 in non-infectious uveitis)
had the MeSH term Myocardial Infarction only because Novartis left template
text in its Keywords field ("Examples: Heart failure, aliskiren, heart
attack, ..."), which ClinicalTrials.gov mapped to Myocardial Infarction. A
scan of all raw files found 23 trials whose MI/ACS MeSH term is not backed by
their conditions list or title. All were excluded under the new rule ("MI/ACS
named in words", see "Inclusion criteria"), with their related rows. Decided
review rows were archived in `review/archive/excluded_trial_decisions.csv`.
Database backup: `data/ami_trials.backup-20261116-124113-before-exclusion.db`.

Reason for all: MI/ACS MeSH term not backed by conditions or title.
- NCT01090310: uveitis; MeSH from Novartis template text in keywords
- NCT04806893, NCT05046106: MeSH from the condition "Cardiovascular Stroke" /
  "Stroke, Cardiovascular", a MeSH synonym for MI (lipid and stroke trials)
- NCT01848106: PCI population, may include some ACS patients; excluded
  because title and conditions don't name ACS
- NCT01007279, NCT01228227: stable angina patients having elective PCI;
  periprocedural MI is the outcome, not the population
- NCT05739929: PCI population; the inclusion criteria exclude ACS patients
- MI only as an outcome or keyword (cardiovascular prevention or other
  diseases): NCT01101035, NCT01492361, NCT01594333, NCT01776424, NCT01975376,
  NCT01975389, NCT02117453, NCT02344290, NCT04023552, NCT04057261,
  NCT04343001, NCT04774159, NCT05485961, NCT05739383, NCT07136012,
  NCT07517263

### 2026-11-16: cardiogenic shock without MI excluded (9 trials, decision 15)
MeSH files "Shock, Cardiogenic" under Myocardial Infarction, so these
trials matched through that child term alone. None names MI or ACS in its
conditions or title, and none requires MI as the cause of shock in its
inclusion criteria. Reason: MI/ACS MeSH term not backed by conditions or
title. NCT03340779, NCT03989531, NCT04020263, NCT04728932, NCT04990349,
NCT05594342, NCT05879276, NCT07099014, NCT07583446. NCT07714746 (cardiogenic
shock after STEMI) stays.

### 2026-11-16: excluded by hand (3 trials, decision 17)
These name MI in their title or conditions, so the rule lets them through,
but MI is not their population. Listed in `review/manual_exclusions.csv`.
- NCT04069234: diabetes patients without prior MI having elective PCI; the
  title names MI only to say patients have none
- NCT07174414: recurrent stroke trial; Myocardial Infarction is in the
  conditions list as an outcome, not the population
- NCT03649711: chronic kidney disease platelet study; Heart Attack is in the
  conditions list as an outcome, not the population

## Analyses
Added on 2026-11-15. Planned analyses of the finished database.
Section 1 is from 2026-11-15; sections 2 and 3 were added on 2026-11-16.

Every analysis runs for all trials and for acute-only trials
(`timing_after_mi` = acute), decision 16. Trials with an empty
timing_after_mi are counted and reported, not dropped silently.

### 1. Share of trials by primary outcome type
- Number and percentage of trials in each `trials.primary_outcome_type`
  (clinical only / surrogate only / patient-reported only / mixed / other).
- Also the number of trials with at least one primary outcome flagged
  `composite_with_surrogate`, reported separately.
- Shown for all trials together, and separately for Phase 3 and Phase 2/3
  (`phase_label`).
- Trials with an empty primary_outcome_type are counted and reported
  separately, not dropped silently.

### 2. Split composites (decision 18)
- Detected in code. A single-event row is a primary outcome typed clinical
  event, with composite_with_surrogate = no, whose measure text has no
  composite wording ("composite", "MACE", "MACCE", "combined", "hierarchical",
  "win ratio", "net clinical", "any of", "or", "and", commas, semicolons,
  "/", "+", "endpoint"). A trial with 2 or more single-event rows has a split
  composite.
- Reported: the number of trials with split composites, and how many of them
  also have a surrogate primary row (e.g. an LVEF row next to death,
  transplant and rehospitalisation rows).
- Known limit: a component whose own wording contains "or" (e.g. "urgent
  coronary or carotid revascularization") is not counted as a single event;
  the trial is still found if 2 other rows qualify. The analysis lists the
  trials found so the owner can check them.
- Preview on 2026-11-16 (161 trials): one trial, NCT05476991 (4 of its 5
  component rows qualify; no surrogate row).

### 3. Mechanistic trials (decision 19, threshold not chosen yet)
Enrollment of the 104 surrogate-only trials on 2026-11-16 (enrollment is the
registry figure, actual or estimated): 25% 60, median 102, 75% 300, 90% 487,
max 4017 (DAPA-MI, surrogate only because of a lab-defined component).
Trials below each threshold: < 50: 15 (14%); < 100: 46 (44%); < 150: 62
(60%); < 200: 70 (67%); < 300: 76 (73%); < 500: 94 (90%); < 1000: 99 (95%).
For comparison, clinical-only trials (46): median 2804; only 6 (13%) enrol
fewer than 500.
