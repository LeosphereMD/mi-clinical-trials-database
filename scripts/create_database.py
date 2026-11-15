"""Create the empty project database (data/ami_trials.db) as described in SPEC.md.

Usage:
    .venv\\Scripts\\python scripts\\create_database.py          # create if missing
    .venv\\Scripts\\python scripts\\create_database.py --reset  # delete and recreate

Safety: --reset refuses to delete a database that holds any review decisions,
so the project owner's decisions can never be lost by re-running this script.

Note for later scripts: SQLite only enforces the links between tables when
each connection runs "PRAGMA foreign_keys = ON". Use connect() below.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ami_trials.db"

SCHEMA = """
-- 9. Log of each ClinicalTrials.gov download (decision 13)
CREATE TABLE fetch_runs (
    run_id          INTEGER PRIMARY KEY,
    run_date        TEXT NOT NULL,
    query_used      TEXT,
    records_in      INTEGER,
    records_kept    INTEGER,
    records_skipped INTEGER,
    skip_reasons    TEXT
);

-- 1. One row per trial
CREATE TABLE trials (
    nct_id                  TEXT PRIMARY KEY,
    title                   TEXT,
    phase_label             TEXT,
    overall_status          TEXT,
    why_stopped             TEXT,
    start_date              TEXT,
    start_date_type         TEXT,
    completion_date         TEXT,
    completion_date_type    TEXT,
    enrollment              INTEGER,
    enrollment_type         TEXT,
    lead_sponsor            TEXT,
    sponsor_class           TEXT,
    population              TEXT CHECK (population IN
                                ('STEMI', 'NSTEMI', 'MI unspecified', 'ACS mixed')),
    has_device_or_procedure INTEGER CHECK (has_device_or_procedure IN (0, 1)),
    allocation              TEXT,
    masking                 TEXT,
    has_results             INTEGER CHECK (has_results IN (0, 1)),
    last_updated            TEXT,
    publication_status      TEXT CHECK (publication_status IN
                                ('found', 'no publication found', 'not yet searched')),
    raw_json_file           TEXT,
    first_seen_run          INTEGER REFERENCES fetch_runs(run_id),
    last_seen_run           INTEGER REFERENCES fetch_runs(run_id)
);

-- 2. Conditions and MeSH terms per trial
CREATE TABLE conditions (
    condition_id   INTEGER PRIMARY KEY,
    nct_id         TEXT NOT NULL REFERENCES trials(nct_id),
    condition_text TEXT,
    mesh_term      TEXT,
    mesh_id        TEXT,
    match_type     TEXT CHECK (match_type IN ('direct term', 'parent term'))
);

-- 3. Each intervention tested
CREATE TABLE interventions (
    intervention_id   INTEGER PRIMARY KEY,
    nct_id            TEXT NOT NULL REFERENCES trials(nct_id),
    intervention_type TEXT,
    name              TEXT,
    other_names       TEXT,
    description       TEXT
);

-- 4. Each study group
CREATE TABLE arms (
    arm_id      INTEGER PRIMARY KEY,
    nct_id      TEXT NOT NULL REFERENCES trials(nct_id),
    arm_label   TEXT NOT NULL,
    arm_type    TEXT,
    description TEXT,
    UNIQUE (nct_id, arm_label)
);

-- 5. Outcomes as registered
CREATE TABLE registered_outcomes (
    registered_outcome_id INTEGER PRIMARY KEY,
    nct_id                TEXT NOT NULL REFERENCES trials(nct_id),
    outcome_type          TEXT CHECK (outcome_type IN ('primary', 'secondary')),
    measure               TEXT,
    time_frame            TEXT,
    description           TEXT
);

-- 6. One row per paper
CREATE TABLE publications (
    publication_id INTEGER PRIMARY KEY,
    pmid           TEXT UNIQUE,
    doi            TEXT UNIQUE,
    pmc_id         TEXT,
    title          TEXT,
    journal        TEXT,
    year           INTEGER
);

-- 7. Links trials to papers
CREATE TABLE trial_publications (
    nct_id         TEXT NOT NULL REFERENCES trials(nct_id),
    publication_id INTEGER NOT NULL REFERENCES publications(publication_id),
    role           TEXT CHECK (role IN
                       ('main results', 'supplement', 'secondary analysis')),
    found_via      TEXT CHECK (found_via IN
                       ('registry reference', 'PubMed search')),
    pdf_file       TEXT,
    PRIMARY KEY (nct_id, publication_id)
);

