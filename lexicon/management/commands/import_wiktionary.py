import json
import re
from urllib.parse import quote

from django.core.management.base import BaseCommand

from lexicon.models import Relation, SourceKind, Status, Suggestion, Term

STRIP = re.compile(r"^(to|a|an|the)\s+", re.I)


def clean_gloss(g):
    g = re.sub(r"\([^)]*\)", "", g).strip().rstrip(".;,")
    g = STRIP.sub("", g).strip().lower()
    if not g or len(g) > 40 or len(g.split()) > 3:
        return None
    if not re.fullmatch(r"[a-z][a-z' \-]*", g):
        return None
    return g


class Command(BaseCommand):
    help = "Seed terms, suggestions and synonym/antonym relations from kaikki Wiktionary JSONL."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default="data_raw/tamil.jsonl")

    def handle(self, path, **opts):
        terms, suggestions, relations = {}, {}, set()
        with open(path, encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                word = e.get("word")
                if not word or word.startswith("-"):
                    continue
                roman = next(
                    (x["form"] for x in e.get("forms", []) if "romanization" in x.get("tags", [])), ""
                )
                pos = e.get("pos", "")
                for s in e.get("senses", []):
                    tags = set(s.get("tags", []))
                    if tags & {"form-of", "alt-of"}:
                        continue
                    for g in s.get("glosses", [])[:1]:
                        c = clean_gloss(g)
                        if c:
                            terms.setdefault(c, None)
                            suggestions.setdefault((c, word), (roman, pos))
                    for kind, key in (("syn", "synonyms"), ("ant", "antonyms")):
                        for r in s.get(key, []) + e.get(key, []):
                            if r.get("word") and r["word"] != word:
                                relations.add((word, r["word"], kind))
                                if kind == "syn":
                                    relations.add((r["word"], word, kind))

        Term.objects.bulk_create([Term(text=t) for t in terms], ignore_conflicts=True, batch_size=2000)
        tid = dict(Term.objects.values_list("text", "id"))
        Suggestion.objects.bulk_create(
            [
                Suggestion(
                    term_id=tid[t], tamil=w, roman=r, pos=p, source="Wiktionary (CC BY-SA)",
                    source_kind=SourceKind.WIKTIONARY, status=Status.APPROVED, license="CC BY-SA 4.0",
                    source_url=f"https://en.wiktionary.org/wiki/{quote(w)}#Tamil",
                )
                for (t, w), (r, p) in suggestions.items()
            ],
            update_conflicts=True,
            unique_fields=["term", "tamil", "region"],
            update_fields=["source", "source_kind", "source_url", "status", "license"],
            batch_size=2000,
        )
        Relation.objects.bulk_create(
            [Relation(word=a, other=b, kind=k) for a, b, k in relations],
            ignore_conflicts=True,
            batch_size=2000,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(terms)} terms, {len(suggestions)} suggestions, {len(relations)} relations"
            )
        )
