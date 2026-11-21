import json
import re
import unicodedata
from urllib.parse import quote

from django.core.management.base import BaseCommand
from django.db import transaction

from lexicon.domains import for_topics
from lexicon.importing import attest, suggestion_ids
from lexicon.models import (
    Attestation,
    Relation,
    SourceKind,
    Status,
    Suggestion,
    SuggestionRelation,
    TamilForm,
    TamilSense,
    Term,
)

SOURCE, LICENSE = "Wiktionary (CC BY-SA)", "CC BY-SA 4.0"
STRIP = re.compile(r"^(to|a|an|the)\s+", re.I)
TAMIL = re.compile(r"[஀-௿]")
# most marked first: a sense tagged both "rare" and "obsolete" counts as obsolete
REGISTERS = ["obsolete", "archaic", "dated", "rare", "literary", "formal", "colloquial"]
FORM_NOISE = {"romanization", "table-tags", "inflection-template", "error-unrecognized-form"}
BATCH = 2000


def clean_gloss(g):
    """One English headword from one gloss part, or None if the part is a description, not a word."""
    g = STRIP.sub("", g.strip().rstrip(".;,")).strip().lower()
    if not g or len(g) > 40 or len(g.split()) > 3:
        return None
    if not re.fullmatch(r"[a-z][a-z' \-]*", g):
        return None
    return g


def gloss_terms(g, limit=4):
    """English headwords in a gloss. "gold (colour), yellow" -> ["gold", "yellow"];
    "yellow, brown, tawny, fawn colour" -> all four; a sentence-length description -> []."""
    g = re.sub(r"\([^)]*\)", "", g)
    out = []
    for part in re.split(r"\s*[;,]\s*", g):
        c = clean_gloss(part)
        if c and c not in out:
            out.append(c)
    return out[:limit]


def register_of(tags):
    return next((r for r in REGISTERS if r in tags), "")


def first_example(sense):
    for ex in sense.get("examples", []):
        text = ex.get("text", "")
        meaning = ex.get("english") or ex.get("translation") or ""
        if text:
            return f"{text} — {meaning}" if meaning else text
    return ""


