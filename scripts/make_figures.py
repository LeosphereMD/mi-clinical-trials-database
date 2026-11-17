"""Charts for the README, saved as PNG in figures/ (SPEC "Analyses"; matplotlib, decision 37).

Usage:  .venv\\Scripts\\python scripts\\make_figures.py

  figures/outcome_type_by_phase.png   primary outcome type by phase (100% bars, n per bar)
  figures/quality_checks.png          where problems were caught: (1) scope, registry
                                      download to database; (2) paper values, agent and
                                      code flags to the owner's corrections

Data: data/ami_trials.db (read only), review/manual_exclusions.csv, and two rule-based
exclusion counts from the SPEC.md Quality log (they are not stored in the database):
"false MI/ACS matches excluded (23 trials)" and "cardiogenic shock without MI excluded
(9 trials, decision 15)". The script stops if the scope steps do not add up to the
number of trials in the database. Withdrawn trials (no patients enrolled) are left out of
chart 1, as in review/registry_analyses.md.
"""
import csv
import sqlite3
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "ami_trials.db"
OUT = ROOT / "figures"

# Rule-based exclusions, from the SPEC.md Quality log (2026-11-16 entries).
FALSE_MESH = 23     # "false MI/ACS matches excluded (23 trials)"
SHOCK = 9           # "cardiogenic shock without MI excluded (9 trials, decision 15)"

TYPES = ["clinical only", "surrogate only", "patient-reported only", "mixed", "other"]
COLORS = {"clinical only": "#2F6DB5", "surrogate only": "#E08A2E",
          "patient-reported only": "#3A9E6F", "mixed": "#8E6BBF", "other": "#9AA0A6",
          "empty": "#D0D0D0"}
INK, MUTED = "#222222", "#5F6368"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#BBBBBB",
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": INK,
                     "axes.spines.top": False, "axes.spines.right": False})


def outcome_type_by_phase(con, snap):
    rows = con.execute("select phase_label, primary_outcome_type from trials "
                       "where overall_status <> 'WITHDRAWN'").fetchall()
    groups = [("Phase 3", [r for r in rows if r[0] == "PHASE3"]),
              ("Phase 2/3", [r for r in rows if r[0] == "PHASE2/PHASE3"]),
              ("All", rows)]
    keys = TYPES + ["empty"]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for i, (name, g) in enumerate(groups):
        n, left = len(g), 0.0
        for k in keys:
            c = sum((r[1] or "empty") == k for r in g)
            if not c:
                continue
            w = 100 * c / n
            ax.barh(i, w, left=left, color=COLORS[k], edgecolor="white", height=0.62,
                    label=k if i == 0 or k not in [t for t, _ in []] else None)
            if w >= 9:
                ax.text(left + w / 2, i, f"{c} ({w:.0f}%)", ha="center", va="center",
                        color="white", fontsize=10, fontweight="bold")
            elif w >= 2.5:
                ax.text(left + w / 2, i, str(c), ha="center", va="center", color="white",
                        fontsize=9)
            left += w
    ax.set_yticks(range(len(groups)), [f"{nm}\n(n = {len(g)})" for nm, g in groups])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks(range(0, 101, 25), [f"{x}%" for x in range(0, 101, 25)])
    ax.xaxis.grid(True, color="#E5E5E5"); ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[k]) for k in TYPES
               if any((r[1] or "empty") == k for r in rows)]
    labels = [k for k in TYPES if any((r[1] or "empty") == k for r in rows)]
    ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=5,
              frameon=False, fontsize=10)
    ax.set_title("Primary outcome type by phase", loc="left", fontsize=14, fontweight="bold",
                 color=INK, pad=22)
    ax.text(0, 1.04, f"MI/ACS drug trials, registry snapshot {snap}; withdrawn trials left out",
            transform=ax.transAxes, color=MUTED, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "outcome_type_by_phase.png", dpi=150)
    plt.close(fig)
    return {nm: len(g) for nm, g in groups}


