"""Build review/review_sheet.xlsx: one row per extracted value, for the owner's review.

Usage:  .venv\\Scripts\\python scripts\\build_review_sheet.py

Reads (never writes) for every trial with a main paper in review/paper_list.csv:
  extractions/<NCT>.json, extractions/inputs/<NCT>.json (arm drugs and doses),
  verifications/<NCT>.json, verifications/<NCT>_step1.json,
  checks/<NCT>_quote_check.csv
Writes review/review_sheet.xlsx (git-ignored: it holds paper quotes, decision 25).
Rows: every extracted value (decision 28: 100% review). Flagged rows first
(WRONG / UNCLEAR / NOT IN PAPER, quote-check FAIL, step-1 mismatch, no verdict),
then by trial (paper_list order). Missing data stays blank; nothing is guessed.
"""
import csv
import json
import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "review" / "review_sheet.xlsx"
CRITICAL = {"effect measure": "effect_measure", "effect value": "effect_value",
            "95% CI lower": "ci_lower", "95% CI upper": "ci_upper", "p-value": "p_value"}


def load(rel):
    p = ROOT / rel
    return json.load(open(p, encoding="utf-8")) if p.exists() else None


def norm(v):
    """Compare values ignoring spaces, thousands commas and a leading 'P='."""
    v = (v or "").lower().replace(" ", "").replace(" ", "").replace(",", "")
    return re.sub(r"^p=", "", v)


