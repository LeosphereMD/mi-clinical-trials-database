"""Code check: is every agent quote found on its stated page? (SPEC.md "Code checks")

Usage:  .venv\\Scripts\\python scripts\\check_quotes.py NCT04509674 [NCT...]

For each trial it collects every quote in:
  outcome_checks/<NCT>.json, extractions/<NCT>.json,
  verifications/<NCT>_step1.json, verifications/<NCT>.json
and looks for it on the stated PDF page.

Before matching, both the quote and the page text are normalised (agent fix d):
  - typographic variants folded (ligatures, curly quotes, dash types, soft hyphens)
  - a plain hyphen between two letters is removed, with or without a line break
    ("hos-" / "pitalization", "patient-years"); hyphens next to numbers are kept
  - all whitespace is removed
A quote that runs onto the next page (page headers/footers in between are ignored)
passes only if it has a quote_note "continues on page N".

Output: checks/<NCT>_quote_check.csv with source, outcome, field, arm, comparison,
stated page, PASS/FAIL/SKIP and a short reason. Never any quote or paper text
(SPEC.md "Code checks"; checks/ is git-ignored).
"""
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent

FOLD = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "−": "-", "­": "-",
})


def norm(text):
    # Soft hyphen (U+00AD) becomes a plain hyphen, so the rule below treats it like any
    # other: removed between letters ("pa-tient"), kept next to numbers ("50-mg").
    text = unicodedata.normalize("NFKC", text or "").replace("­", "-")
    # Plain hyphen between two letters, with or without a line break: removed on both
    # sides, because a real hyphen at a line end ("patient-" / "years") can't be told
    # apart from a line-break hyphen ("hos-" / "pitalization"). pypdf sometimes puts a
    # space before it ("hos -"). Done before folding, so a long dash (" — ") and
    # hyphens next to numbers are never removed.
    text = re.sub(r"(?<=[^\W\d_])\s?-\s*(?=[^\W\d_])", "", text)
    text = text.translate(FOLD)
    return re.sub(r"\s+", "", text)      # all whitespace


def spans(q, first, second):
    """True if the quote starts on page `first` and finishes on page `second`.
    Page headers/footers between the two parts are ignored."""
    k = 0
    while k < len(q) and q[:k + 1] in first:
        k += 1
    return 20 <= k < len(q) and q[k:] in second


def load(path):
    p = ROOT / path
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def pick(d):
    return dict(quote=d.get("quote"), file=d.get("file"), page=d.get("page"),
                quote_note=d.get("quote_note", ""))


def collect(nct):
    """Yield one dict per quote found in the agent output files."""
    oc = load(f"outcome_checks/{nct}.json")
    if oc:
        src = f"outcome_checks/{nct}.json"
        for paper in oc.get("papers", []):
            pe = paper.get("primary_endpoint") or {}
            yield dict(source=src, outcome="primary", field="primary_endpoint", arm="",
                       comparison="", **pick(pe))
        for key in ("disclosure_hits", "near_matches"):
            for i, hit in enumerate(oc.get(key, []), 1):
                yield dict(source=src, outcome="", field=f"{key} #{i}", arm="",
                           comparison="", **pick(hit))
    ex = load(f"extractions/{nct}.json")
    if ex:
        src = f"extractions/{nct}.json"
        for v in ex.get("values", []):
            yield dict(source=src, outcome=v.get("outcome", ""), field=v.get("field", ""),
                       arm=v.get("arm") or "", comparison=v.get("comparison") or "",
                       not_reported=v.get("not_reported", False), **pick(v))
    s1 = load(f"verifications/{nct}_step1.json")
    if s1:
        src = f"verifications/{nct}_step1.json"
        for comp in s1.get("comparisons", []):
            # "outcome" names the primary endpoint when a paper has several (decision 32).
            outcome = comp.get("outcome") or "primary"
            for key, item in comp.items():
                if isinstance(item, dict) and "quote" in item:
                    yield dict(source=src, outcome=outcome, field=key, arm="",
                               comparison=comp.get("comparison", ""), **pick(item))
                # Several p-values for one comparison: one entry per hypothesis.
                elif key == "p_values" and isinstance(item, list):
                    for p in item:
                        if isinstance(p, dict) and "quote" in p:
                            yield dict(source=src, outcome=outcome,
                                       field=f"p_value ({p.get('hypothesis', '')})", arm="",
                                       comparison=comp.get("comparison", ""), **pick(p))
    ve = load(f"verifications/{nct}.json")
    if ve:
        src = f"verifications/{nct}.json"
        for c in ve.get("step2_checks", []):
            yield dict(source=src, outcome=c.get("outcome", ""), field=c.get("field", ""),
                       arm=c.get("arm") or "", comparison=c.get("comparison") or "",
                       quote=c.get("verifier_quote"), file=c.get("verifier_file"),
                       page=c.get("verifier_page"),
                       quote_note=c.get("quote_note") or c.get("verifier_quote_note") or "")
        for key, item in (ve.get("step3") or {}).items():
            if isinstance(item, dict):
                yield dict(source=src, outcome="step3", field=key, arm="", comparison="",
                           **pick(item))


