from django.core.management.base import BaseCommand

from lexicon.models import Term
from lexicon.search import embed


class Command(BaseCommand):
    help = "Embed English terms (multilingual MiniLM) for vector search."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Re-embed every term")

    def handle(self, all=False, **opts):
        qs = Term.objects.all() if all else Term.objects.filter(embedding=None)
        terms = list(qs)
        self.stdout.write(f"embedding {len(terms)} terms")
        for i in range(0, len(terms), 256):
            chunk = terms[i : i + 256]
            vecs = embed([t.text for t in chunk])
            for t, v in zip(chunk, vecs):
                t.embedding = v.tobytes()
            Term.objects.bulk_update(chunk, ["embedding"])
            self.stdout.write(f"  {min(i + 256, len(terms))}/{len(terms)}")
