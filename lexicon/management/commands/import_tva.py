import json
import re
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand

from lexicon.domains import for_source
from lexicon.importing import attest, suggestion_ids
from lexicon.models import Attestation, SourceKind, Status, Suggestion, Term
from lexicon.ocr import english_problem, fix_tamil, tamil_problem

SOURCES = {
    "tva_glossary.jsonl": ("TVA · அறிவியல் கலைச்சொல்லகராதி (OCR)", "TVA_BOK_0006216"),
    "tva_kalanjiyam.jsonl": ("TVA · அறிவியல் கலைச்சொல் களஞ்சியம் (OCR)", "TVA_BOK_0002295"),
}


class Command(BaseCommand):
    help = "Import English→Tamil pairs extracted from the TVA science glossaries (scripts/extract_tva.py)."

    def add_arguments(self, parser):
        parser.add_argument("directory", nargs="?", default="data_raw")

    def handle(self, directory, **opts):
        for name, (label, book_id) in SOURCES.items():
            rows, skipped, seen = [], Counter(), set()
            for line in (Path(directory) / name).read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                text = re.sub(r"\s+", " ", r["en"]).strip().lower()
                tamil = fix_tamil(r["ta"])
                why = english_problem(text) or tamil_problem(tamil)
                if not why and not (0 < len(text) <= 120 and len(tamil) <= 200):
                    why = "too long"
                if why:
                    skipped[why] += 1
                    continue
                if (text, tamil) in seen:
                    continue
                seen.add((text, tamil))
                rows.append((text, tamil, r["note"], label, f"{book_id}, p. {r['page']}"))
            Term.objects.bulk_create(
                [Term(text=t) for t in {r[0] for r in rows}], ignore_conflicts=True, batch_size=2000
            )
            tid = dict(Term.objects.filter(text__in={r[0] for r in rows}).values_list("text", "id"))
            before = Suggestion.objects.count()
            Suggestion.objects.bulk_create(
                [
                    Suggestion(
                        term_id=tid[t], tamil=ta, note=note, source=src,
                        source_kind=SourceKind.BOOK, source_ref=ref, domain=for_source(src),
                        status=Status.DRAFT, license="check publisher rights",
                    )
                    for t, ta, note, src, ref in rows
                ],
                ignore_conflicts=True,  # a pair another source already has keeps its row
                batch_size=2000,
            )
            sid = suggestion_ids({(t, ta) for t, ta, *_ in rows}, tid)
            attest([
                Attestation(
                    suggestion_id=sid[(t, ta)], source=src, source_kind=SourceKind.BOOK, source_ref=ref,
                    license="check publisher rights", domain=for_source(src), note=note,
                )
                for t, ta, note, src, ref in rows if (t, ta) in sid
            ])
            self.stdout.write(f"{name}: {len(rows)} rows, {Suggestion.objects.count() - before} new suggestions")
            for why, n in skipped.most_common():
                self.stdout.write(f"  skipped {n:>5}  {why}")
