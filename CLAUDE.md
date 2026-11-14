# Project rules

This project builds a SQLite database of Phase 3 drug trials in acute myocardial
infarction (AMI) that started in 2010 or later, using data from the
ClinicalTrials.gov API. Later, AI agents will extract results from the published
papers, and the project owner (a medical sciences graduate, not a programmer)
reviews them. See SPEC.md for details.

## Rules (apply to all work in this project)

1. **Explain first.** Before doing anything, say in plain language what you are
   about to do and why. Avoid jargon, or explain it when you can't avoid it.
2. **Python only.** Use the standard library plus `requests`, `pandas`, `pypdf`
   and `openpyxl`. Don't add other libraries. Run scripts with the project's
   virtual environment: `.venv\Scripts\python`.
3. **Every script prints a summary at the end**: how many records came in, how
   many went out, and how many were skipped (with the reason).
4. **Never guess medical data.** A missing value is stored as empty (NULL / blank
   cell), never invented, estimated or filled in from memory.
5. **Never download papers or log in to any website for the user.** The user
   gets the papers and puts them in `papers/`.
6. **Never commit the `papers/` folder to git.**
7. **If you need to deviate from SPEC.md, tell me and wait for my OK before
   doing it.**

## Folder map

| Folder | What goes in it |
|---|---|
| `data/` | The SQLite database and raw API downloads |
| `papers/` | PDFs the user adds by hand (never committed) |
| `extractions/` | Results the AI agents pull out of the papers |
| `verifications/` | Second-pass checks of each extracted value against the paper |
| `checks/` | Automatic consistency checks (e.g. arm totals, ranges) |
| `outcome_checks/` | Outcome-switch checks: registered vs. reported primary outcome (contains quotes, never committed) |
| `review/` | Files for the user's manual review and their decisions |
| `scripts/` | Python scripts |
| `.claude/agents/` | Definitions for the AI agents |
