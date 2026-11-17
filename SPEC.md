# Specification: Phase 3 and Phase 2/3 Drug Trials in MI and ACS

## Goal
Build a SQLite database of Phase 3 and Phase 2/3 drug trials in MI and ACS
patients started on or after 2010-01-01, labelled by timing (acute / recent /
prior MI); see "Reporting wording" (decision 27). The trial data comes from the
ClinicalTrials.gov registry. Then add results from the published papers: AI
agents extract them, a second step verifies them, and the project owner reviews
every value. This is a portfolio project, so it should be reproducible and
transparent.

## Reporting wording
Added on 2026-11-16 (decision 27). The README, CV and any other description
of the dataset use:
"Phase 3 and Phase 2/3 drug trials in MI and ACS patients started on or after
2010-01-01, labelled by timing (acute / recent / prior MI)",
with the current trial count taken from the database at the time of writing,
never hard-coded. The dataset is never called "Phase 3 trials in acute MI"
alone.

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
| 3 | Find the papers and place the PDFs: the 10 largest completed or terminated trials with a main results paper (decision 28) | `papers/` | project owner, by hand |
| 3b | Outcome-checker reads the paper's primary endpoint, before the extractor runs (decision 26; see "Outcome-switch check") | `outcome_checks/` | AI agent |
| 4 | Extract results from the PDFs | `extractions/` | AI agent |
| 5 | Verify each extracted value against the PDF | `verifications/` | second AI agent |
| 6 | Automatic consistency checks (no quotes in the output; see "Code checks") | `checks/` | script |
| 7 | Human review: accept, reject or correct | `review/` | project owner |
| 8 | Load reviewed results into SQLite (`scripts/load_reviewed_results.py`; decision 35) | `data/` | script |
| 9 | Outcome-switch status: registered vs. reported primary outcome, from the outcome-checker's output (step 3b) and the extractor's (Phase 3 of the build; see "Outcome-switch check") | `outcome_checks/` | script, then project owner |

## Progress
1. Current step: Analyses and README (steps 1-8 done for the 10-trial paper target; human review complete, 590 of 590 values, loaded on 2026-11-17); last updated 2026-11-17.
2. Exclusions applied on 2026-11-16 in three rounds plus PREMIER: 196 → 161 → 148 → 141 → 140 trials (Phase 3 122, Phase 2/3 18); see the Quality log.
3. 2a: drug names, sponsors and why_stopped reviewed and loaded. Primary outcome types: loaded with the owner's comments (decision 18); #1367 (NCT03122340, MoCA) changed to patient-reported under rule 2 at the owner's request; estimated error rate of unreviewed drafts 0 of 31 (Quality log); "small surrogate-only trial (<500 patients)" rule approved (decision 19). The owner finished `review/outcome_types.csv` (now 56 rows after the exclusions; a full copy is in `review/archive/outcome_types_reviewed_20261116.csv`). Loaded on 2026-11-16 with the classification rules added to part 4: all 210 primary outcomes typed (56 owner approved, 154 Claude draft, not sampled). 
4. Timing after MI: loaded on 2026-11-16 (decision 23). Of 140 trials: acute 115 (38 owner approved, 77 Claude draft, not reviewed; 8 owner-approved acute labels carry "no window stated"), recent 18, prior 7, none waiting. `review/timing_after_mi.csv` has 63 rows.
5. 2b: `review/registry_check.xlsx` rebuilt on 2026-11-16 with 10 random trials and a timing row (seed 20261116; 116 rows for 46 trials: 10 random trials × 8 fields, 23 text-based and 18 of 117 MeSH population labels). `registry_checks` is still empty. Next: owner checks the sheet against the website, then run `load_registry_check.py`.
6. Drug names (2026-11-16): CANTOS "Standard of care" = usual care, role background; NCT06742567 "Control (Standard treatment)" = usual care, comparator; NCT05077683 "DAPT strategy" = aspirin + P2Y12 inhibitor, background; NCT07604103 "antibiotic treatments" = antibiotic, background; Vaxigrip = influenza vaccine (quadrivalent, inactivated); Ropren = polyprenols; "tissue plasminogen activator" kept (registry never names alteplase). Roles loaded on 2026-11-16 and fixed the same day (Quality log): all 268 DRUG/BIOLOGICAL interventions have a role (study drug 158, comparator 103, background 7); every trial has at least one study drug. Sources: 53 placebo decisions, 6 "role:" comments, 209 rows of `review/intervention_roles.csv`.
7. Not built yet: the paper-results analyses (planned in "Analyses") and step 9 (outcome-switch status).

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
   endpoint was met. (Extended by decision 32: one set of primary-result fields
   per primary comparison.)
   Clarified on 2026-11-16 (owner): the "key secondary outcome" is the one the
   paper calls key / major / principal secondary; if there are several, or the
   paper gives a hierarchical testing order, the FIRST one in that order, with
   the quoted sentence that shows the order. If none of that is stated: "not
   reported". It is never chosen by importance. Also extracted: "total
   randomized" for the whole trial, as stated in the paper (never summed from
   the arms).
   Worded out on 2026-11-17 (decision 34): several outcomes named key with no
   order, or tested at the same level (e.g. Hochberg) → the first listed in
   the paper's text; the verifier checks this rule.
   Added on 2026-11-17 (owner, review round 1; decision 35): a hierarchical
   testing procedure that is mentioned without the order being stated counts
   as no testing order, and the order in which the paper lists its secondary
   outcomes is never assumed to be the testing order (e.g. TAO, which refers
   to its design paper for the order → "not reported").
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
   (Exception for factorial trials: decision 31.)
   Supplements (owner, 2026-11-16): every agent reads the main paper first and
   opens a `*_supp.pdf` only for a value or definition the main paper doesn't
   give, and only the pages needed (from its table of contents); every page
   range read is listed in the agent's `files_read`. Exception: the
   outcome-checker also searches the supplement for the disclosure words.
10. **Verification.** Must every extracted value include a page number and a
    direct quote? Does the second agent work independently and get compared, or
    does it check the first agent's output?
    Choice: Yes, every value needs a page number and a direct quote, or "not
    reported". Hybrid: the verifier first finds the critical values on its own
    (N randomized, effect measure, value, 95% CI, p-value) and these are
    compared automatically. Then it checks every other field in the extractor's
    output. Code checks run after both agents. (Decision 32: the critical
    values are checked for each comparison. Decision 33: verdicts are
    CONFIRMED / WRONG / NOT IN PAPER / UNCLEAR, each with a one-line reason.)
    Step 1 file (owner, 2026-11-16): the verifier writes its own critical
    values to `verifications/<NCT ID>_step1.json` BEFORE it opens the
    extraction, and never rewrites or edits that file; steps 2 and 3 go in
    `verifications/<NCT ID>.json`. A code check compares the step 1 values with
    the extractor's critical values; any difference is flagged (see "Code
    checks"). Page numbers in every agent output are PDF page numbers counted
    from the first page of the file.
