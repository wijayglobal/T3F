import hashlib

from django.core.management.base import BaseCommand
from django.db import transaction

from lexicon.domains import for_source
from lexicon.importing import attest, suggestion_ids
from lexicon.models import Attestation, SourceKind, Status, Suggestion, TamilSense, Term
from lexicon.schemas import tamil_definitions, validate_file

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
                        sense=r.sense, domain=r.domain,
                        source=r.source, source_kind=SourceKind.BOOK, source_url=r.source_url,
                        source_ref="mydictionary.in", status=Status.DRAFT, license=r.license.value,
                    )
                    for r in {r.key(): r for r in reversed(rows)}.values()  # first book per pair
                ],
                # an existing pair (a user's word, another book) keeps its own source and status
                ignore_conflicts=True,
                batch_size=BATCH,
            )
            sid = suggestion_ids({r.key() for r in rows}, tid)
            attest([
                Attestation(
                    suggestion_id=sid[r.key()], source=r.source, source_kind=SourceKind.BOOK,
                    source_url=r.source_url, source_ref="mydictionary.in", license=r.license.value,
                    sense=r.sense, domain=r.domain, note=r.note,
                )
                for r in rows if r.key() in sid
            ], batch_size=BATCH)
            # Tamil headwords with Tamil meanings (Sangam / Siddha books): kept as senses of the word
            senses = [
                TamilSense(
                    word=e.term, gloss="; ".join(x for x in (e.meaning, e.meaning_note) if x), gloss_lang="ta",
                    domain=for_source(e.dictionary, e.dictionary_en), source=e.dictionary,
                    source_url=str(e.dictionary_url), license=e.license.value,
                    ref=hashlib.sha1(f"{e.term}|{e.meaning}".encode()).hexdigest()[:20],
                )
                for e in tamil_definitions(path)
                if len(e.term) <= 200
            ]
            TamilSense.objects.bulk_create(senses, ignore_conflicts=True, batch_size=BATCH)
        self.stdout.write(f"{len(senses)} Tamil-Tamil definitions kept as Tamil senses")
        self.stdout.write(
            f"terms +{Term.objects.count() - before_t}, suggestions +{Suggestion.objects.count() - before_s} "
            f"(pairs already present were left as they were). Run build_embeddings to embed the new terms."
        )