-- 8. One row per value an agent pulls from a paper
CREATE TABLE extracted_values (
    value_id          INTEGER PRIMARY KEY,
    nct_id            TEXT NOT NULL REFERENCES trials(nct_id),
    publication_id    INTEGER NOT NULL REFERENCES publications(publication_id),
    arm               TEXT,              -- empty for whole-trial values
    outcome           TEXT NOT NULL,
    field             TEXT NOT NULL,
    -- extractor
    extracted_value   TEXT,
    quote             TEXT,
    page              TEXT,
    not_reported      INTEGER CHECK (not_reported IN (0, 1)),
    -- verifier
    verifier_value    TEXT,
    verifier_quote    TEXT,
    verifier_page     TEXT,
    verifier_verdict  TEXT CHECK (verifier_verdict IN
                          ('agree', 'disagree', 'not found')),
    independent_match INTEGER CHECK (independent_match IN (0, 1)),
    -- code checks
    code_check_result TEXT CHECK (code_check_result IN
                          ('pass', 'fail', 'not run')),
    code_check_note   TEXT,
    -- review selection (the decisions are in review_decisions)
    review_reason     TEXT CHECK (review_reason IN
                          ('flagged', 'random sample', 'not selected',
                           'value changed after decision')),
    -- final
    final_value       TEXT,
    FOREIGN KEY (nct_id, arm) REFERENCES arms(nct_id, arm_label)
);

-- Fixed identity of a value, so re-running an extraction updates the same row
-- (and keeps its value_id) instead of creating a new one.
CREATE UNIQUE INDEX extracted_values_identity ON extracted_values
    (nct_id, publication_id, COALESCE(arm, ''), outcome, field);

-- 10. The project owner's review decisions, one row per decision
CREATE TABLE review_decisions (
    decision_id     INTEGER PRIMARY KEY,
    value_id        INTEGER NOT NULL
                        REFERENCES extracted_values(value_id) ON DELETE RESTRICT,
    decision        TEXT NOT NULL CHECK (decision IN ('approve', 'correct', 'reject')),
    corrected_value TEXT,
    comment         TEXT,
    decided_at      TEXT NOT NULL DEFAULT (datetime('now')),
    value_shown     TEXT,   -- the extracted value printed on the review sheet
    CHECK (decision <> 'correct' OR corrected_value IS NOT NULL)
);
CREATE INDEX review_decisions_value ON review_decisions (value_id);

-- final_value follows the latest decision for that value. If the value the
-- owner saw (value_shown) differs from the current extracted value, the
-- decision is stale: final_value is emptied and the value goes back to review.
CREATE TRIGGER review_decision_sets_final_value
AFTER INSERT ON review_decisions
BEGIN
    UPDATE extracted_values
    SET final_value = (
            SELECT CASE
                       WHEN d.value_shown IS NOT extracted_values.extracted_value THEN NULL
                       WHEN d.decision = 'approve' THEN extracted_values.extracted_value
                       WHEN d.decision = 'correct' THEN d.corrected_value
                       ELSE NULL
                   END
            FROM review_decisions d
            WHERE d.value_id = extracted_values.value_id
            ORDER BY d.decided_at DESC, d.decision_id DESC
            LIMIT 1),
        review_reason = CASE
            WHEN (SELECT d.value_shown IS NOT extracted_values.extracted_value
                  FROM review_decisions d
                  WHERE d.value_id = extracted_values.value_id
                  ORDER BY d.decided_at DESC, d.decision_id DESC
                  LIMIT 1)
            THEN 'value changed after decision'
            ELSE review_reason
        END
    WHERE value_id = NEW.value_id;
END;

-- Same rule when a re-run changes a value that already has decisions.
CREATE TRIGGER changed_value_returns_to_review
AFTER UPDATE OF extracted_value ON extracted_values
WHEN OLD.extracted_value IS NOT NEW.extracted_value
 AND EXISTS (SELECT 1 FROM review_decisions WHERE value_id = NEW.value_id)
BEGIN
    UPDATE extracted_values
    SET final_value = (
            SELECT CASE
                       WHEN d.value_shown IS NOT extracted_values.extracted_value THEN NULL
                       WHEN d.decision = 'approve' THEN extracted_values.extracted_value
                       WHEN d.decision = 'correct' THEN d.corrected_value
                       ELSE NULL
                   END
            FROM review_decisions d
            WHERE d.value_id = extracted_values.value_id
            ORDER BY d.decided_at DESC, d.decision_id DESC
            LIMIT 1),
        review_reason = CASE
            WHEN (SELECT d.value_shown IS NOT extracted_values.extracted_value
                  FROM review_decisions d
                  WHERE d.value_id = extracted_values.value_id
                  ORDER BY d.decided_at DESC, d.decision_id DESC
                  LIMIT 1)
            THEN 'value changed after decision'
            ELSE review_reason
        END
    WHERE value_id = NEW.value_id;