11. **Review format.** An Excel sheet (one row per value, with
    accept / reject / correct and comment columns), or something else?
    Choice: An Excel sheet with one row per value: accept / reject / correct,
    corrected value, comment, and a column saying why the row is there (flagged
    or random sample). Include all flagged values plus a random 15% of the values
    that passed, with a fixed seed. (Changed by decision 28: while the paper
    target is 10 trials, the sheet holds 100% of the extracted values.)
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
19. **Small surrogate-only trials.** Which trials count as small
    surrogate-only trials?
    Choice (approved by the project owner on 2026-11-16): a trial is a
    "small surrogate-only trial (<500 patients)" when its
    primary_outcome_type is surrogate only and its registry enrollment is
    under 500. SPEC and the README use this name, not "mechanistic". The
    analysis applies the rule in code (see "Analyses", 3).
20. **"Usual care" convention.** How are standard or optimal medical therapy
    interventions named?
    Choice: generic name "usual care", also when the automatic exact MeSH
    match gave another name (the owner overrides it with a row in
    `review/drug_names.csv`, which the loader applies after the automatic
    matches). First case: NCT01327846 (CANTOS) "Standard of care".
21. **Intervention role.** `interventions.intervention_role` (study drug /
    comparator / background) for DRUG and BIOLOGICAL interventions, so a
    drug-class analysis can leave out background therapy. Filled only from
    the owner: approved placebo = comparator; a "role: ..." comment in
    `review/drug_names.csv`; or the owner's decision on
    `review/intervention_roles.csv`. That sheet has a draft_role from the
    registry arm types (only experimental arms = study drug; only comparator
    arms = comparator; every arm = background; mixed = empty), updated on
    2026-11-16: the owner approves or corrects each row, and nothing goes in
    without a decision. The drug-class analysis is "Analyses", 4.
    Rule change (owner, 2026-11-16): an intervention only in "Active
    comparator" arms, in a trial whose other arms are all placebo, sham or
    no intervention, gets the draft "study drug" (registries often label the
    tested drug's arm "Active comparator").
    Head-to-head trials (owner, 2026-11-16): the older standard drug is the
    comparator; if neither is the standard, both are study drugs.
    Every trial has at least one study drug; a trial whose tested
    intervention is not a drug is excluded by hand (decision 17), e.g.
    NCT02982057 (ABSORB) and NCT01004406 (PREMIER).
22. **Rule 9 flags.** "mechanistic" is removed from the standard comment
    flags; decision 19's code rule replaces it.
23. **Acute window.** How wide is "acute" in `timing_after_mi`?
    Choice (2026-11-16): strict, within 7 days or during the index
    hospitalisation. 8-14 day windows (e.g. DAPA-MI, EMPACT-MI) are recent.
    A label taken from a paper cites the paper in the review comment. See
    "Timing after MI".
24. **Code-check outputs hold no quotes** (2026-11-16). Files in `checks/`
    store only the field name, PASS/FAIL and a short reason; they never copy
    the quote or any paper text. `checks/` is git-ignored (except its
    `.gitkeep`). See "Code checks".
25. **.gitignore matches the never-commit rule** (2026-11-16). Never
    committed: `papers/`, `.venv/`, the full database (`data/ami_trials.db`)
    and every database backup in `data/` (`data/*.backup*.db`),
    `extractions/`, `verifications/`, `outcome_checks/`, `checks/` and
    `review/review_sheet.xlsx` (paper quotes). Committed: `data/raw/` (public
    registry JSON), the empty `.gitkeep` folder markers, and the registry
    review files in `review/` (registry text and the owner's decisions, the
    record of the human review). Checked with `git ls-files` on 2026-11-16:
    no excluded file was tracked apart from the `.gitkeep` markers, and no
    committed file quotes a paper (comments citing a paper are allowed).
26. **The outcome-checker never sees the extractor's output** (2026-11-16).
    Run order for each paper: outcome-checker, then extractor, then verifier.
    The outcome-checker runs only if `extractions/<NCT ID>.json` does not
    exist yet; if it exists, that NCT ID is skipped and reported. Its agent
    instructions (written when it is built) let it read only `papers/` and
    the registry outcome for that trial, never `extractions/` or
    `verifications/`. Reason: the outcome-switch statuses depend on two
    independent readings of the primary endpoint. See "Outcome-switch check".
27. **Reporting wording** (2026-11-16). The dataset is described as "Phase 3
    and Phase 2/3 drug trials in MI and ACS patients started on or after
    2010-01-01, labelled by timing (acute / recent / prior MI)", with the
    current trial count taken from the database, never hard-coded; never as
    "Phase 3 trials in acute MI" alone. SPEC's title and Goal and the first
    line of CLAUDE.md were aligned with it. See "Reporting wording".
28. **Paper target** (2026-11-16). Papers are extracted for the 10 largest
    (by registry enrollment) completed or terminated trials that have a main
    results paper. If fewer than 10 qualify, all that qualify are used, and
    the README says so. Because the target is small, the review sheet holds
    100% of the extracted values, not all flagged values plus a 15% random
    sample of the values that passed (this changes decision 11). The target
    can be raised later; trials whose papers are finished are skipped.
    Count on 2026-11-16 (before the find-papers step): 81 completed or
    terminated trials, 57 with at least one candidate paper (11 from the
    registry's RESULT references, 46 more from a PubMed search by NCT
    number); by timing: acute 42 of 66, recent 10 of 10, prior 5 of 5.
29. **Population rules (a) and (b)** (2026-11-16, after the registry
    hand-check). (a) For trials whose label comes from an "Acute Coronary
    Syndrome" MeSH term, the inclusion criteria are used when they name only
    STEMI, only NSTEMI, or STEMI + NSTEMI without unstable angina. (b)
    "Primary PCI" / "pPCI" in the inclusion criteria counts as STEMI. See
    "Population label", rules 1 and 4.
30. **Population overrides** (2026-11-16). `review/population_overrides.csv`
    (nct_id, label, reason, date) holds labels the owner sets by hand; they
    are applied last, like `review/manual_exclusions.csv`, and the file is
    committed. First rows: NCT01787110 and NCT02290080 (DETO2X-AMI and its
    biomarker study), NCT06723002 and NCT04476173, all ACS mixed; then
    NCT07297589 (EPIC-CT), STEMI + NSTEMI. See
    "Population label", rule 6. Added on 2026-11-17 from the papers (the
    registry text names no MI type): NCT01225562 (PEGASUS), MI unspecified;
    NCT03473223 (AEGIS-II), STEMI + NSTEMI (Quality log).
31. **Factorial trials: one main paper per comparison** (2026-11-16). A
    factorial trial whose comparisons are reported in separate main results
    papers is one trial with two (or more) main papers, each extracted and
    linked to its own registered primary outcome(s). The extra paper is
    saved as `NCT########_<comparison>.pdf`. No schema change is needed:
    `trial_publications` allows two "main results" rows per trial, and
    `extracted_values` and `outcome_comparisons` carry the publication_id.
    First case: NCT03048825 (CLEAR SYNERGY): spironolactone paper (PMID
    39555814, `NCT03048825.pdf`) → registered primary outcomes #650 and #651;
    colchicine paper (PMID 39555823, `NCT03048825_colchicine.pdf`) → #649;
    #648 not assessed (stent performance-goal comparison; no drug paper
    covers it). `scripts/find_papers.py` holds the mapping
    (FACTORIAL_MAIN_PAPERS).
