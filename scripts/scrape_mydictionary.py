"""Scrape every dictionary entry from mydictionary.in (தமிழ்ப்பேழை, Creative Commons licensed).

Usage: python3 -I scrape_mydictionary.py <work_dir> [--workers N] [--limit N]

The site has no bulk export and its search is exact-match only, so the scrape runs in phases:
  1. Download the list of dictionaries, then each dictionary page (it embeds every headword in
     A-Z tabs) and its editor panel (which states that book's licence, e.g. "CC BY-SA").
  2. POST words to the site-wide search (/tpdbtamilpelai.php). A search returns the exact
     matches plus every multi-word entry containing the word ("combination"), across all
     dictionaries, with translation, domain and source book. So only a covering set of words is
     searched: every one-word headword, plus enough words that each longer headword contains one.
  3. Search, as a whole, any headword that phase 2 did not turn up.

Everything is cached under <work_dir> (pages/, queries.jsonl), so an interrupted run resumes.
Writes <work_dir>/mydictionary.jsonl, one deduplicated entry per line:
  {"term": ..., "term_note": ..., "meaning": ..., "meaning_note": ..., "dictionary": ...,
   "dictionary_en": ..., "dictionary_url": ..., "license": ...}
The notes are the bracketed domain / language tags, e.g. "computer science", "*LATIN".
"""
import argparse
import functools
import hashlib
import html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://mydictionary.in"
SEARCH = BASE + "/tpdbtamilpelai.php"
LIST = BASE + "/menutamilpelai/listofdictionariescontent.php"
UA = "Mozilla/5.0 (tamil_translation dataset builder; CC-licensed scrape)"
STANDARD_INCLUDES = ("topmenu", "leftcolumn", "rightcolumn", "footer", "afile")

