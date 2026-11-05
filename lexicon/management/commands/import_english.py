import re
from pathlib import Path

from django.core.management.base import BaseCommand

from lexicon.models import Relation, Term

WORD = re.compile(r"[a-z][a-z \-]*[a-z]|[ai]")


def norm(w):
    return re.sub(r"\s+", " ", w.replace("_", " ")).strip().lower()


class Command(BaseCommand):
    help = "Load English headwords from WordNet and a plain word list, with WordNet glosses and synonym/antonym links."

    def add_arguments(self, parser):
        parser.add_argument("--nltk-data", default="data_raw/nltk")
        parser.add_argument("--wordlist", default="/usr/share/dict/american-english")

    def handle(self, nltk_data, wordlist, **opts):
        import nltk

        nltk.data.path.insert(0, nltk_data)
        from nltk.corpus import wordnet as wn

        glosses, relations = {}, set()
        for syn in wn.all_synsets():
            names = [norm(l.name()) for l in syn.lemmas()]
            for n in names:
                glosses.setdefault(n, syn.definition()[:300])
            if len(names) <= 8:
                for a in names:
                    for b in names:
                        if a != b:
                            relations.add((a, b, Relation.SYNONYM))
            for l in syn.lemmas():
                for ant in l.antonyms():
                    relations.add((norm(l.name()), norm(ant.name()), Relation.ANTONYM))
        self.stdout.write(f"WordNet: {len(glosses)} lemmas, {len(relations)} relations")

        plain = set()
        for line in Path(wordlist).read_text(encoding="utf-8", errors="ignore").splitlines():
            w = line.strip()
            if w and w == w.lower() and WORD.fullmatch(w):  # drops proper nouns, possessives
                plain.add(w)
        self.stdout.write(f"Plain list: {len(plain)} words")

        keep = {w for w in glosses if WORD.fullmatch(w)} | plain
        existing = set(Term.objects.values_list("text", flat=True))
        Term.objects.bulk_create(
            [Term(text=w, gloss=glosses.get(w, "")) for w in sorted(keep - existing)],
            ignore_conflicts=True,
            batch_size=5000,
        )
        # fill glosses on terms that already existed
        todo = list(Term.objects.filter(gloss="", text__in=[w for w in existing if w in glosses]))
        for t in todo:
            t.gloss = glosses[t.text]
        Term.objects.bulk_update(todo, ["gloss"], batch_size=2000)

        Relation.objects.bulk_create(
            [Relation(word=a, other=b, kind=k) for a, b, k in relations if a in keep and b in keep],
            ignore_conflicts=True,
            batch_size=5000,
        )
        self.stdout.write(self.style.SUCCESS(f"{Term.objects.count()} terms total"))