32. **More than one primary comparison per trial** (approved by the project
    owner on 2026-11-16; changes decisions 7 and 10). Pilot cases: PEGASUS
    (ticagrelor 90 mg and 60 mg vs placebo), CANTOS (canakinumab 50, 150 and
    300 mg vs placebo), TAO (two otamixaban doses vs UFH + eptifibatide; the
    registry says one otamixaban arm continued after an interim analysis, by
    DMC decision).
    - **Primary outcome:** for each comparison the paper reports as primary,
      one set of primary-result fields: effect measure, value, 95% CI,
      p-value, and events/N for each arm of the comparison. Each set is
      labelled in `extracted_values.comparison` as "<arm_label> vs
      <arm_label>", using the registry arm labels exactly (e.g. "1 vs 3" for
      PEGASUS, "Canakinumab Dose 150 mg vs Placebo" for CANTOS). Per-arm values
      carry both the arm and the comparison, so an arm shared by several
      comparisons (e.g. placebo) is stored once per comparison.
    - **Several primary endpoints** (owner, 2026-11-17, after batch run 1:
      PEGASUS, TAO, CLEAR SYNERGY): each primary endpoint gets its own outcome
      name as the paper labels it ("primary 1", "primary 2", or the paper's
      own names, e.g. "co-primary 1"), with the full per-comparison field set
      for each (and its own definition, components and analysis population).
      A paper with one primary endpoint keeps outcome "primary". In the
      verifier's step 1 file, each entry carries `outcome` with the same name.
      A primary safety endpoint that is a bleeding outcome is stored as
      "safety: major bleeding" (decision 34), not as a further primary.
    - **New whole-trial fields:** "multiplicity handling" (how the paper
      handled the multiple comparisons, e.g. closed testing, alpha split,
      Bonferroni; with quote and page, or "not reported"); "dropped arm" (one
      row per arm dropped during the trial: arm = its registry label, value =
      when and why, with quote and page). Only the comparisons the paper
      reports are extracted.
    - **Secondary and safety outcomes:** extracted as the paper reports them:
      per comparison where the paper gives per-comparison results; if the
      paper reports only a pooled result, it is extracted with a label that
      joins the pooled arms with " + " (e.g. "1 + 2 vs 3"). Per-comparison
      values are never calculated from pooled data, nor pooled values from
      per-comparison data.
    - **Factorial trials (decision 31):** comparison labels use the factor
      levels as the paper reports them (e.g. "colchicine vs placebo",
      "spironolactone vs placebo"), and the per-arm events/N are the factor
      groups as the paper reports them.
    - **Verifier:** the critical values (N randomized, effect measure, value,
      95% CI, p-value) are found independently for each comparison.
    - **Code checks:** every primary comparison has a complete set of fields;
      every part of a comparison label (each side of " vs ", each arm joined
      by " + ") exists in `arms` for that trial (skipped for the trials listed
      under decision 31); an arm that appears in several comparisons has the
      same N and events for the same outcome in each.
      Label matching order (owner, 2026-11-17): each side of " vs " (and each
      `arm`) is first matched whole against the registry arm labels; only if
      it is not one is it split on " + " and each part matched. A registry
      label that itself contains " + " (e.g. TAO's "UFH + Eptifibatide") is
      therefore read as one arm, not as a pooled group.
    - **Review sheet:** wherever a comparison label appears, the drug name and
      dose of each arm (from the arms and interventions tables) are shown next
      to it, e.g. "1 (ticagrelor 90 mg) vs 3 (placebo)". Display only: the
      stored labels stay the registry labels.
    - **Schema:** new column `extracted_values.comparison`; a value's identity
      is now nct_id + publication_id + arm + comparison + outcome + field.
33. **Verifier verdicts, confidence, timing check, extractor blind to the
    registry outcome** (approved by the project owner on 2026-11-16; changes
    decision 10).
    - **Verifier verdicts:** every extracted field gets CONFIRMED / WRONG /
      NOT IN PAPER / UNCLEAR, with a one-line reason
      (`extracted_values.verifier_reason`, new). The verifier's own value,
      quote and page go in the existing columns `verifier_value`,
      `verifier_quote` and `verifier_page`: a WRONG verdict stores the correct
      value; a CONFIRMED verdict needs the verifier's own quote.
    - **Confidence:** the extractor gives every value a confidence, high /
      medium / low (`extracted_values.confidence`, new).
    - **Timing check:** the verifier checks the paper's population against the
      registry timing label (acute / recent / prior) as well as the population
      label (see "Population check against the paper").
    - **Disclosure words:** "protocol modification" is the 5th word the
      outcome-checker searches for (see "Outcome-switch check").
    - **Extractor blind to the registry outcome:** the extractor never sees the
      registered outcome text, so its reading of the primary endpoint stays
      independent of the outcome-checker's. Linking extracted values to
      registered outcome rows (e.g. CLEAR SYNERGY #649-#651) is done later by
      code, not by the extractor.
    - **Agent input files**, written by `scripts/prepare_agent_inputs.py <NCT
      ID>` from the database, the raw registry JSON and
      `review/paper_list.csv`, all in git-ignored folders:
      - `outcome_checks/inputs/<NCT ID>.json` (outcome-checker): paper files
        and PMIDs, the registered primary outcomes (id, measure, time frame,
        description) and which of them each paper covers (decision 31). Not
        written if `extractions/<NCT ID>.json` exists (decision 26).
      - `extractions/inputs/<NCT ID>.json` (extractor): paper files and PMIDs,
        the registry arm labels with each arm's drug and dose, the factorial
        comparison names (decision 31), and whether the trial was terminated.
        No registered outcome text, no population or timing label.
      - `verifications/inputs/<NCT ID>.json` (verifier): paper files and
        PMIDs, the arms (as above), the registry population label and the
        timing label, each with its source.
34. **Extraction rules after batch run 1** (approved by the project owner on
    2026-11-17, after the 10-trial batch run; see `checks/batch_summary.md`).
    - **Key secondary check:** the verifier checks the decision 7 selection
      rule; a wrong selection (or a wrong "not reported") is WRONG, reason
      "key secondary rule".
    - **Reason for early termination:** extracted whenever the paper reports
      that the trial stopped early, whatever the registry status or the
      agent input says (changes "Reason for early termination from the
      paper"). A disagreement with the registry is recorded in the Quality
      log; the registry status is not changed (it is the snapshot).
    - **Total randomized:** "total randomized" and the per-arm "N randomized"
      are the numbers the paper calls randomized. Numbers after exclusions
      (e.g. patients randomized in error, an excluded site) go in "N
      analysed".
    - **Major bleeding:** "safety: major bleeding" is the bleeding outcome the
      paper names as its primary safety endpoint, with its definition. If the
      paper names none, the outcome it calls major bleeding; if neither, "not
      reported".
    - **Post hoc results** are never the primary result.
    - **Several p-values for one comparison** (e.g. non-inferiority and
      superiority) are each stored, labelled by hypothesis ("p-value
      (non-inferiority)", "p-value (superiority)"), the paper's primary
      hypothesis first. In the verifier's step 1 file they go in `p_values`
      (one entry per hypothesis).
    - **Verifier step 2:** a value that breaks one of these rules is WRONG,
      with the rule as the reason ("total randomized rule", "post hoc rule",
      "major bleeding rule", "p-value rule", "primary endpoints rule").
    - **Human review stays at 100%** (decision 28): every extracted value goes
      on the review sheet.
35. **Human review round 1: import, rule and checker fixes** (approved by the
    project owner on 2026-11-17, after reviewing all 590 extracted values;
    see the Quality log). No agent was re-run.
    - **Extractor rules:** (a) a quote contains the value itself and, in
      running text, starts at the beginning of the sentence (never after a
      line break or an opening bracket); a table value's quote is the row
      from its label to the value. (b) A value contains only what its quote
      says: no inferences or commentary of the agent's own, nothing from
      other sentences (explanations go in `quote_note`). (c) Per-arm "N
      analysed" for an outcome reported in a table is the N in that table's
      column header.
    - **Decision 7:** a hierarchical testing procedure mentioned without the
      order = no testing order; list order is not assumed to be the testing
      order (extractor and verifier).
    - **"continues on page N"** may name a later page than the next one, when
      the text resumes after tables or figures (both agents).
    - **Quote check:** en dash and hyphen count as the same character; a
      missing space after punctuation never matters (all spaces were already
      removed before matching); a quote_note "continues on page N" is
      followed to page N, not only to the next page (see "Code checks").
    - **Loading the review** (`scripts/load_reviewed_results.py`, pipeline
      step 8): sheet "correct" → approve; "wrong" with a corrected value →
      correct; "wrong" without one → reject; "unclear" is not stored and the
      value stays not reviewed; an empty decision = not reviewed. decided_at
      is the time the sheet was last saved. Re-running adds no duplicate
      decisions. An owner-confirmed fix of a sheet entry is applied by the
      script and written in the decision comment (first case: AEGIS-II
      per-arm N randomized, entered swapped on the sheet).
    - **review_reason** gets two new values: flagged (flagged on the sheet the
      owner reviewed) / critical value (decision 10: a primary outcome's
      effect measure, effect value, 95% CI and p-value; total randomized and
      per-arm N randomized) / remaining.
    - **item_no** (new column): when one field has several rows (e.g. one row
      per MACE component, or TAO's two "analysis population" rows), they are
      numbered 1, 2, 3 in the agent's order; a single row is 1. It is part of
      the value identity.
    - **No database link from `extracted_values.arm` to `arms`**: decision 32
      allows pooled labels and decision 31 factorial group names, which the
      link rejected. On the owner's condition, the loader runs the decision 32
      label check on every load and refuses any value that fails (see table
      8).

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
   conditions / eligibility / owner override), n_countries (number of distinct countries in
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
   nct_id, intervention_type, name, other_names, description,
   generic_name, generic_name_source, intervention_role (study drug /
   comparator / background) and intervention_role_source (owner placebo
   decision / owner comment / owner role sheet).
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
     whole-trial values such as a hazard ratio), comparison (decision 32:
     "<arm_label> vs <arm_label>", "a + b vs c" for a pooled result, factor
     levels for factorial trials; empty for values that belong to no
     comparison), outcome, field, item_no (1, 2, 3 ... when one field has
     several rows, e.g. one per MACE component, in the agent's order; else 1;
     decision 35).
   - Arm labels (owner, 2026-11-17, decision 35): there is no database link
     from arm to `arms`, because decision 32 allows pooled labels ("a + b")
     and decision 31 factorial group names. Instead
     `scripts/load_reviewed_results.py` checks every value on every load: its
     arm and each side of its comparison must be a registry arm label, a
     " + " join of registry arm labels, or, for a decision 31 factorial
     trial, a factor group (comparison name) of that paper. A value that
     fails is refused (not loaded) and listed in the script's summary.
   - Extractor: extracted_value, quote, page, not_reported, confidence
     (high / medium / low; decision 33).
   - Verifier: verifier_value, verifier_quote, verifier_page, verifier_verdict
     (CONFIRMED / WRONG / NOT IN PAPER / UNCLEAR; decision 33), verifier_reason
     (one line), independent_match (critical values only).
   - Code checks: code_check_result (pass / fail / not run), code_check_note.
   - Review: review_reason (flagged / critical value / remaining / random
     sample / not selected / value changed after decision; the first three
     since decision 35). The decisions themselves live in
     `review_decisions` (table 10).
   - Final: final_value, filled from the project owner's latest decision in
     `review_decisions`, or automatically only when every check passed and the
     value was not sampled.
   - Each value has a fixed identity: nct_id + publication_id + arm +
     comparison + outcome + field + item_no. Re-running an extraction updates the existing row in place, so its
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
match / owner approved), intervention_role and intervention_role_source
(decision 21).

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
   Unstable" → **ACS mixed** (source: mesh). Only this rule and an owner
   override (rule 6) give this label.
   - **Rule (a)** (decision 29, 2026-11-16): first the inclusion criteria are
     read (the text before the "Exclusion Criteria" heading). If they name
     only STEMI, only NSTEMI, or STEMI + NSTEMI, and never unstable angina
     ("unstable angina", "UA", "NSTE-ACS", "non-ST-elevation ACS", "non-ST or
     ST") or an unrestricted ACS, that label is used instead (source:
     eligibility). ACS restricted on the spot counts as narrower ("ACS
     (STEMI or NSTEMI)", "Diagnosis of ACS: STEMI or NSTEMI", "STE-ACS");
     once the criteria define ACS that way, later mentions ("the qualifying
     ACS event") refer to it. "With or without ST(-segment) elevation" names
     both STEMI and NSTEMI. Primary PCI counts as STEMI (rule b).
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
   - **Rule (b)** (decision 29, 2026-11-16): in the inclusion criteria,
     "primary PCI", "primary percutaneous coronary intervention" and "pPCI"
     count as STEMI. "With or without ST(-segment) elevation" names both.
5. No hit anywhere → **MI unspecified** (source: mesh).
6. **Owner override** (decision 30, 2026-11-16): a trial listed in
   `review/population_overrides.csv` (nct_id, label, reason, date) gets the
   owner's label (source: owner override). It is applied last, after rules
   1-5, by `fetch_trials.py` on every download and by
   `scripts/relabel_population.py` (which recomputes every label from the
   saved raw files without a new download; dry run unless `--apply`). The
   file is committed, like the other review CSVs. It is for cases the rules
   can't read, e.g. ST elevation listed as one of several allowed ECG
   findings, or "primary PCI" in a negated sentence.

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
- Conventions (owner): placebo is "placebo"; standard or optimal medical
  therapy is "usual care" (decision 20); combinations are written "a + b".
  An owner row in drug_names.csv overrides an automatic exact match.
- **Roles** (decision 21): `scripts/draft_roles.py` writes
  `review/intervention_roles.csv` with every DRUG or BIOLOGICAL intervention
  whose role is not already known from the owner's placebo decisions or
  "role: ..." comments. It shows the registry arms, a hint (e.g. "in every
  arm: possibly background") and a draft_role from the hint (only
  experimental arms = study drug; only "Active comparator" arms when every
  other arm is placebo, sham or no intervention = study drug; other
  comparator-only = comparator; every arm = background; mixed or no arms =
  empty). Rows are sorted with the mixed and every-arm rows first. Head-to-
  head trials: the older standard drug is the comparator; if neither is the
  standard, both are study drugs (decision 21). The owner approves (the draft_role) or corrects
  (corrected_role) each row; `load_cleaning.py` loads only rows with a
  decision.
- Automatic names that break the conventions are overridden the same way as
  CANTOS (decision 20): Vaxigrip = influenza vaccine (quadrivalent,
  inactivated); Ropren = polyprenols. "tissue plasminogen activator"
  (NCT03335839) is kept as the registry names it, because the registry
  describes recombinant tPA and never names alteplase.

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
     analysis: "feasibility", "safety-only primary", "split composite",
     "composite incl. PRO component". ("mechanistic" was removed on
     2026-11-16: the code rule "small surrogate-only trial (<500 patients)",
     decision 19, replaces it. No comment had used it.)
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
1. **10 random trials**, with the key fields: phase, overall status, start
   date, enrollment and enrollment type, lead sponsor, primary outcome,
   population, and timing after MI (the label, with its evidence quote and
   source in `where_found`). Changed from 15 trials and 7 fields at the
   owner's request on 2026-11-16, before any decision; same seed, so the 10
   are the first 10 of the earlier 15.
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
- for timing after MI: the evidence quote and the label's source
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
- New extraction field "reason for early termination", extracted whenever the
  paper reports that the trial stopped early, whatever the registry status
  says (decision 34, 2026-11-17; before that: terminated trials only). It is
  extracted like every other value, with an exact quote and page, and stored
  as a whole-trial value in `extracted_values`.
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
- It also checks the paper's population against the registry timing label
  (acute / recent / prior), with an exact quote and page (decision 33; field
  "timing after MI"). Code compares it with `trials.timing_after_mi`; a
  disagreement flags the value in the same way. If the paper states no
  enrolment window but the drug was given at presentation, at PCI or in
  hospital, the label is "acute" with the note "no window stated" (the same
  convention as "Timing after MI"); if the paper states no window and the
  timing is not clear, "unclear", with the quote.
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
- **Run order (decision 26):** for each paper, the outcome-checker runs
  first, then the extractor, then the verifier. It runs only if
  `extractions/<NCT ID>.json` does not exist yet; if it exists, that NCT ID
  is skipped and reported. Its agent instructions (written when it is built)
  let it read only `papers/` and the registry outcome for that trial, never
  `extractions/` or `verifications/`. Reason: the outcome-switch statuses
  depend on two independent readings of the primary endpoint.
- Finds the paper's primary endpoint in the Methods section on its own. It
  never sees `extractions/`. It gives the exact quote and the page.
- Compares the registered and reported primary outcome on three points:
  components (e.g. each MACE component), time frame, and measure. A difference
  in wording alone is not a change.
- Searches the whole paper for "amendment", "originally", "changed",
  "revised" and "protocol modification" (the 5th word added by decision 33),
  and gives the quote and page for every hit.
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

## Code checks
Added on 2026-11-16 (decision 24). Pipeline step 6: scripts check the
extracted values (e.g. arm totals, ranges, each quote found word for word on
its stated page).
- Check files in `checks/` store only the field name, PASS/FAIL and a short
  reason. They never copy the quote or any paper text.
- Quote check (`scripts/check_quotes.py`) matching: typographic variants are
  folded (ligatures, curly quotes, dash types); en dash and the other hyphen
  variants count as a plain hyphen (decision 35); a hyphen between two
  letters is removed (line-break hyphens); all whitespace is removed, so a
  missing space after punctuation never matters. A quote that runs onto
  another page passes only with a quote_note "continues on page N", and is
  followed to page N even when tables or figures lie in between (decision
  35).
- `checks/` is git-ignored (only its `.gitkeep` is committed).
- Comparison checks (decision 32): every primary comparison has a complete
  set of fields; every part of a comparison label exists in `arms` (skipped
  for the factorial trials of decision 31); an arm shared by several
  comparisons has the same N and events for the same outcome in each. Each
  label is first matched whole against the registry arm labels, and only
  then split on " + " (decision 32, 2026-11-17).
- Allowed files (owner, 2026-11-16): each agent output's `files_read` lists
  only that agent's allowed paths (outcome-checker: `papers/<NCT ID>*.pdf`,
  `outcome_checks/inputs/<NCT ID>.json`; extractor: `papers/<NCT ID>*.pdf`,
  `extractions/inputs/<NCT ID>.json`; verifier: `papers/<NCT ID>*.pdf`,
  `verifications/inputs/<NCT ID>.json`, and `extractions/<NCT ID>.json` only
  in `verifications/<NCT ID>.json`, never in the step 1 file). Anything else
  is flagged.
- Verifier step 1 vs extractor (decision 10): for each primary comparison,
  the verifier's independent values in `verifications/<NCT ID>_step1.json`
  (total randomized, effect measure, value, 95% CI, p-value) are compared with
  the extractor's; any difference is flagged.
- The agents: `.claude/agents/outcome-checker.md`, `extractor.md` and
  `verifier.md` (tools Read, Write, Glob; model inherit). The folder limits
  are instructions (the tool list can't enforce folders), so the check above
  is the safeguard.

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
- **The acute window stays strict** (decision 23, 2026-11-16): acute means
  within 7 days or during the index hospitalisation, nothing longer. Trials
  whose window runs to 8-14 days are labelled recent, e.g. DAPA-MI
  (NCT04564742, 7 days, or up to 10 days) and EMPACT-MI (NCT04509674, up to
  14 days after admission). Acute trials whose criteria give no window carry
  the owner's comment "no window stated".
- **Labels taken from a paper:** when the registry is not enough and the
  owner takes the label from a paper, the comment on
  `review/timing_after_mi.csv` cites it (authors, journal, year, volume and
  article or page, or the DOI, and where in the paper). The comment is kept in
  the review file; the database keeps the label, the registry evidence quote
  and the source "owner approved".

## Quality log
Problems found in the data, and what was done about them.

Summary of 2026-11-16: 35 trials excluded in one run (196 → 161; Phase 3
142, Phase 2/3 19): the 23, 9 and 3 trials below. Database backups:
`data/ami_trials.backup-20261116-124113-before-exclusion.db` (before) and
`data/ami_trials.backup-20261116-135337.db` (before the timing columns were
added). The owner's reviewed `review/outcome_types.csv` was copied to
`review/archive/outcome_types_reviewed_20261116.csv` before its excluded rows
were removed.

### 2026-11-17: human review complete (590 of 590 extracted values)
The owner reviewed every extracted value of the 10 trials (11 papers) on
`review/review_sheet.xlsx` (decision 28: 100% review). Loaded with
`scripts/load_reviewed_results.py` (decision 35): 590 values, 590 decisions,
0 skipped, 0 refused by the label check. Database backups:
`data/ami_trials.backup-20261117-141623.db` (before the first layout change)
and `data/ami_trials.backup-20261117-141940.db` (before the final one).
- **Decisions:** 581 correct, 9 wrong (all with a corrected value, stored as
  "correct"), 0 unclear.
- **Flagged values:** 21 of 590 were flagged on the sheet (verifier WRONG /
  UNCLEAR: 13; quote check or step 1 only: 8). 7 of the 21 were wrong.
- **Where the 9 wrong values were caught:** verifier 7, quote check only 0,
  neither 2 (the ELIXA denominators below). So 2 of the 569 unflagged values
  were wrong (0.4%). The 8 quote-check-only flags were all correct values: 1
  real copying slip and 7 checker limits.
- **The 9 wrong values:** AEGIS-II per-arm N randomized ×2; dal-GenE per-arm
  N randomized ×2; ELIXA "discontinued due to adverse events" N analysed ×2;
  TAO and CLEAR SYNERGY (colchicine paper) "multiplicity handling"; EMPACT-MI
  "key secondary selection". The last three were rule violations, not
  factual errors: the selected endpoint or the procedure was right, but the
  value held the agent's own inference or a clause from another sentence.
- **Owner note types** (25 notes): quote incomplete or left out the value 4
  (PEGASUS major bleeding effect measure ×2, quotes starting after a line
  break; LIBREXIA-ACS N analysed ×2, number only in the quote_note); rule
  violation, not a factual error 3; checker limit 3 (TAO en dash; CANTOS
  quote resuming on page 8 ×2), plus 4 EMPACT-MI verifier quotes the owner
  did not check further that the fixed checker now passes (quote resuming on
  page 6); real copying slip 1 (AEGIS-II "key secondary selection", the
  dropped "through", in both agents' quotes); denominator in a table header
  2 (ELIXA); other 8 (per-arm counts after exclusions 4, key secondary rule
  3, an explanatory note on dal-GenE total randomized 1).
- **AEGIS-II and dal-GenE per-arm counts after exclusions:** both papers give
  per-arm randomized counts only after excluding a few patients (AEGIS-II: 7
  of 18,226 from one site, data quality concerns; dal-GenE: 2 of 6149
  randomized in error); the split of the excluded patients is only in a
  supplement figure (AEGIS-II Fig. S1, not in `papers/`) or not given. Both
  agents left per-arm N randomized "not reported"; the verifier marked them
  UNCLEAR. Owner decision: store the paper's per-arm counts, which the paper
  itself calls randomized: AEGIS-II CSL112 9112, placebo 9107; dal-GenE
  dalcetrapib 3071, placebo 3076 (Figure 1). Total randomized stays the
  pre-exclusion number (18,226 and 6149), so the arms do not add up to it.
  The AEGIS-II arms were entered swapped on the sheet (CSL112 9107, placebo
  9112); the paper gives CSL112 9112 and placebo 9107 (abstract, page 4,
  Tables 1-2). Fixed with the owner's OK and written in the decision
  comment.
- **TAO: no key secondary.** No secondary outcome is called key, and the
  paper mentions a hierarchical testing procedure without stating the order
  (it refers to the design paper). Owner: "not reported" under decision 7;
  list order is not assumed to be the testing order (rule added to decision
  7). dal-GenE likewise: no secondary called key, two secondaries tested
  together (Hochberg), no order → "not reported".
- **Missed table-header denominators:** ELIXA "discontinued due to adverse
  events": both agents marked per-arm N analysed "not reported" (the verifier
  CONFIRMED the absence), but Table 3's column headers give it (lixisenatide
  3031, placebo 3032). Not flagged by any check; found only by the owner's
  review. PEGASUS: not marked by the owner. New extractor rule (c), decision
  35.
- **Quote check re-run** on all 10 trials after the checker fixes (decision
  35): 1329 quotes; FAIL 12 → 4, PASS 1180 → 1188, SKIP 137 (not reported).
  All 8 changes were FAIL → PASS: TAO major bleeding definition, extractor
  and verifier (en dash); CANTOS 300 mg p-value and "primary endpoint met",
  extractor (page 5 → 8); EMPACT-MI key secondary effect measure, value and
  95% CI, verifier ×4 (page 4 → 6). No PASS became FAIL. Still failing:
  AEGIS-II key secondary selection, extractor and verifier (the real copying
  slip); dal-GenE per-arm N randomized, verifier ×2 (text inside the Figure 1
  boxes, which pypdf cannot read).
- **Loading problem found and fixed:** the first load put 590 values into 584
  rows, because rows of one field (one per MACE component: PEGASUS 3, CANTOS
  3, EMPACT-MI 2; TAO's 2 analysis population rows) had the same identity,
  and later rows overwrote earlier ones. The database was restored from the
  backup taken just before (the faulty file is kept as
  `data/ami_trials.backup-20261117-failed-load-duplicate-identity.db`), the
  owner approved `item_no` (decision 35), and the reload stored 590 rows.

### 2026-11-17: PEGASUS and AEGIS-II population overrides; verifier label not stable
Both trials had "ACS mixed" from rule 1 (MeSH "Acute Coronary Syndrome");
their registry inclusion criteria name no MI type, so rule (a) could not
apply. Their papers show MI-only populations with no unstable angina. Owner
decision: overrides in `review/population_overrides.csv` (now 7 rows):
NCT01225562 (PEGASUS) MI unspecified ("paper: spontaneous MI 1-3 years
earlier, any type incl. unknown type; no unstable angina"); NCT03473223
(AEGIS-II) STEMI + NSTEMI ("paper: type 1 MI, qualifying STEMI 50.5% /
NSTEMI 49.5%; no unstable angina"). Applied with
`relabel_population.py --apply` (2 labels changed; a second run found
nothing left to change). Database backup:
`data/ami_trials.backup-20261117-094835-before-pegasus-aegis-overrides.db`.
The verifier gave PEGASUS different paper population labels in the two
batch runs, from the same paper: "MI unspecified" in run 1 and "STEMI +
NSTEMI" in run 2 (AEGIS-II got STEMI + NSTEMI both times). The verifier's
population label is therefore a pointer for the owner's review, not a
decision.

### 2026-11-17: AEGIS-II (NCT03473223) repeated quote error caught only by code
In batch run 1 and again in run 2, the same word was dropped from the quote
for "key secondary selection" (paper page 3: "... through 180 days and
through 365 days ..."; the quotes left out the second "through"). Run 1: the
extractor dropped it (in two quotes) and the verifier marked them CONFIRMED.
Run 2: the extractor and the verifier both dropped it, and the verifier
again marked the extractor's quote CONFIRMED. Both times only the quote
check (`scripts/check_quotes.py`, code, not an agent) flagged it. The value
(the selected endpoint) was right; the quote was not word for word. Lesson:
two agents can make the same reading error, so the code quote check is
needed alongside the verifier, and the owner's review (decision 28) covers
every value.

### 2026-11-17: LIBREXIA-ACS (NCT05754957) registry status vs paper
The registry snapshot (downloaded 2026-11-15) lists the trial as COMPLETED,
with no why_stopped, so the agent input said "not terminated". The main paper
(PMID 42670965) reports that the trial was stopped early for futility after
the planned interim analysis. Found in batch run 1, when the extractor left
out "reason for early termination" because the input said not terminated.
Under decision 34 the field is now extracted from the paper. The registry
status is not changed: it is the snapshot.

### 2026-11-16: quote check (`scripts/check_quotes.py`) on EMPACT-MI
The first version of the quote check failed 12 correct quotes because of
text-extraction differences between the PDF reader and the agents' quotes:
spaced long dashes, a space before line-break hyphens ("hos -"), and real
hyphens at line ends ("patient-" / "years"). After the fixes, on NCT04509674:
98 PASS, 1 FAIL (a real page error, "multiplicity handling": the quote runs
from page 3 onto page 4 without a "continues on page" note, also caught by
the verifier as WRONG, "page only"), 12 SKIP (not reported).

### 2026-11-16: registry hand-check results (step 2b)
The owner checked `review/registry_check.xlsx` (116 rows, 46 trials; seed
20261116) against the ClinicalTrials.gov website. Excel saved a copy,
`review/registry_check_reviewed.xlsx`; its decisions are identical to
`registry_check.xlsx` and no other cell changed. All 116 decisions were
loaded into `registry_checks` (113 approve, 3 correct). Database backup
before loading: `data/ami_trials.backup-20261116-200307-before-registry-check-load.db`.

Errors per field (exact binomial 95% CI):
- phase, overall status, start date, enrollment (with type), lead sponsor,
  primary outcome, timing after MI: 0 of 10 each (0-31%); together 0 of 70
  registry values (0-5%).
- population: 3 of 46 (7%, 1-18%). By how the row was picked: random trials
  1 of 10; text-based labels 0 of 23 (0-15%); MeSH sample 3 of 18 (17%,
  4-41%). All 3 errors are MeSH-based labels.

The errors and their causes (the code follows "Population label" exactly;
no bug):
- NCT02044146: ACS mixed, owner: NSTEMI ("NSTEMI undergoing PCI").
- NCT06286878: ACS mixed, owner: STEMI + NSTEMI ("Acute myocardial
  infarction, with or without ST-segment elevation (STEMI/NSTEMI)").
  Cause of both: rule 1. Any "Acute Coronary Syndrome" MeSH term gives ACS
  mixed and the text is never read, so a trial that lists ACS among its
  conditions but enrols a narrower group gets the broader label.
- NCT03404063: MI unspecified, owner: STEMI (inclusion requires cMRI after
  "pPCI", primary PCI). Cause: rule 4's search terms are STEMI / NSTEMI
  words only; "primary PCI" is not one, so rule 5 gave MI unspecified.

Follow-up check (owner request): every MeSH-based label (117 trials: ACS
mixed 54, STEMI 45, MI unspecified 9, STEMI + NSTEMI 7, NSTEMI 2) compared
with the inclusion criteria. Inclusion text names a narrower group:
- Clear (13; * = also found by the hand-check):
  - ACS mixed, inclusion STEMI only: NCT01087723 (STE-ACS), NCT01992523,
    NCT02404376, NCT02976701, NCT06054100, NCT07146360.
  - ACS mixed, inclusion NSTEMI only: NCT02044146*.
  - ACS mixed, inclusion STEMI or NSTEMI (no unstable angina):
    NCT02377388, NCT05998525, NCT06286878*, NCT07102628, NCT07625306.
  - MI unspecified, inclusion primary PCI (implies STEMI): NCT03404063*.
- Possible, for the owner to judge (MI required, no unstable angina, type
  not stated): NCT01225562 (PEGASUS, prior MI 1-3 years ago), NCT03473223
  (AEGIS-II, type I MI), NCT01787110 and NCT02290080 (DETO2X-AMI and its
  biomarker study, suspected MI with ECG changes), NCT00910065 (troponin
  rise plus ECG change; the registry doesn't say whether all criteria are
  required).
- Broader, not narrower: NCT04476173 (MeSH STEMI; inclusion STEMI or
  NSTE-ACS).
- Checked and not narrower: NCT01660373, NCT06723002 (definitions allow
  unstable angina), NCT02924727 (STEMI without reperfusion is only a
  risk-enrichment criterion), NCT01294462, NCT02145468, NCT04739384.
Nothing was changed at first; the fix followed the owner's decision (below).

Fix (2026-11-16, decisions 29 and 30): rules (a)+(b) changed 16 labels; 3 of
those changes (19%) were wrong because ST elevation was one of several
allowed ECG findings (NCT01787110, NCT02290080), or "primary PCI" appeared in
a negated sentence (NCT06723002). All 3 were caught in review and corrected
with overrides (`review/population_overrides.csv`), together with
NCT04476173 (STEMI → ACS mixed: inclusion allows NSTE-ACS). The 13 correct
changes are exactly the 13 "clear" trials listed above. Applied with
`scripts/relabel_population.py --apply` (17 labels changed: 13 by the rules,
4 by overrides); a second run found nothing left to change. Database backup
before the schema upgrade (new population_source "owner override"):
`data/ami_trials.backup-20261116-201704.db`.
Re-run of the MeSH check after the fix: no trial is left with a narrower
inclusion population except the "possible" PEGASUS (NCT01225562) and
AEGIS-II (NCT03473223) and the two already ruled out (NCT01660373,
NCT02924727). New finding, broader the other way (like NCT04476173):
NCT07297589 (EPIC-CT) has MeSH STEMI, but its inclusion says "acute
myocardial infarction with and without ST-segment elevation" (STEMI +
NSTEMI). Owner decision (2026-11-16): override to STEMI + NSTEMI, reason
"inclusion: acute MI with and without ST-segment elevation; MeSH lists STEMI
only" (`review/population_overrides.csv`, now 5 rows; applied with
`relabel_population.py --apply`, 1 label changed). Database backup:
`data/ami_trials.backup-20261116-202153-before-epic-ct-override.db`.

### 2026-11-16: cut-off timing evidence quotes fixed
15 of Claude's timing evidence quotes stopped mid-word or on a dangling word
(e.g. "Hospitalization within 12 ho"); they passed the word-for-word check
because a cut-off piece is still found in the text. Each was extended to the
full sentence or criterion from the registry's inclusion criteria (checked
word for word again): NCT01087723, NCT01327534, NCT01502774, NCT01992523,
NCT02525939, NCT02894138, NCT03048825, NCT03699215, NCT03822377,
NCT03998319, NCT04420624, NCT04564742, NCT04571580, NCT04912167,
NCT06723002. Changed in `review/timing_suggestions_claude.csv` and, for
NCT02525939 and NCT04564742, in the evidence columns of
`review/timing_after_mi.csv`. Labels, sources and the owner's decisions are
unchanged (checked after reloading). NCT05182970 (MIMET) keeps "I. AMI":
that is the registry's whole criterion, with no time window; its label rests
on the paper cited in the owner's comment. Database backup:
`data/ami_trials.backup-20261116-190739-before-quote-fix.db`.

### 2026-11-16: role fixes and PREMIER excluded (141 → 140)
A check for trials with no "study drug" found 26 after the roles were loaded.
Cause: registries often label the tested drug's arm "Active comparator", and
the old draft rule turned that into the draft "comparator", which the owner
approved. Database backup:
`data/ami_trials.backup-20261116-185551-before-role-fixes.db`.
- Drug vs placebo or no intervention (22 trials), listed drug set to study
  drug by the owner: NCT01882179, NCT02377388, NCT02404376, NCT02451293,
  NCT02525939, NCT02551094, NCT02591927, NCT02733185, NCT03048825,
  NCT03287609, NCT03371784, NCT03516903, NCT05424315, NCT05881382,
  NCT07478003, NCT07604103 (antibiotics stay background), NCT07736313
  (rosuvastatin alone = background, because the PCSK9 arm's intervention
  also includes rosuvastatin 20 mg), NCT01787110, NCT04367935, NCT05182970,
  NCT05957887, NCT06847568.
- Head-to-head (new rule in decision 21): NCT01531114 prasugrel and
  ticagrelor both study drug; NCT02298088 and NCT02429271 ticagrelor =
  study drug, clopidogrel = comparator.
- NCT01225562 (PEGASUS): ticagrelor 90 mg set back to study drug (the
  owner's earlier change was a slip; both doses are tested against
  placebo).
- New draft rule (decision 21) applied to every row: 22 drafts change, all in
  the trials above. Outside them, no row's new draft differs from its old
  draft; 13 rows differ from the draft only because the owner had already
  corrected them, so none was put back for review.
- NCT01004406 (PREMIER) excluded by hand: tested intervention is a device
  (intensive LDL-lowering, registered as Device); statin is background in
  both arms. Same as ABSORB. 3 decided rows archived (drug name, role,
  sponsor "VA Office of Research and Development"). After: 140 trials
  (Phase 3 122, Phase 2/3 18).

### 2026-11-16: excluded by hand, round 3 (7 trials, 148 → 141, decision 17)
Flagged by the owner with comments starting "OUT OF SCOPE?" while reviewing
`review/timing_after_mi.csv`; the owner's comment (without that prefix) is the
reason in `review/manual_exclusions.csv`. Decided review rows (13 + 1)
archived in `review/archive/excluded_trial_decisions.csv`. After this round:
141 trials (Phase 3 123, Phase 2/3 18). Database backups:
`data/ami_trials.backup-20261116-171008-before-exclusion-round3.db` (before
the 6) and `data/ami_trials.backup-20261116-171851-before-exclusion-NCT02617290.db`
(before NCT02617290).
- PCI populations with ACS only a subset (same logic as NCT01848106 and
  NCT01465828): NCT01109784 (clopidogrel resistance after PCI), NCT01156571
  (CHAMPION PHOENIX, cangrelor), NCT01360437 (high platelet reactivity; ACS
  or TIMI score >2, so ACS not required), NCT03755700 (contrast kidney injury
  in CKD patients having angiography/PCI; STEMI excluded).
- NCT01812330: elective PCI with clopidogrel resistance in stable patients.
- NCT02982057: device trial (ABSORB BVS vs optimal medical therapy); the
  medical therapy is registered as "Drug" only as the comparator.
- Bug found and fixed in `apply_inclusion_rule.py`: deleting a row from
  `review/registry_check.xlsx` moved the cell text up but left the
  ctgov_link links in place, so the 26 rows below the deleted one linked to
  the next trial. The script now sets every link again from the row's
  nct_id; the sheet was repaired and checked (all links matched, all
  values unchanged). `intervention_roles.csv` was added to the review files
  the script cleans.
- NCT05998525 kept (owner decision, 2026-11-16): CT sub-study of
  NCT04717986 (DAPA-AMI, registry phase N/A, not in database); same
  patients, no double counting. Both registrations share the site (UMAE
  No. 1 Bajío, León), the investigator, dapagliflozin 10 mg vs placebo and
  the 2021-2023 period; enrollment 188 (main trial) and 54 (sub-study).
  NCT04717986 fails the phase rule, so NCT05998525 is the study's only
  registration in the database. Its timing label (acute) comes from the
  sub-study paper, cited in the timing comment: Macías-Cervantes HE et al.
  Curr Probl Cardiol. 2024;49(2):102213. doi:10.1016/j.cpcardiol.2023.102213
  (PMID 38000564; PubMed links it only to NCT05998525). The main trial's
  paper is PMID 42471097 (doi:10.1016/j.cpcardiol.2026.103401).
- NCT02617290, decided by the owner after the scope check: elective PCI,
  troponin-negative; prior ACS only an optional risk feature. MI listed in
  conditions as outcome (type 4a), not population. Same as NCT01848106.
  Excluded in a second run the same day; the repaired link rebuilding was
  checked again on it (all 140 links match).

### 2026-11-16: excluded by hand, round 2 (13 trials, 161 → 148, decision 17)
Found by a check for trials whose inclusion criteria never mention MI or ACS.
Listed in `review/manual_exclusions.csv`; decided review rows archived in
`review/archive/excluded_trial_decisions.csv`. After this run: 148 trials
(Phase 3 130, Phase 2/3 18). Database backup:
`data/ami_trials.backup-20261116-142458-before-exclusion-round2.db`.
- Clearly out of scope:
  - NCT01543555: non-cardiac surgery population; MI is an outcome, not the
    population
  - NCT01877915: heart failure population after a decompensation
  - NCT05473520: pulmonary tuberculosis population
  - NCT05474053: healthy volunteers
  - NCT05476991: ischemic stroke population; MI is an outcome (it also had a
    split composite)
  - NCT07052799: aspirin users having colonoscopy; MI is an outcome
  - NCT07908082: giant cell arteritis population
- Lists ACS among its conditions, but the population is defined by
  PCI/CABG/AF/LV thrombus/CA-AKI, with ACS patients only a subset (same logic
  as NCT01848106): NCT01465828 (PCI, clopidogrel resistance), NCT01755520
  (CABG), NCT02352402 (CABG), NCT03331484 (AF after PCI), NCT06286059
  (contrast kidney injury after complex PCI).
- NCT05825573 (intracardiac thrombus): the same reason, except that it lists
  STEMI, not ACS, among its conditions.
- Reason wording updated on 2026-11-16 at the owner's request; the archive
  file keeps the wording in use when the rows were archived.
- Kept: NCT06081803, a STEMI trial that describes STEMI by ECG criteria.

### 2026-11-16: drug_names.csv rows for NCT02145468 and NCT02596126 fixed
The registry text of two control-arm rows had been typed over with the study
drug's name, so they did not load. The registry text was put back ("Standard
therapy"; "Treatment Prevention for Secondary CV") and both were corrected to
"usual care" (the owner's convention: standard or optimal medical therapy is
"usual care"), comment "role: comparator".

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

Withdrawn and terminated trials (owner, 2026-11-17): withdrawn trials
(`overall_status` = WITHDRAWN; they enrolled no patients) are left out of
the main analyses and listed separately. Terminated trials stay in the main
analyses and are also listed separately. Script: `scripts/registry_analyses.py`;
output: `review/registry_analyses.md` (numbers only, committed).

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

### 3. Small surrogate-only trials (<500 patients) (decision 19)
- Rule: primary_outcome_type = surrogate only and enrollment < 500 (the
  registry figure, actual or estimated). Reported as a count and share of
  all trials and of surrogate-only trials, for all trials and acute-only
  trials. Trials with no enrollment figure are counted separately.
- Distribution used to choose the threshold (2026-11-16, 161 trials):
Enrollment of the 104 surrogate-only trials on 2026-11-16 (enrollment is the
registry figure, actual or estimated): 25% 60, median 102, 75% 300, 90% 487,
max 4017 (DAPA-MI, surrogate only because of a lab-defined component).
Trials below each threshold: < 50: 15 (14%); < 100: 46 (44%); < 150: 62
(60%); < 200: 70 (67%); < 300: 76 (73%); < 500: 94 (90%); < 1000: 99 (95%).
For comparison, clinical-only trials (46): median 2804; only 6 (13%) enrol
fewer than 500.

### 4. Drug classes (placeholder, decision 21)
Added on 2026-11-16; the class mapping is built at the analysis step.
- Counts trials and interventions by drug class.
- Leaves out background therapy (`intervention_role` = background) and
  biologicals that are not drugs (e.g. blood products, cell therapy).
- Herbal and traditional medicine is its own class.
- Interventions with no role yet are counted and reported, not dropped
  silently.
