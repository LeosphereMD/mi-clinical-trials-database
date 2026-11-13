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