LIST_BLOCK = re.compile(r'<div class="ex1">(.*?)</table>', re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
INCLUDE = re.compile(r'ajaxinclude\("([^"]+)"\)')
LICENSE = re.compile(r"உரிமை நிலை\s*</font>\s*</?br\s*/?>\s*([^<]+)", re.S)
RESULT = re.compile(
    r"color='#0eaf0e'[^>]*>(.*?)</td>.*?color='#8B008B'[^>]*>(.*?)</td>.*?"
    r"title='([^']*)'><a href='([^']*)'[^>]*>(.*?)</a>",
    re.S,
)


def fetch(url, data=None, timeout=300, tries=5):
    if data is not None:
        data = urllib.parse.urlencode(data).encode()
    url = urllib.parse.quote(url, safe=":/?=&%-")
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise
            print(f"  retry {attempt + 1} {url[:80]}: {e}", file=sys.stderr)
            time.sleep(5 * 2**attempt)


def text(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def split_note(s):
    """'<i>ab initio</i> <font ...>(*LATIN) </font>' -> ('ab initio', '*LATIN')"""
    i = s.find("<font")
    main, note = (s, "") if i < 0 else (s[:i], s[i:])
    note = text(note)
    if note.startswith("(") and note.endswith(")"):
        note = note[1:-1].strip()
    return text(main), note


def parse_results(page):
    rows = []
    for head, gloss, title, href, name in RESULT.findall(page):
        term, term_note = split_note(head)
        meaning, meaning_note = split_note(gloss)
        rows.append({
            "term": term, "term_note": term_note, "meaning": meaning, "meaning_note": meaning_note,
            "dictionary": text(name), "dictionary_en": html.unescape(title),
            "dictionary_url": urllib.parse.unquote(href),
        })
    return rows


def cached(path, url):
    if not path.exists():
        path.write_text(fetch(url), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def collect_dictionaries(work):
    pages = work / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    listing = cached(pages / "_list.html", LIST)
    slugs = sorted(set(re.findall(r'href="(/-[^"]+)"', listing)))
    print(f"phase 1: {len(slugs)} dictionaries", file=sys.stderr)
    books, headwords = {}, set()
    for n, slug in enumerate(slugs, 1):
        key = hashlib.md5(slug.encode()).hexdigest()[:10]
        page = cached(pages / f"{key}.html", BASE + slug)
        heads = {text(c) for block in LIST_BLOCK.findall(page) for c in CELL.findall(block)} - {""}
        licence = ""
        for inc in INCLUDE.findall(page):
            if not any(s in inc for s in STANDARD_INCLUDES) and "/edit" in inc:
                m = LICENSE.search(cached(pages / f"{key}_edit.html", BASE + inc))
                licence = text(m.group(1)) if m else ""
        books[BASE + urllib.parse.unquote(slug)] = {"slug": slug, "headwords": len(heads), "license": licence}
        headwords |= heads
        print(f"  [{n}/{len(slugs)}] {urllib.parse.unquote(slug)}: {len(heads)} headwords, {licence or '?'}",
              file=sys.stderr)
    (work / "dictionaries.json").write_text(json.dumps(books, ensure_ascii=False, indent=1), encoding="utf-8")
    return books, headwords


def tokens(headword):
    """Distinct casefolded words; punctuation-only bits like '%' are skipped (they break the search)."""
    out = set()
    for t in headword.split():
        t = t.strip(".,;:()[]{}\"'")
        if re.search(r"\w", t):
            out.add(t.casefold())
    return out


def covering_words(headwords):
    """Every one-word headword, then, most frequent first, words until each headword has one."""
    toks = {h: tokens(h) for h in headwords}
    chosen = {next(iter(t)) for t in toks.values() if len(t) == 1}
    rest = [t for t in toks.values() if len(t) > 1 and not t & chosen]
    freq = {}
    for t in rest:
        for w in t:
            freq[w] = freq.get(w, 0) + 1
    for t in rest:
        if not t & chosen:
            chosen.add(max(t, key=lambda w: (freq[w], w)))
    return sorted(chosen)


def run_queries(work, queries, workers, done):
    todo = [q for q in queries if q not in done]
    print(f"  {len(todo)} to search ({len(queries) - len(todo)} cached), {workers} workers", file=sys.stderr)
    lock = threading.Lock()
    start = time.time()
    with open(work / "queries.jsonl", "a", encoding="utf-8") as out, ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(fetch, SEARCH, {"search": q}): q for q in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            q = futures[fut]
            try:
                rows = parse_results(fut.result())
            except Exception as e:  # leave it uncached so the next run retries it
                print(f"  FAILED {q!r}: {e}", file=sys.stderr)
                continue
            with lock:
                out.write(json.dumps({"q": q, "rows": rows}, ensure_ascii=False) + "\n")
                out.flush()
                done[q] = rows
            if n % 50 == 0 or n == len(todo):
                rate = n / (time.time() - start)
                eta = (len(todo) - n) / rate / 3600
                print(f"  {n}/{len(todo)}  {rate:.2f} q/s  eta {eta:.1f} h", file=sys.stderr)


def load_done(work):
    done = {}
    path = work / "queries.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["q"]] = rec["rows"]
    return done


def norm(s):
    return re.sub(r"\s+", " ", s).strip().casefold()


def book_resolver(books):
    """Map a result row to its book's URL. Result links are unreliable: the same book appears as
    '/-ஆட்சிச்-சொல்லகராதி-' or '/ஆட்சிச்-சொல்லகராதி', with spaces for hyphens or a dropped final vowel
    sign, and every வெற்றி அகராதி row links to the computer dictionary. So match the book's
    display name against the page slugs first ('வெற்றி அகராதி (1995)' -> '/-வெற்றி-அகராதி-'), and
    only then the link, loosely."""
    def key(s):
        return re.sub(r"[\W_]+", "", s)  # also drops Tamil vowel signs, the same way on both sides

    by_key = {key(urllib.parse.urlparse(u).path): u for u in books}

    @functools.lru_cache(maxsize=None)
    def resolve(name, url):
        k = key(re.sub(r"\(\d{4}\)\s*$", "", name))
        if k in by_key:
            return by_key[k]
        k = key(urllib.parse.urlparse(url).path)
        if k in by_key:
            return by_key[k]
        hits = {u for s, u in by_key.items() if k and (s.startswith(k) or k.startswith(s))}
        return hits.pop() if len(hits) == 1 else url

    return lambda r: resolve(r["dictionary"], r["dictionary_url"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("--workers", type=int, default=2, help="concurrent searches (be gentle; the server is slow)")
    ap.add_argument("--limit", type=int, help="only search the first N words (for a trial run)")
    ap.add_argument("--export-only", action="store_true", help="just write mydictionary.jsonl from the cache")
    args = ap.parse_args()
    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)

    books, headwords = collect_dictionaries(work)
    done = load_done(work)

    if args.export_only:
        return export(work, books, headwords, done)

    words = covering_words(headwords)
    if args.limit:
        words = words[: args.limit]
    print(f"phase 2: {len(headwords)} distinct headwords -> {len(words)} covering words", file=sys.stderr)
    run_queries(work, words, args.workers, done)

    if not args.limit:
        seen = {norm(r["term"]) for rows in done.values() for r in rows}
        missing = sorted(h for h in headwords if norm(h) not in seen)
        print(f"phase 3: {len(missing)} headwords not yet found", file=sys.stderr)
        run_queries(work, missing, args.workers, done)
    export(work, books, headwords, done)


def export(work, books, headwords, done):
    entries, keys = [], set()
    for rows in done.values():
        for r in rows:
            k = tuple(r[f] for f in ("term", "term_note", "meaning", "meaning_note", "dictionary"))
            if k not in keys:
                keys.add(k)
                entries.append(r)
    book = book_resolver(books)
    entries = [
        {**r, "dictionary_url": (u := book(r)), "license": books.get(u, {}).get("license", "")} for r in entries
    ]
    entries.sort(key=lambda r: (r["dictionary"], r["term"].casefold(), r["meaning"]))
    with open(work / "mydictionary.jsonl", "w", encoding="utf-8") as f:
        for r in entries:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    found = {norm(r["term"]) for r in entries}
    unmatched = sum(1 for h in headwords if norm(h) not in found)
    print(f"wrote {len(entries)} entries; {unmatched} headwords still unmatched", file=sys.stderr)


if __name__ == "__main__":
    main()