END;

-- Decisions are never deleted or edited; a new decision is added instead.
CREATE TRIGGER review_decisions_no_delete
BEFORE DELETE ON review_decisions
BEGIN
    SELECT RAISE(ABORT, 'Review decisions are never deleted. Add a new decision instead.');
END;

CREATE TRIGGER review_decisions_no_update
BEFORE UPDATE ON review_decisions
BEGIN
    SELECT RAISE(ABORT, 'Review decisions are never edited. Add a new decision instead.');
END;

-- An extracted value with decisions can't be deleted (works even if
-- foreign-key checking is off).
CREATE TRIGGER extracted_values_keep_decided
BEFORE DELETE ON extracted_values
WHEN EXISTS (SELECT 1 FROM review_decisions WHERE value_id = OLD.value_id)
BEGIN
    SELECT RAISE(ABORT, 'This value has review decisions and cannot be deleted. Update it in place instead.');
END;

-- 11. Outcome-switch check (built in Phase 3; table only for now)
CREATE TABLE outcome_comparisons (
    comparison_id         INTEGER PRIMARY KEY,
    nct_id                TEXT NOT NULL REFERENCES trials(nct_id),
    publication_id        INTEGER NOT NULL REFERENCES publications(publication_id),
    registered_outcome_id INTEGER REFERENCES registered_outcomes(registered_outcome_id),
    registered_text       TEXT,
    paper_endpoint_quote  TEXT,
    paper_endpoint_page   TEXT,
    components_comparison TEXT CHECK (components_comparison IN
                              ('same', 'different', 'not reported')),
    time_frame_comparison TEXT CHECK (time_frame_comparison IN
                              ('same', 'different', 'not reported')),
    measure_comparison    TEXT CHECK (measure_comparison IN
                              ('same', 'different', 'not reported')),
    comparison_note       TEXT,
    change_mentions       TEXT,   -- every keyword hit, with quote and page
    change_mentioned      TEXT CHECK (change_mentioned IN ('yes', 'no')),
    quote_check_result    TEXT CHECK (quote_check_result IN ('pass', 'fail', 'not run')),
    agents_agree          TEXT CHECK (agents_agree IN ('yes', 'no')),
    status                TEXT CHECK (status IN ('MATCH', 'POSSIBLE_EXTRACTION_ERROR',
                              'DISCLOSED_CHANGE', 'UNDISCLOSED_DIFFERENCE')),
    history_url           TEXT,
    checked_at            TEXT,
    final_classification  TEXT CHECK (final_classification IN ('MATCH',
                              'POSSIBLE_EXTRACTION_ERROR', 'DISCLOSED_CHANGE',
                              'UNDISCLOSED_DIFFERENCE')),
    owner_comment         TEXT,
    classified_at         TEXT,
    UNIQUE (nct_id, publication_id, registered_outcome_id)
);
"""


def connect(path=DB_PATH):
    """Open the database with the links between tables enforced."""
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def count_decisions(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0]
    except sqlite3.OperationalError:  # older database without this table
        return 0
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true",
                        help="delete the existing database and create it again")
    args = parser.parse_args()

    deleted = False
    if DB_PATH.exists():
        if not args.reset:
            print(f"{DB_PATH} already exists. Use --reset to delete and recreate it.")
            print("Summary: tables in 0, tables created 0, skipped 1 (database already exists)")
            sys.exit(1)
        n = count_decisions(DB_PATH)
        if n:
            print(f"Refusing to delete: the database holds {n} review decision(s).")
            print("Summary: tables in 0, tables created 0, skipped 1 (review decisions present)")
            sys.exit(1)
        DB_PATH.unlink()
        deleted = True

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = connect()
    con.executescript(SCHEMA)
    con.commit()
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    triggers = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'").fetchone()[0]
    con.close()

    print(f"Database: {DB_PATH}")
    print(f"Old database deleted: {'yes' if deleted else 'no (none existed)'}")
    print(f"Tables: {', '.join(tables)}")
    print(f"Safety rules (triggers): {triggers}")
    print(f"Summary: tables defined {SCHEMA.count('CREATE TABLE')}, "
          f"tables created {len(tables)}, skipped 0")


if __name__ == "__main__":
    main()
