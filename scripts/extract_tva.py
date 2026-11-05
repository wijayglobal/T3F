"""Extract English -> Tamil pairs from two Tamil Virtual Academy science glossaries (OCR'd PDFs).

Usage: python3 -I extract_tva.py <book1.pdf> <book2.pdf> <out_dir>

  book1  அறிவியல் கலைச்சொல்லகராதி   table layout:  English   -   Tamil   (sub-entries marked with "..")
  book2  அறிவியல் கலைச்சொல் களஞ்சியம்  two-column prose: "English: (subject) Tamil: definition"

Writes <out_dir>/tva_glossary.jsonl and <out_dir>/tva_kalanjiyam.jsonl, one JSON object per line:
  {"en": ..., "ta": ..., "note": ..., "page": ...}
The source text is OCR output, so some Tamil is noisy; downstream marks it as unreviewed.
"""
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TAMIL = re.compile(r"[஀-௿]")
LATIN = re.compile(r"[A-Za-z]")
JUNK_EDGE = re.compile(r"^[\s\-—–~௪.,:;|_]+|[\s\-—–~௪.,:;|_]+$")


def clean_ta(s):
    s = s.replace("‌", "").replace("‍", "")
    s = re.sub(r"\s+", " ", s)
    return JUNK_EDGE.sub("", s)


def clean_en(s):
    s = re.sub(r"\s+", " ", s)
    return JUNK_EDGE.sub("", s).strip()


def good_ta(ta):
    return len(TAMIL.findall(ta)) >= 2 and len(LATIN.findall(ta)) <= 2 and len(ta) <= 120


def good_en(en):
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9 ,'\-/&()\.]{0,80}", en)) and len(LATIN.findall(en)) >= 2


# ---------------------------------------------------------------- book 1
SPLIT = re.compile(r"^(\s*)(.+?)\s{2,}[-—–~௪.\s]*([஀-௿].*)$")
HEADER = re.compile(r"\S.*\s{2,}\d{1,3}\s{2,}\S")


def book1(pdf):
    txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
    out = []
    for pno, page in enumerate(txt.split("\f"), 1):
        if pno < 16:  # front matter
            continue
        lines = [l for l in page.split("\n") if l.strip()]
        lines = [l for l in lines[1:] if not HEADER.match(l)] if lines and HEADER.match(lines[0]) else lines
        indents = [len(m.group(1)) for l in lines if (m := SPLIT.match(l)) and LATIN.search(m.group(2))]
        if not indents:
            continue
        base = min(indents)
        head = ""
        for l in lines:
            m = SPLIT.match(l)
            if not m:
                # left-only line at main indent => compound headword with sub-lines below
                s = l.strip()
                if LATIN.search(s) and not TAMIL.search(s) and len(l) - len(l.lstrip()) <= base + 1:
                    head = clean_en(s.rstrip("-—–~"))
                continue
            indent, left, right = len(m.group(1)), m.group(2).strip(), clean_ta(m.group(3))
            if not good_ta(right):
                continue
            left_c = left.rstrip("-—–~ ")
            if left_c.startswith(".") or left_c.endswith("."):
                core = clean_en(left_c.strip("."))
                en = f"{head} {core}" if left_c.startswith(".") else f"{core} {head}"
            elif indent > base + 1 and head:
                en = f"{head} {clean_en(left_c)}"
            else:
                en = clean_en(left_c)
                head = en
            en = clean_en(en)
            if good_en(en):
                out.append({"en": en, "ta": right, "note": "", "page": pno})
    return out


# ---------------------------------------------------------------- book 2
NS = {"x": "http://www.w3.org/1999/xhtml"}
ENTRY = re.compile(
    r"(?:(?<=\s)|^)([A-Z][A-Za-z0-9 ,'\-/&\.]{1,60}?)\s*:\s*(?:\(([^)]{1,25})\)\s*)?(?=[஀-௿])"
)


def book2(pdf):
    xml = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"], capture_output=True, text=True).stdout
    root = ET.fromstring(xml.replace('xmlns="http://www.w3.org/1999/xhtml"', ""))
    chunks = []
    for pno, page in enumerate(root.iter("page"), 1):
        if pno < 20:
            continue
        mid = float(page.get("width")) / 2
        cols = ([], [])
        # OCR "lines" span both columns, so assign each word to a column by its own centre
        for w in page.iter("word"):
            x0, x1, y0, y1 = (float(w.get(k)) for k in ("xMin", "xMax", "yMin", "yMax"))
            cols[0 if (x0 + x1) / 2 < mid else 1].append((y0, y1 - y0, x0, w.text or ""))
        for c in cols:
            c.sort()
            lines, cur, last = [], [], None
            for y0, h, x0, t in c:
                if last is not None and y0 - last > 0.6 * max(h, 1):
                    lines.append(cur)
                    cur = []
                cur.append((x0, t))
                last = y0 if last is None or not cur[:-1] else last
            if cur:
                lines.append(cur)
            chunks.append((pno, " ".join(t for ln in lines for _, t in sorted(ln))))
    # walk columns in reading order, tracking which page each entry started on
    text, marks = "", []
    for pno, c in chunks:
        marks.append((len(text), pno))
        text += c.replace("‌", "") + " "
    out, ms = [], list(ENTRY.finditer(text))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        body = text[m.end():end].strip()
        en = clean_en(m.group(1))
        if not good_en(en) or not body:
            continue
        head = re.split(r"[:;]", body, maxsplit=1)
        ta_part = clean_ta(head[0])
        definition = clean_ta(head[1]) if len(head) > 1 else ""
        page = max((p for off, p in marks if off <= m.start()), default=0)
        subject = (m.group(2) or "").strip()
        # a Tamil rendering may list alternatives separated by commas
        for ta in [clean_ta(x) for x in re.split(r"\s*,\s*", ta_part)]:
            if len(ta) > 60:
                continue
            if good_ta(ta):
                note = definition[:400]
                if subject:
                    note = f"({subject}) {note}".strip()
                out.append({"en": en, "ta": ta, "note": note, "page": page})
    return out


def dump(rows, path):
    seen, n = set(), 0
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            k = (r["en"].lower(), r["ta"])
            if k in seen:
                continue
            seen.add(k)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    print(path, n)


if __name__ == "__main__":
    b1, b2, out = sys.argv[1:4]
    Path(out).mkdir(parents=True, exist_ok=True)
    dump(book1(b1), Path(out) / "tva_glossary.jsonl")
    dump(book2(b2), Path(out) / "tva_kalanjiyam.jsonl")
