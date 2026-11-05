"""Collect English→Tamil pairs from open sources into the common dataset.

    manage.py ingest wikipedia_ta [--max-requests N]
    manage.py ingest file PATH --name "My source" --license "CC BY 4.0" [--url https://…]

Every row lands as an unreviewed DRAFT with its source, URL and licence, so the review
queue (and the Hugging Face export) can tell exactly where it came from. Only open
APIs/dumps are used, with a descriptive User-Agent and a delay between requests.
"""
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from lexicon.models import SourceKind, Status, Suggestion, Term

UA = "KalaicholBot/0.1 (Tamil term dataset; contact: admin@localhost)"
PAREN = re.compile(r"\s*\(([^)]*)\)\s*$")


def save(rows, name, license_, kind=SourceKind.WEB, status=Status.DRAFT, author=None):
    """rows: dicts with en, ta and optional note/url/ref. Skips pairs that already exist."""
    clean = []
    for r in rows:
        en = re.sub(r"\s+", " ", r["en"]).strip().lower()
        ta = re.sub(r"\s+", " ", r["ta"]).strip()
        if en and ta and any("஀" <= c <= "௿" for c in ta) and len(en) <= 120 and len(ta) <= 200:
            clean.append((en, ta, r))
    Term.objects.bulk_create([Term(text=e) for e in {c[0] for c in clean}], ignore_conflicts=True, batch_size=2000)
    tid = dict(Term.objects.filter(text__in={c[0] for c in clean}).values_list("text", "id"))
    before = Suggestion.objects.count()
    Suggestion.objects.bulk_create(
        [
            Suggestion(
                term_id=tid[en], tamil=ta, note=r.get("note", "")[:400], source=name, source_kind=kind,
                source_url=r.get("url", ""), source_ref=r.get("ref", ""), status=status, license=license_, author=author,
            )
            for en, ta, r in clean
        ],
        ignore_conflicts=True, batch_size=2000,
    )
    return Suggestion.objects.count() - before


def get(url, tries=6):
    """GET JSON, backing off on 429/5xx (honouring Retry-After)."""
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as f:
                return json.load(f)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
            time.sleep(int(e.headers.get("Retry-After", 0)) or 10 * 2**i)


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("source", choices=["wikipedia_ta", "file"])
        parser.add_argument("path", nargs="?")
        parser.add_argument("--name", default="")
        parser.add_argument("--license", default="")
        parser.add_argument("--url", default="")
        parser.add_argument("--max-requests", type=int, default=0, help="0 = no limit")
        parser.add_argument("--delay", type=float, default=2.0)

    def handle(self, source, path, name, license, url, max_requests, delay, **opts):
        if source == "file":
            if not (path and name and license):
                raise CommandError("file source needs PATH, --name and --license")
            n = save(self.read_file(path, url), name, license)
            self.stdout.write(self.style.SUCCESS(f"{n} new suggestions from {path}"))
        else:
            self.wikipedia_ta(max_requests, delay)

    def read_file(self, path, url):
        p = Path(path)
        if p.suffix == ".jsonl":
            for line in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                r.setdefault("url", url)
                yield r
        else:
            with p.open(encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f, delimiter="\t" if p.suffix in (".tsv", ".txt") else ","):
                    r.setdefault("url", url)
                    yield r

    def wikipedia_ta(self, max_requests, delay):
        """Tamil Wikipedia article titles with an English interlanguage link (CC BY-SA 4.0)."""
        api = "https://ta.wikipedia.org/w/api.php"
        params = {
            "action": "query", "format": "json", "generator": "allpages", "gapnamespace": "0",
            "gapfilterredir": "nonredirects", "gaplimit": "500", "prop": "langlinks",
            "lllang": "en", "lllimit": "500",
        }
        state = Path("data_raw/wikipedia_ta.cont")  # lets an interrupted run resume
        cont = json.loads(state.read_text()) if state.exists() else {}
        requests, total = 0, 0
        while True:
            data = get(api + "?" + urllib.parse.urlencode({**params, **cont}))
            rows = []
            for page in data.get("query", {}).get("pages", {}).values():
                for ll in page.get("langlinks", []):
                    en = ll["*"] if "*" in ll else ll.get("title", "")
                    ta = page["title"]
                    note = ""
                    if m := PAREN.search(en):
                        note, en = f"(English page: {m.group(1)})", PAREN.sub("", en)
                    # enwiki titles of common nouns are "Anode"; names have more capitals ("Robert the Doll")
                    if not re.fullmatch(r"[A-Z][a-z]+(?:[ \-][a-z]+)*", en):
                        continue
                    ta = PAREN.sub("", ta).strip("'\" ")
                    rows.append({
                        "en": en, "ta": ta, "note": note,
                        "url": "https://ta.wikipedia.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_")),
                    })
            total += save(rows, "Tamil Wikipedia (interlanguage links)", "CC BY-SA 4.0")
            requests += 1
            self.stdout.write(f"  request {requests}: +{total} total new")
            cont = data.get("continue")
            state.write_text(json.dumps(cont or {}))
            if not cont or (max_requests and requests >= max_requests):
                break
            time.sleep(delay)
        self.stdout.write(self.style.SUCCESS(f"{total} new suggestions from ta.wikipedia.org"))