def trial_order():
    order, acronyms = [], {}
    with open(ROOT / "review" / "paper_list.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("proposed_main") == "yes" and r["nct_id"] not in order:
                order.append(r["nct_id"])
                acronyms[r["nct_id"]] = r.get("acronym") or ""
    return order, acronyms


def arm_names(inp):
    """arm_label -> 'label (drug names)' from the extractor input (registry arms)."""
    out = {}
    for a in (inp or {}).get("arms", []):
        drugs = [i["name"] for i in a.get("interventions", [])
                 if i.get("type") in ("DRUG", "BIOLOGICAL")]
        out[a["arm_label"]] = f"{a['arm_label']} ({' + '.join(drugs)})" if drugs else a["arm_label"]
    return out


def show_side(side, arms):
    """Whole registry label first, then split a pooled label on ' + ' (decision 32)."""
    side = side.strip()
    if side in arms:
        return arms[side]
    parts = [p.strip() for p in side.split(" + ")]
    if len(parts) > 1 and all(p in arms for p in parts):
        return " + ".join(arms[p] for p in parts)
    return side


def show_comparison(label, arms, factorial):
    if not label:
        return ""
    if factorial:
        return label  # factor names as the paper writes them (decision 32)
    return " vs ".join(show_side(s, arms) for s in label.split(" vs "))


def quote_rows(nct, source):
    p = ROOT / "checks" / f"{nct}_quote_check.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r["source"] == source]


def step1_lookup(s1):
    """(pmid, comparison, outcome) -> {field: value}; also total randomized per pmid."""
    crit, totals = {}, {}
    for c in (s1 or {}).get("comparisons", []):
        key = (c.get("pmid"), c.get("comparison"), c.get("outcome") or "primary")
        vals = {k: (c.get(k) or {}).get("value") for k in CRITICAL.values()}
        for p in c.get("p_values") or []:
            vals[f"p-value ({p.get('hypothesis', '')})"] = p.get("value")
        crit[key] = vals
        tr = (c.get("total_randomized") or {}).get("value")
        if tr:
            totals.setdefault(c.get("pmid"), set()).add(norm(tr))
    return crit, totals


def build_rows():
    """Every extracted value as one sheet row. Each row also carries (keys starting with
    '_', never written to the sheet) the value's identity and its verifier/check records,
    so scripts/load_reviewed_results.py can match the owner's decisions back."""
    order, acronyms = trial_order()
    rows, skipped = [], {}
    values_in = 0
    for t_idx, nct in enumerate(order):
        ex, ve = load(f"extractions/{nct}.json"), load(f"verifications/{nct}.json")
        if not ex:
            skipped[f"{nct}: no extraction file"] = 1
            continue
        inp = load(f"extractions/inputs/{nct}.json") or {}
        arms, factorial = arm_names(inp), bool(inp.get("factorial"))
        files = {p.get("pmid"): p.get("file") for p in inp.get("papers", [])}
        checks = (ve or {}).get("step2_checks", [])
        q_ex = quote_rows(nct, f"extractions/{nct}.json")
        q_ve = quote_rows(nct, f"verifications/{nct}.json")
        crit, totals = step1_lookup(load(f"verifications/{nct}_step1.json"))
        values = ex.get("values", [])
        values_in += len(values)

        for i, v in enumerate(values):
            key = (v.get("pmid"), v.get("arm"), v.get("comparison"), v["outcome"], v["field"])
            c = checks[i] if i < len(checks) else None
            if c and (c.get("pmid"), c.get("arm"), c.get("comparison"), c["outcome"], c["field"]) != key:
                c = None  # verdicts not in the same order: don't attach a wrong one
            qe = q_ex[i] if i < len(q_ex) else None
            if qe and (qe["outcome"], qe["field"]) != (v["outcome"], v["field"]):
                qe = None
            qv = q_ve[i] if (c is not None and i < len(q_ve)) else None
            if qv and (qv["outcome"], qv["field"]) != (c["outcome"], c["field"]):
                qv = None

            # step 1 match for the critical values
            s1 = ""
            fld = v["field"]
            if v["outcome"].startswith("primary") and (fld in CRITICAL or fld.startswith("p-value (")):
                sv = crit.get((v.get("pmid"), v.get("comparison"), v["outcome"]), {})
                want = sv.get(CRITICAL.get(fld, fld))
                if want is not None:
                    s1 = "match" if norm(want) == norm(v["value"]) else f"MISMATCH (step 1: {want})"
                else:
                    s1 = "no step-1 value"
            elif v["outcome"] == "trial" and fld == "total randomized":
                tot = totals.get(v.get("pmid")) or set().union(*totals.values()) if totals else set()
                if tot:
                    s1 = "match" if norm(v["value"]) in tot else f"MISMATCH (step 1: {', '.join(sorted(tot))})"

            verdict = (c or {}).get("verdict", "")
            flags = []
            if verdict in ("WRONG", "UNCLEAR", "NOT IN PAPER"):
                flags.append(f"verifier {verdict}")
            if not c:
                flags.append("no verifier verdict")
            if qe and qe["result"] == "FAIL":
                flags.append("quote check FAIL (extractor)")
            if qv and qv["result"] == "FAIL":
                flags.append("quote check FAIL (verifier)")
            if s1.startswith("MISMATCH"):
                flags.append("step-1 mismatch")

            vv, vq, vp = (c or {}).get("verifier_value"), (c or {}).get("verifier_quote"), (c or {}).get("verifier_page")
            rows.append({
                "_sort": (0 if flags else 1, t_idx, i),
                "_nct": nct, "_v": v, "_c": c, "_qe": qe, "_s1": s1,
                "flagged": "yes" if flags else "no",
                "flag_reason": "; ".join(flags),
                "trial": f"{nct} {acronyms.get(nct, '')}".strip(),
                "paper": f"PMID {v.get('pmid')} ({files.get(v.get('pmid'), '')})",
                "comparison": show_comparison(v.get("comparison"), arms, factorial),
                "arm": (v.get("arm") if factorial else show_side(v.get("arm") or "", arms)) or "",
                "outcome": v["outcome"], "field": fld,
                "extracted_value": v.get("value"), "confidence": v.get("confidence"),
                "quote": v.get("quote"), "quote_note": v.get("quote_note"), "page": v.get("page"),
                "verifier_verdict": verdict, "verifier_reason": (c or {}).get("reason", ""),
                "verifier_value (if different)": vv if vv is not None and norm(str(vv)) != norm(str(v.get("value"))) else "",
                "verifier_quote (if different)": vq if vq and vq != v.get("quote") else "",
                "verifier_page (if different)": vp if vp not in (None, "", 0) and vp != v.get("page") else "",
                "quote_check (extractor)": f"{qe['result']}{': ' + qe['reason'] if qe and qe.get('reason') else ''}" if qe else "",
                "quote_check (verifier)": f"{qv['result']}{': ' + qv['reason'] if qv and qv.get('reason') else ''}" if qv else "",
                "step1_match": s1,
                "my_decision": "", "corrected_value": "", "my_note": "",
            })

    rows.sort(key=lambda r: r["_sort"])
    return order, rows, values_in, skipped


def main():
    lock = OUT.parent / f"~${OUT.name}"
    if lock.exists():
        sys.exit(f"STOP: {OUT.name} is open in Excel ({lock.name} exists). Close it and re-run.")
    order, rows, values_in, skipped = build_rows()
    cols = [k for k in rows[0] if not k.startswith("_")]
    wb = Workbook()
    ws = wb.active
    ws.title = "review"
    ws.append(["row"] + cols)
    for n, r in enumerate(rows, 1):
        ws.append([n] + [r[c] for c in cols])
    # layout
    head = Font(bold=True)
    owner = PatternFill("solid", fgColor="FFF2CC")
    flag = PatternFill("solid", fgColor="F8CBAD")
    widths = {"quote": 60, "quote_note": 40, "verifier_reason": 45, "verifier_quote (if different)": 45,
              "flag_reason": 30, "comparison": 40, "extracted_value": 30, "my_note": 40,
              "verifier_value (if different)": 25, "corrected_value": 25}
    for j, name in enumerate(["row"] + cols, 1):
        cell = ws.cell(row=1, column=j)
        cell.font = head
        letter = cell.column_letter
        ws.column_dimensions[letter].width = widths.get(name, 16)
        if name in ("my_decision", "corrected_value", "my_note"):
            for k in range(1, len(rows) + 2):
                ws.cell(row=k, column=j).fill = owner
    wrap = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
        if row[cols.index("flagged") + 1].value == "yes":
            row[cols.index("flag_reason") + 1].fill = flag
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    dv = DataValidation(type="list", formula1='"correct,wrong,unclear"', allow_blank=True)
    dec_col = ws.cell(row=1, column=cols.index("my_decision") + 2).column_letter
    dv.add(f"{dec_col}2:{dec_col}{len(rows) + 1}")
    ws.add_data_validation(dv)
    wb.save(OUT)

    flagged = sum(r["flagged"] == "yes" for r in rows)
    print(f"Wrote {OUT.relative_to(ROOT)}")
    print("=== Summary ===")
    print(f"Trials:                {len(order)}")
    print(f"Extracted values in:   {values_in}")
    print(f"Rows written out:      {len(rows)}  (flagged {flagged}, not flagged {len(rows) - flagged})")
    reasons = {}
    for r in rows:
        for f_ in filter(None, r["flag_reason"].split("; ")):
            reasons[f_] = reasons.get(f_, 0) + 1
    for k, n in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  flag: {k}: {n}")
    print(f"Skipped:               {sum(skipped.values())}" + "".join(f"\n  {k}" for k in skipped))


if __name__ == "__main__":
    main()
