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
   sponsor_class, population (STEMI / NSTEMI / MI unspecified / ACS mixed),
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
   - Review: review_reason (flagged / random sample / not selected). The
     decisions themselves live in `review_decisions` (table 10).
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
    comment, decided_at.
    - Changing your mind adds a new row. The latest row (by decided_at) counts
      and sets `extracted_values.final_value`: approve gives the extracted value,
      correct gives corrected_value, and reject leaves it empty.
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

### How the tables connect
```
fetch_runs --(first/last_seen_run)--> trials
trials --1:many--> conditions, interventions, arms, registered_outcomes
trials --many:many via trial_publications--> publications
extracted_values --> trials, publications, arms (optional)
review_decisions --many:1--> extracted_values
outcome_comparisons --> trials, publications, registered_outcomes
```

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