def quality_checks(con):
    fetched = con.execute("select records_in from fetch_runs order by run_id desc limit 1"
                          ).fetchone()[0]
    in_db = con.execute("select count(*) from trials").fetchone()[0]
    with open(ROOT / "review" / "manual_exclusions.csv", encoding="utf-8-sig") as f:
        by_hand = sum(1 for _ in csv.DictReader(f))
    if fetched - FALSE_MESH - SHOCK - by_hand != in_db:
        sys.exit(f"STOP: scope steps do not add up ({fetched} - {FALSE_MESH} - {SHOCK} - "
                 f"{by_hand} != {in_db}); nothing drawn.")

    q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
    latest = ("(select decision from review_decisions d where d.value_id = e.value_id "
              "order by decided_at desc, decision_id desc limit 1)")
    n_values = q("select count(*) from extracted_values")
    reviewed = q(f"select count(*) from extracted_values e where {latest} is not null")
    flag_verifier = q("select count(*) from extracted_values where review_reason = 'flagged' "
                      "and verifier_verdict in ('WRONG', 'UNCLEAR', 'NOT IN PAPER')")
    flag_code = q("select count(*) from extracted_values where review_reason = 'flagged'") \
        - flag_verifier
    slip = q("select count(*) from extracted_values where code_check_result = 'fail'")
    corrected = q(f"select count(*) from extracted_values e where {latest} = 'correct'")
    corr_flagged = q(f"select count(*) from extracted_values e where {latest} = 'correct' "
                     "and review_reason = 'flagged'")
    corr_human = corrected - corr_flagged

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [1, 1.15]})
    # (1) scope: waterfall
    steps = [("Fetched from registry", fetched, 0, "#2F6DB5"),
             ("False MI/ACS MeSH matches", -FALSE_MESH, fetched - FALSE_MESH, "#C0504D"),
             ("Cardiogenic shock without MI", -SHOCK, fetched - FALSE_MESH - SHOCK, "#C0504D"),
             ("Excluded by hand (reasons listed)", -by_hand, in_db, "#C0504D"),
             ("In the database", in_db, 0, "#2F6DB5")]
    for i, (lab, v, base, col) in enumerate(steps):
        a1.barh(i, abs(v), left=base, color=col, height=0.6)
        a1.text(base + abs(v) + 3, i, f"{v:+d}" if v < 0 else str(v), va="center", fontsize=10,
                color=INK)
    a1.set_yticks(range(len(steps)), [s[0] for s in steps]); a1.invert_yaxis()
    a1.set_xlim(0, fetched * 1.15); a1.set_xlabel("Trials")
    a1.set_title(f"1. Scope (trials): {fetched} fetched, {in_db} kept", loc="left", fontsize=12,
                 fontweight="bold", color=INK)
    # (2) paper values
    bars = [(f"Flagged by verifier (wrong / unclear)", flag_verifier, "#9AA0A6"),
            (f"Flagged by code checks only", flag_code, "#9AA0A6"),
            ("Quote slip caught only by code\n(both agents; value right)", slip, "#8E6BBF"),
            ("Corrected after a verifier flag", corr_flagged, "#E08A2E"),
            ("Found only by human review", corr_human, "#E08A2E"),
            ("Corrected in total", corrected, "#C0504D")]
    for i, (lab, v, col) in enumerate(bars):
        a2.barh(i, v, color=col, height=0.6)
        a2.text(v + 0.2, i, str(v), va="center", fontsize=10, color=INK)
    a2.set_yticks(range(len(bars)), [b[0] for b in bars]); a2.invert_yaxis()
    a2.set_xlim(0, max(b[1] for b in bars) * 1.2); a2.set_xlabel("Extracted values")
    a2.set_title(f"2. Paper values: n = {n_values}, {reviewed} reviewed", loc="left",
                 fontsize=12, fontweight="bold", color=INK)
    for ax in (a1, a2):
        ax.xaxis.grid(True, color="#E5E5E5"); ax.set_axisbelow(True)
        ax.tick_params(axis="y", length=0)
    fig.suptitle("Where problems were caught", x=0.01, ha="left", fontsize=14,
                 fontweight="bold", color=INK)
    fig.text(0.01, 0.01, "Sources: data/ami_trials.db; SPEC.md Quality log (rule-based "
             "exclusions, human review 2026-11-17)", color=MUTED, fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(OUT / "quality_checks.png", dpi=150)
    plt.close(fig)
    return dict(fetched=fetched, false_mesh=FALSE_MESH, shock=SHOCK, by_hand=by_hand,
                in_db=in_db, values=n_values, reviewed=reviewed, flag_verifier=flag_verifier,
                flag_code=flag_code, slip=slip, corr_flagged=corr_flagged,
                corr_human=corr_human, corrected=corrected)


def main():
    con = sqlite3.connect(DB)
    run = con.execute("select run_date from fetch_runs order by run_id desc limit 1").fetchone()
    snap = (run[0] or "")[:10] if run else "unknown"
    n_trials = con.execute("select count(*) from trials").fetchone()[0]
    n_withdrawn = con.execute("select count(*) from trials where overall_status = 'WITHDRAWN'"
                              ).fetchone()[0]
    OUT.mkdir(exist_ok=True)
    a = outcome_type_by_phase(con, snap)
    b = quality_checks(con)
    con.close()
    old = OUT / "surrogate_only_by_size.png"
    removed = old.exists()
    if removed:
        old.unlink()
    print("Wrote figures/outcome_type_by_phase.png and figures/quality_checks.png"
          + (" (removed figures/surrogate_only_by_size.png)" if removed else ""))
    print("=== Summary ===")
    print(f"Trials in: {n_trials}; chart 1 out: {a['All']} (Phase 3 {a['Phase 3']}, "
          f"Phase 2/3 {a['Phase 2/3']}); skipped: {n_withdrawn} (withdrawn)")
    print("Chart 2: " + ", ".join(f"{k} {v}" for k, v in b.items()))


if __name__ == "__main__":
    main()
