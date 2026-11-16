"""Recompute every trial's population label from its saved raw file (SPEC.md "Population label").

Usage:
    .venv\\Scripts\\python scripts\\relabel_population.py          # show what would change
    .venv\\Scripts\\python scripts\\relabel_population.py --apply  # save the changes

Uses the same rules as fetch_trials.py (population_label: rules 1-5, then the
owner's overrides in review/population_overrides.csv), so a rule change can be
applied without a new download. Only trials.population and
trials.population_source are changed, in one transaction. Back up the
database before using --apply.
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from create_database import DB_PATH, connect
from fetch_trials import population_label

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="save the changes")
    args = parser.parse_args()
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    con = connect()
    changes, skipped = [], Counter()
    try:
        trials = con.execute("SELECT nct_id, population, population_source, raw_json_file "
                             "FROM trials ORDER BY nct_id").fetchall()
        for nct_id, old, old_source, raw_file in trials:
            path = ROOT / raw_file if raw_file else None
            if not path or not path.exists():
                skipped["raw file missing"] += 1
                continue
            new, new_source = population_label(json.loads(path.read_text(encoding="utf-8")))
            if (new, new_source) != (old, old_source):
                changes.append((nct_id, old, old_source, new, new_source))
        for nct_id, old, old_source, new, new_source in changes:
            print(f"  {nct_id}: {old} ({old_source}) -> {new} ({new_source})")
        if args.apply and changes:
            with con:
                con.executemany("UPDATE trials SET population = ?, population_source = ? "
                                "WHERE nct_id = ?",
                                [(new, src, nct_id) for nct_id, _, _, new, src in changes])
        counts = con.execute("SELECT population, population_source, COUNT(*) FROM trials "
                             "GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
    except sqlite3.Error as e:
        print(f"STOPPED: {e}. Nothing was changed.")
        sys.exit(1)
    finally:
        con.close()
    print(("Saved" if args.apply else "Would change (dry run; nothing saved)")
          + f": {len(changes)} labels")
    print("Labels in the database" + (" now:" if args.apply else " (unchanged):"))
    for label, source, n in counts:
        print(f"  {label} (from {source}): {n}")
    print(f"Summary: records in {len(trials)} trials, out {len(changes)} "
          f"{'changed' if args.apply else 'to change'}, skipped {sum(skipped.values())}"
          + (f" ({', '.join(f'{k}: {v}' for k, v in skipped.items())})" if skipped else ""))


if __name__ == "__main__":
    main()
