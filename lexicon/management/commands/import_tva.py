import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from lexicon.models import SourceKind, Status, Suggestion, Term

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
            rows = []
            for line in (Path(directory) / name).read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                text = re.sub(r"\s+", " ", r["en"]).strip().lower()
                rows.append((text, r["ta"], r["note"], label, f"{book_id}, p. {r['page']}"))
            Term.objects.bulk_create(
                [Term(text=t) for t in {r[0] for r in rows}], ignore_conflicts=True, batch_size=2000
            )
            tid = dict(Term.objects.filter(text__in={r[0] for r in rows}).values_list("text", "id"))
            before = Suggestion.objects.count()
            Suggestion.objects.bulk_create(
                [
                    Suggestion(
                        term_id=tid[t], tamil=ta, note=note, source=src,
                        source_kind=SourceKind.BOOK, source_ref=ref,
                        status=Status.DRAFT, license="check publisher rights",
                    )
                    for t, ta, note, src, ref in rows
                ],
                update_conflicts=True,
                unique_fields=["term", "tamil", "region"],
                update_fields=["note", "source", "source_kind", "source_ref", "status", "license"],
                batch_size=2000,
            )
            self.stdout.write(f"{name}: {len(rows)} rows, {Suggestion.objects.count() - before} new suggestions")