class Command(BaseCommand):
    help = (
        "Import kaikki Wiktionary JSONL: English terms with Tamil renderings (one per sense, with the "
        "sense's gloss, register, subject and its own synonyms), every sense of each Tamil word, "
        "synonym/antonym relations and inflected forms."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default="data_raw/tamil.jsonl")

    def handle(self, path, **opts):
        terms, suggestions, sense_rels, relations = {}, {}, {}, set()
        senses, forms = {}, {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                word = unicodedata.normalize("NFC", e.get("word") or "")
                if not word or word.startswith("-") or len(word) > 200:
                    continue
                roman = next(
                    (x["form"] for x in e.get("forms", []) if "romanization" in x.get("tags", [])), ""
                )[:200]
                pos = e.get("pos", "")[:30]
                url = f"https://en.wiktionary.org/wiki/{quote(word)}#Tamil"

                for x in e.get("forms", []):
                    form = unicodedata.normalize("NFC", x.get("form", ""))
                    if form != word and TAMIL.search(form) and len(form) <= 200:
                        tags = ", ".join(sorted(set(x.get("tags", [])) - FORM_NOISE))[:120]
                        forms.setdefault((form, word), tags)

                for i, s in enumerate(e.get("senses", [])):
                    glosses = s.get("glosses", [])
                    if not glosses:
                        continue
                    tags = set(s.get("tags", []))
                    register = register_of(tags)
                    domain = for_topics(s.get("topics"))
                    gloss = glosses[-1]  # the most specific gloss; glosses[0] is the parent sense
                    ref = (s.get("id") or f"{word}-{pos}-{e.get('etymology_number', 0)}-{i}")[:120]
                    senses.setdefault(ref, TamilSense(
                        word=word, pos=pos, gloss=gloss, register=register, domain=domain, roman=roman,
                        example=first_example(s), source=SOURCE, source_url=url, license=LICENSE,
                        ref=ref, position=i,
                    ))

                    sense_words = {
                        "syn": [r["word"] for r in s.get("synonyms", []) if r.get("word")],
                        "ant": [r["word"] for r in s.get("antonyms", []) if r.get("word")],
                        "rel": [r["word"] for r in s.get("related", []) + s.get("coordinate_terms", [])
                                if r.get("word")],
                    }
                    for kind in ("syn", "ant"):
                        for other in sense_words[kind] + [r["word"] for r in e.get(
                                {"syn": "synonyms", "ant": "antonyms"}[kind], []) if r.get("word")]:
                            if other != word:
                                relations.add((word, other, kind))
                                if kind == "syn":
                                    relations.add((other, word, kind))

                    if tags & {"form-of", "alt-of"}:
                        continue
                    for term in gloss_terms(gloss):
                        terms.setdefault(term, None)
                        key = (term, word)
                        if key not in suggestions:
                            suggestions[key] = dict(roman=roman, pos=pos, sense=gloss[:300],
                                                    register=register, domain=domain, url=url)
                        bucket = sense_rels.setdefault(key, set())
                        for kind, words in sense_words.items():
                            bucket.update((w[:200], kind) for w in words if w != word)

        with transaction.atomic():
            Term.objects.bulk_create([Term(text=t) for t in terms], ignore_conflicts=True, batch_size=BATCH)
            tid = dict(Term.objects.values_list("text", "id"))
            Suggestion.objects.bulk_create(
                [
                    Suggestion(
                        term_id=tid[t], tamil=w, roman=v["roman"], pos=v["pos"], sense=v["sense"],
                        register=v["register"], domain=v["domain"], source=SOURCE,
                        source_kind=SourceKind.WIKTIONARY, status=Status.APPROVED, license=LICENSE,
                        source_url=v["url"],
                    )
                    for (t, w), v in suggestions.items()
                ],
                # a pair another source already has keeps its row; Wiktionary is added as an attestation
                ignore_conflicts=True,
                batch_size=BATCH,
            )
            sid = suggestion_ids(suggestions, tid)
            ids = list(sid.values())
            by_id = {sid[k]: v for k, v in suggestions.items() if k in sid}
            for i in range(0, len(ids), 900):
                chunk = ids[i : i + 900]
                # a reviewed dictionary confirming an unreviewed draft makes it approved
                Suggestion.objects.filter(id__in=chunk, status=Status.DRAFT).update(status=Status.APPROVED)
                missing = list(Suggestion.objects.filter(id__in=chunk, roman=""))
                for s in missing:
                    s.roman = by_id[s.id]["roman"]
                Suggestion.objects.bulk_update(missing, ["roman"])
            attest([
                Attestation(
                    suggestion_id=sid[key], source=SOURCE, source_kind=SourceKind.WIKTIONARY,
                    source_url=v["url"], license=LICENSE, sense=v["sense"], domain=v["domain"],
                    register=v["register"],
                )
                for key, v in suggestions.items() if key in sid
            ])
            SuggestionRelation.objects.bulk_create(
                [
                    SuggestionRelation(suggestion_id=sid[key], word=w, kind=k)
                    for key, pairs in sense_rels.items() if key in sid
                    for w, k in pairs
                ],
                ignore_conflicts=True,
                batch_size=BATCH,
            )
            Relation.objects.bulk_create(
                [Relation(word=a[:200], other=b[:200], kind=k) for a, b, k in relations],
                ignore_conflicts=True,
                batch_size=BATCH,
            )
            TamilSense.objects.bulk_create(
                list(senses.values()),
                update_conflicts=True,
                unique_fields=["source", "ref"],
                update_fields=["word", "pos", "gloss", "register", "domain", "roman", "example", "position"],
                batch_size=BATCH,
            )
            TamilForm.objects.bulk_create(
                [TamilForm(form=f, lemma=lemma, tags=t) for (f, lemma), t in forms.items()],
                ignore_conflicts=True,
                batch_size=BATCH,
            )
        n_rel = sum(len(v) for v in sense_rels.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(terms)} terms, {len(suggestions)} suggestions ({n_rel} sense-level related words), "
                f"{len(relations)} relations, {len(senses)} Tamil senses, {len(forms)} inflected forms"
            )
        )