_pages_cache = {}


def page_texts(file):
    if file not in _pages_cache:
        p = ROOT / file
        _pages_cache[file] = ([norm(pg.extract_text() or "") for pg in PdfReader(p).pages]
                              if p.exists() else None)
    return _pages_cache[file]


def check(rec):
    """Return (result, reason). Reasons never contain paper text."""
    if rec.get("not_reported") or not rec.get("quote"):
        return "SKIP", "no quote (not reported)"
    if not rec.get("file"):
        return "FAIL", "quote has no file"
    pages = page_texts(rec["file"])
    if pages is None:
        return "SKIP", "paper file missing"
    try:
        page = int(rec.get("page"))
    except (TypeError, ValueError):
        return "FAIL", "page missing or not a number"
    if not 1 <= page <= len(pages):
        return "FAIL", f"page {page} out of range (file has {len(pages)})"
    q = norm(rec["quote"])
    if q in pages[page - 1]:
        return "PASS", ""
    if page < len(pages) and spans(q, pages[page - 1], pages[page]):
        if "continues on page" in (rec.get("quote_note") or ""):
            return "PASS", f"spans pages {page}-{page + 1} (noted)"
        return "FAIL", f"spans pages {page}-{page + 1}, no 'continues on page' note"
    found = [i + 1 for i, t in enumerate(pages) if q in t]
    if found:
        return "FAIL", "found on page " + ", ".join(map(str, found)) + " instead"
    for i in range(len(pages) - 1):
        if spans(q, pages[i], pages[i + 1]):
            return "FAIL", f"found across pages {i + 1}-{i + 2} instead"
    return "FAIL", "not found in file"


def main(ncts):
    if not ncts:
        print(__doc__)
        sys.exit(1)
    total_in = total_out = 0
    results, skipped = Counter(), Counter()
    no_outputs = []
    for nct in ncts:
        recs = list(collect(nct))
        if not recs:
            no_outputs.append(nct)
            continue
        rows = []
        for r in recs:
            res, reason = check(r)
            results[res] += 1
            if res == "SKIP":
                skipped[reason] += 1
            elif res == "FAIL":
                print(f"FAIL {nct} | {r['source']} | {r['outcome']} | {r['field']} | "
                      f"{r['arm']} | {r['comparison']} | page {r['page']} | {reason}")
            rows.append([r["source"], r["outcome"], r["field"], r["arm"], r["comparison"],
                         r["page"], res, reason])
        out = ROOT / "checks" / f"{nct}_quote_check.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["source", "outcome", "field", "arm", "comparison", "stated_page",
                        "result", "reason"])
            w.writerows(rows)
        total_in += len(recs)
        total_out += len(rows)
        print(f"{nct}: wrote {out.relative_to(ROOT)}")

    print("\n=== Summary ===")
    print(f"Trials asked for:        {len(ncts)}")
    print(f"Trials with no outputs:  {len(no_outputs)} {no_outputs if no_outputs else ''}")
    print(f"Quote records in:        {total_in}")
    print(f"Rows written out:        {total_out}")
    print(f"  PASS: {results['PASS']}   FAIL: {results['FAIL']}   SKIP: {results['SKIP']}")
    for reason, n in skipped.items():
        print(f"  skipped ({reason}): {n}")


if __name__ == "__main__":
    main(sys.argv[1:])
