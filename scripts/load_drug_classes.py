"""Load the owner-reviewed drug classes into the database (SPEC.md decision 36).

Usage:  .venv\\Scripts\\python scripts\\load_drug_classes.py

Reads review/drug_classes.csv (drug, drug_class, source) and rebuilds the table
drug_classes from it (the CSV is the record of the owner's review). Each class must be
"parent: subclass" (exactly one ": "); a row that is not is skipped and listed.

Then checks the join: every study-drug intervention (interventions.intervention_role =
"study drug") must get a class through interventions.generic_name = drug_classes.drug,
except the biologicals that are not drugs (SPEC "Analyses", 4), listed below. Any other
study drug without a class is listed. Nothing is guessed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_database import connect  # noqa: E402
from review_files import REVIEW_DIR, read_csv  # noqa: E402

CSV = REVIEW_DIR / "drug_classes.csv"

# Study interventions that are not drugs (cell therapy, blood products): left out of the
# drug-class analysis (SPEC "Analyses", 4). Generic names as stored in the database.
NON_DRUG_BIOLOGICALS = {
    "mesenchymal stem cells (allogeneic)",
    "mesenchymal stem cells (umbilical cord)",
    "red blood cell transfusion",
}


def main():
    rows = read_csv(CSV)
    good, skipped = [], []
    seen = set()
    for n, r in enumerate(rows, 2):
        drug, cls = (r.get("drug") or "").strip(), (r.get("drug_class") or "").strip()
        if not drug or not cls:
            skipped.append(f"line {n}: drug or class empty")
            continue
        if cls.count(": ") != 1:
            skipped.append(f"line {n} ({drug}): class not 'parent: subclass'")
            continue
        if drug in seen:
            skipped.append(f"line {n} ({drug}): drug listed twice")
            continue
        seen.add(drug)
        parent, sub = cls.split(": ")
        good.append((drug, cls, parent, sub, (r.get("source") or "").strip() or None))

    con = connect()
    with con:
        con.execute("DELETE FROM drug_classes")
        con.executemany("INSERT INTO drug_classes (drug, drug_class, class_parent, "
                        "class_subclass, source) VALUES (?, ?, ?, ?, ?)", good)
    loaded = con.execute("SELECT COUNT(*) FROM drug_classes").fetchone()[0]
    parents = con.execute("SELECT COUNT(DISTINCT class_parent) FROM drug_classes").fetchone()[0]
    subclasses = con.execute("SELECT COUNT(DISTINCT drug_class) FROM drug_classes").fetchone()[0]

    study = con.execute(
        "SELECT i.nct_id, i.name, i.generic_name, c.drug_class FROM interventions i "
        "LEFT JOIN drug_classes c ON c.drug = i.generic_name "
        "WHERE i.intervention_role = 'study drug' ORDER BY i.nct_id").fetchall()
    non_drug = [s for s in study if s[2] in NON_DRUG_BIOLOGICALS]
    classed = [s for s in study if s[3] is not None]
    missing = [s for s in study if s[3] is None and s[2] not in NON_DRUG_BIOLOGICALS]
    unused = sorted(set(d for d, *_ in good) -
                    {r[0] for r in con.execute("SELECT DISTINCT generic_name FROM interventions "
                                               "WHERE generic_name IS NOT NULL")})
    con.close()

    print("=== Summary ===")
    print(f"CSV rows in:        {len(rows)}")
    print(f"Classes out:        {loaded}  ({parents} parents, {subclasses} distinct "
          "parent: subclass classes)")
    print(f"Skipped:            {len(skipped)}")
    for s in skipped:
        print(f"  {s}")
    print("Join check (study-drug interventions):")
    print(f"  with a class:              {len(classed)}")
    print(f"  non-drug biologicals:      {len(non_drug)} (left out by design)")
    print(f"  WITHOUT a class:           {len(missing)}")
    for s in missing:
        print(f"    {s[0]} | {s[1]} | generic name: {s[2]}")
    print(f"  classes matching no intervention: {len(unused)} {unused if unused else ''}")


if __name__ == "__main__":
    main()
