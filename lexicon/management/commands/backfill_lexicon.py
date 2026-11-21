from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef

from lexicon.domains import for_source
from lexicon.models import Attestation, Suggestion
from lexicon.ocr import fix_tamil, tamil_problem

TVA = "TVA · "


class Command(BaseCommand):
    help = (
        "Bring rows imported before the domain / OCR fixes up to date: set Suggestion.domain from the "
        "source book, repair OCR'd TVA Tamil, and hide TVA rows that are still unreadable (hidden, not "
        "deleted). Re-run import_wiktionary separately for senses, registers, forms and sense relations."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")

    def handle(self, dry_run=False, **opts):
        with transaction.atomic():
            domains = self.domains(dry_run)
            ocr = self.ocr(dry_run)
            attested = self.attestations()
            if dry_run:
                transaction.set_rollback(True)
        self.stdout.write(f"domain set on {sum(domains.values())} rows: {dict(domains.most_common())}")
        self.stdout.write(f"TVA OCR: {dict(ocr)}")
        self.stdout.write(f"attestations created for {attested} suggestions from their own source")
        if dry_run:
            self.stdout.write("dry run: nothing written")

    def domains(self, dry_run):
        out = Counter()
        sources = Suggestion.objects.filter(domain="").values_list("source", flat=True).distinct()
        for src in list(sources):
            slug = for_source(src)
            if slug:
                out[slug] += Suggestion.objects.filter(source=src, domain="").update(domain=slug)
        return out

    def attestations(self):
        """Every suggestion's own source becomes an attestation, even if an import already added others."""
        own = Attestation.objects.filter(suggestion=OuterRef("pk"), source=OuterRef("source"))
        todo = Suggestion.objects.exclude(source="").filter(~Exists(own)) | Suggestion.objects.filter(
            source="", attestations__isnull=True)
        todo = todo.values(
            "id", "source", "source_kind", "source_url", "source_ref", "license", "sense", "domain", "register", "note"
        )
        rows = [
            Attestation(
                suggestion_id=s.pop("id"), **{**s, "source": (s["source"] or s["source_kind"])[:200]}
            )
            for s in todo.iterator()
        ]
        Attestation.objects.bulk_create(rows, ignore_conflicts=True, batch_size=2000)
        return len(rows)

    def ocr(self, dry_run):
        out = Counter()
        rows = Suggestion.objects.filter(source__startswith=TVA, hidden=False).only("id", "term_id", "tamil", "region")
        for s in rows.iterator():
            fixed = fix_tamil(s.tamil)
            if tamil_problem(fixed):
                out["hidden: still unreadable"] += 1
                Suggestion.objects.filter(pk=s.pk).update(hidden=True)
            elif fixed != s.tamil:
                twin = Suggestion.objects.filter(term_id=s.term_id, tamil=fixed, region=s.region).exclude(pk=s.pk)
                if twin.exists():
                    out["hidden: duplicate of the repaired spelling"] += 1
                    Suggestion.objects.filter(pk=s.pk).update(hidden=True)
                else:
                    out["repaired"] += 1
                    Suggestion.objects.filter(pk=s.pk).update(tamil=fixed)
        return out
