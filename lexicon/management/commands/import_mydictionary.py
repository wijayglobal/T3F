from django.core.management.base import BaseCommand
from django.db import transaction

from lexicon.models import SourceKind, Status, Suggestion, Term
from lexicon.schemas import validate_file

BATCH = 5000


class Command(BaseCommand):
    help = (
        "Import English→Tamil pairs scraped from mydictionary.in (scripts/scrape_mydictionary.py), "
        "validated by lexicon.schemas. Rows land as unreviewed drafts with their book and licence."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default="data_raw/mydictionary/mydictionary.jsonl")
        parser.add_argument("--dry-run", action="store_true", help="validate and report only")

    def handle(self, path, dry_run=False, **opts):
        rows, rep = validate_file(path)
        self.stdout.write(
            f"{rep.lines} lines → {rep.entries} valid entries {rep.by_direction} → "
            f"{rep.suggestions} suggestions ({rep.truncated} meanings cut off on the site)"
        )
        for reason, n in sorted(rep.rejected.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"  rejected {n:>6}  {reason}\n           e.g. {rep.examples[reason][:100]}")
        if dry_run:
            return

        texts = sorted({r.term for r in rows})
        with transaction.atomic():
            before_t, before_s = Term.objects.count(), Suggestion.objects.count()
            Term.objects.bulk_create(
                [Term(text=t) for t in texts], ignore_conflicts=True, batch_size=BATCH
            )
            tid = {}
            for i in range(0, len(texts), BATCH):  # chunked: SQLite caps query parameters
                tid.update(Term.objects.filter(text__in=texts[i : i + BATCH]).values_list("text", "id"))
            Suggestion.objects.bulk_create(
                [
                    Suggestion(
                        term_id=tid[r.term], tamil=r.tamil, pos=r.pos, note=r.note,
                        source=r.source, source_kind=SourceKind.BOOK, source_url=r.source_url,
                        source_ref="mydictionary.in", status=Status.DRAFT, license=r.license.value,
                    )
                    for r in rows
                ],
                # an existing pair (a user's word, another book) keeps its own source and status
                ignore_conflicts=True,
                batch_size=BATCH,
            )
        self.stdout.write(
            f"terms +{Term.objects.count() - before_t}, suggestions +{Suggestion.objects.count() - before_s} "
            f"(pairs already present were left as they were). Run build_embeddings to embed the new terms."
        )
