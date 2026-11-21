import json
import tempfile
from io import StringIO
from pathlib import Path

import numpy as np
from django.core.management import call_command
from django.test import TestCase
from pydantic import ValidationError

from lexicon import search
from lexicon import ocr
from lexicon.domains import for_source, for_topics
from lexicon.management.commands.import_wiktionary import gloss_terms
from lexicon.models import (
    Register, Relation, SourceKind, Status, Suggestion, SuggestionRelation, TamilForm, TamilSense, Term,
)
from lexicon.schemas import Direction, Licence, ScrapedEntry, validate_file

ROW = {
    "term": "computer", "term_note": "computer science", "meaning": "கணிப்பொறி; கணினி,*,",
    "meaning_note": "கணிப்பொறி அறிவியல்", "dictionary": "அருங்கலைச்சொல் அகரமுதலி (2002)",
    "dictionary_en": "Dictionary of Technical Terms (2002)",
    "dictionary_url": "https://mydictionary.in/-அருங்கலைச்சொல்-அகரமுதலி-", "license": "CC-BY-SA",
}


def entry(**kw):
    return ScrapedEntry.model_validate({**ROW, **kw})


class ScrapedEntryTests(TestCase):
    def test_cleans_and_splits_meaning(self):
        e = entry()
        self.assertEqual(e.meaning, "கணிப்பொறி; கணினி")  # ',*,' marker dropped
        self.assertEqual(e.license, Licence.CC_BY_SA)
        self.assertEqual(e.direction, Direction.EN_TA)
        sugs = [e.suggestion(ta, gloss) for ta, gloss in e.renderings()]
        self.assertEqual([s.tamil for s in sugs], ["கணிப்பொறி", "கணினி"])
        self.assertEqual(sugs[0].note, "computer science; கணிப்பொறி அறிவியல்")
        self.assertEqual(sugs[0].source_url, "https://mydictionary.in/-அருங்கலைச்சொல்-அகரமுதலி-")

    def test_licences(self):
        self.assertEqual(entry(license="CC0 1.0 Universal Public Domain Dedication license").license, Licence.CC0)
        self.assertEqual(entry(license="CC-BY-SA 4.0").license, Licence.CC_BY_SA_4)
        with self.assertRaises(ValidationError):
            entry(license="")

    def test_rejects_garbled_empty_and_foreign_rows(self):
        for bad in (
            {"meaning": "கவனக்குறைவ??ன"}, {"meaning": ""}, {"term": ""},
            {"dictionary_url": "https://example.com/x"}, {"extra": 1},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                entry(**bad)

    def test_vetri_gloss_and_part_of_speech(self):
        e = entry(term="antedate (verb transitive)(noun)", meaning="to put a date earlier முற்படத் தேதி குறி")
        ((tamil, gloss),) = e.renderings()
        s = e.suggestion(tamil, gloss)
        self.assertEqual((s.term, s.pos, s.tamil), ("antedate", "vt, n", "முற்படத் தேதி குறி"))
        self.assertTrue(s.note.startswith("to put a date earlier"))

    def test_rendering_rules(self):
        self.assertEqual(entry(term="cow", meaning="ஆ").suggestion("ஆ").tamil, "ஆ")  # one-letter word
        with self.assertRaises(ValidationError):
            entry().suggestion("0001")
        with self.assertRaises(ValidationError):
            entry().suggestion("க" * 201)

    def test_direction(self):
        self.assertEqual(entry(term="அகம்", meaning="உள்ளே").direction, Direction.TA_TA)
        self.assertEqual(entry(meaning="Not equivalent").direction, Direction.OTHER)


class ImportTests(TestCase):
    def write(self, rows):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
        f.close()
        self.addCleanup(Path(f.name).unlink)
        return f.name

    def test_validate_file_reports_rejects(self):
        _, rep = validate_file(self.write([ROW, {**ROW, "meaning": ""}, {**ROW, "license": ""}]))
        self.assertEqual((rep.lines, rep.entries, rep.suggestions), (3, 1, 2))
        self.assertEqual(sum(rep.rejected.values()), 2)

    def test_import_is_idempotent_and_keeps_existing_pairs(self):
        mine = Suggestion.objects.create(
            term=Term.objects.create(text="computer"), tamil="கணினி", source="a user",
            source_kind=SourceKind.SELF, status=Status.APPROVED,
        )
        path = self.write([ROW])
        call_command("import_mydictionary", path, stdout=StringIO())
        call_command("import_mydictionary", path, stdout=StringIO())

        self.assertEqual(Term.objects.count(), 1)
        new = Suggestion.objects.get(tamil="கணிப்பொறி")
        self.assertEqual((new.status, new.license, new.source_kind), (Status.DRAFT, "CC BY-SA", SourceKind.BOOK))
        mine.refresh_from_db()
        self.assertEqual((mine.source, mine.status), ("a user", Status.APPROVED))
        self.assertEqual(Suggestion.objects.count(), 2)

    def test_dry_run_writes_nothing(self):
        call_command("import_mydictionary", self.write([ROW]), "--dry-run", stdout=StringIO())
        self.assertFalse(Term.objects.exists())


    def test_domain_sense_and_tamil_definitions(self):
        vetri = {**ROW, "term": "apart", "meaning": "apart தள்ளி", "dictionary": "வெற்றி அகராதி (1995)",
                 "dictionary_en": "Vetri Dictionary (1995)"}
        sangam = {**ROW, "term": "அகவல்", "meaning": "ஆசிரியப்பா", "dictionary": "தொல்காப்பிய அகராதி (2004)",
                  "dictionary_en": "Dictionary of Tholkapiyam (2004)"}
        call_command("import_mydictionary", self.write([ROW, vetri, sangam]), stdout=StringIO())
        self.assertEqual(Suggestion.objects.get(tamil="கணினி").domain, "science-technology")
        s = Suggestion.objects.get(tamil="தள்ளி")
        self.assertEqual((s.sense, s.domain), ("apart", "general"))
        t = TamilSense.objects.get(word="அகவல்")
        self.assertEqual((t.gloss, t.gloss_lang, t.domain), ("ஆசிரியப்பா; கணிப்பொறி அறிவியல்", "ta", "literature"))


WIKT = [
    {"word": "அரன்", "pos": "noun", "forms": [{"form": "araṉ", "tags": ["romanization"]}],
     "senses": [
         {"id": "s1", "glosses": ["Shiva"], "synonyms": [{"word": "சிவன்"}, {"word": "ஈசன்"}]},
         {"id": "s2", "glosses": ["yellow"], "tags": ["obsolete"], "synonyms": [{"word": "மஞ்சள்"}]},
     ]},
    {"word": "மஞ்சள்", "pos": "noun",
     "forms": [{"form": "mañcaḷ", "tags": ["romanization"]},
               {"form": "மஞ்சளை", "tags": ["accusative", "singular"]},
               {"form": "no-table-tags", "tags": ["table-tags"]}],
     "senses": [
         {"id": "m1", "glosses": ["yellow (colour)"]},
         {"id": "m2", "glosses": ["turmeric (the pulverized rhizome of the turmeric plant)"],
          "topics": ["cooking", "food"],
          "examples": [{"text": "மஞ்சள் தூள்", "english": "turmeric powder"}]},
     ]},
    {"word": "பிங்கலம்", "pos": "noun", "senses": [{"id": "p1", "glosses": ["gold (colour), yellow"]}]},
    {"word": "பண்டாரம்", "pos": "noun",
     "senses": [{"id": "b1", "glosses": ["a yellow powder kept in a little box by the priests of village deities"]}]},
]


class AttestationTests(TestCase):
    def write(self, rows, name="x.jsonl"):
        return ImportTests.write(self, rows)

    def test_same_pair_from_several_sources_keeps_each_source(self):
        medicine = {**ROW, "dictionary": "கலைச்சொல் பேரகராதி தொகுதி 11 மருத்துவம் (2011)",
                    "dictionary_en": "Lexicon of Terminologies, Volume 11, Medicine (2011)"}
        call_command("import_mydictionary", self.write([ROW, medicine]), stdout=StringIO())
        call_command("import_mydictionary", self.write([ROW, medicine]), stdout=StringIO())
        s = Suggestion.objects.get(tamil="கணினி")
        self.assertEqual(Suggestion.objects.filter(tamil="கணினி").count(), 1)
        self.assertEqual(sorted(s.attestations.values_list("domain", flat=True)), ["medicine", "science-technology"])

    def test_wiktionary_confirms_a_draft_without_taking_it_over(self):
        draft = Suggestion.objects.create(term=Term.objects.create(text="yellow"), tamil="மஞ்சள்",
                                          source="TVA · அறிவியல் கலைச்சொல் களஞ்சியம் (OCR)",
                                          source_kind=SourceKind.BOOK, status=Status.DRAFT)
        call_command("backfill_lexicon", stdout=StringIO())
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        f.write(json.dumps(WIKT[1], ensure_ascii=False))
        f.close()
        self.addCleanup(Path(f.name).unlink)
        call_command("import_wiktionary", f.name, stdout=StringIO())
        draft.refresh_from_db()
        self.assertEqual((draft.status, draft.source_kind, draft.roman), (Status.APPROVED, SourceKind.BOOK, "mañcaḷ"))
        self.assertEqual(set(draft.attestations.values_list("source_kind", "sense")),
                         {("book", ""), ("wiktionary", "yellow (colour)")})


class WiktionaryImportTests(TestCase):
    def setUp(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in WIKT))
        f.close()
        self.addCleanup(Path(f.name).unlink)
        call_command("import_wiktionary", f.name, stdout=StringIO())
        call_command("import_wiktionary", f.name, stdout=StringIO())  # idempotent

    def renderings(self, term):
        return set(Suggestion.objects.filter(term__text=term).values_list("tamil", flat=True))

    def test_every_word_for_yellow_with_its_own_sense(self):
        self.assertEqual(self.renderings("yellow"), {"அரன்", "மஞ்சள்", "பிங்கலம்"})  # comma gloss split
        self.assertEqual(self.renderings("turmeric"), {"மஞ்சள்"})  # second meaning kept
        aran = Suggestion.objects.get(term__text="yellow", tamil="அரன்")
        self.assertEqual((aran.sense, aran.register), ("yellow", Register.OBSOLETE))
        self.assertEqual(Suggestion.objects.get(term__text="turmeric").domain, "food")

    def test_related_words_follow_the_sense(self):
        aran = Suggestion.objects.get(term__text="yellow", tamil="அரன்")
        self.assertEqual(set(aran.sense_relations.values_list("word", "kind")), {("மஞ்சள்", "syn")})
        # the word-level table still has every synonym, Shiva's included
        self.assertTrue(Relation.objects.filter(word="அரன்", other="சிவன்").exists())

    def test_all_senses_and_forms_are_kept(self):
        self.assertEqual(list(TamilSense.objects.filter(word="மஞ்சள்").values_list("ref", flat=True)), ["m1", "m2"])
        self.assertEqual(TamilSense.objects.get(ref="m2").example, "மஞ்சள் தூள் — turmeric powder")
        # a description, not a headword: no Term, but still a findable sense mentioning yellow
        self.assertFalse(Suggestion.objects.filter(tamil="பண்டாரம்").exists())
        self.assertTrue(TamilSense.objects.filter(word="பண்டாரம்", gloss__icontains="yellow").exists())
        self.assertEqual(list(TamilForm.objects.values_list("form", "lemma", "tags")),
                         [("மஞ்சளை", "மஞ்சள்", "accusative, singular")])

    def test_gloss_terms(self):
        self.assertEqual(gloss_terms("yellow, brown, tawny, fawn colour"), ["yellow", "brown", "tawny", "fawn colour"])
        self.assertEqual(gloss_terms("to strike; to beat"), ["strike", "beat"])
        self.assertEqual(gloss_terms("a yellow powder kept in a little box by the priests"), [])


class PageTests(TestCase):
    """Search and term pages show every rendering with each of its sources, sense-level related
    words, other meanings, and Tamil words whose meaning mentions the query."""

    def setUp(self):
        WiktionaryImportTests.setUp(self)
        search._index.update(ids=None, mat=None, count=-1, checked=0.0)
        book = Suggestion.objects.create(
            term=Term.objects.get(text="yellow"), tamil="பொன்மஞ்சள்", source="கலைச்சொல் பேரகராதி, தொகுதி 9, மனையியல் (2010)",
            source_kind=SourceKind.BOOK, status=Status.DRAFT, sense="golden yellow", domain="home-science")
        call_command("backfill_lexicon", stdout=StringIO())
        self.book = book

    def test_yellow_shows_every_word_with_its_sources(self):
        html = self.client.get("/search/", {"q": "yellow"}).content.decode()
        for word in ("மஞ்சள்", "அரன்", "பிங்கலம்", "பொன்மஞ்சள்"):
            self.assertIn(word, html)
        self.assertIn("“gold (colour), yellow”", html)  # Wiktionary's own wording
        self.assertIn("Home science", html)  # the book's subject
        self.assertIn("வழக்கொழிந்தது · Obsolete", html)  # அரன் is marked obsolete
        self.assertIn("turmeric", html)  # மஞ்சள்'s other meaning
        self.assertNotIn("சிவன்", html)  # Shiva: another meaning of அரன், not related to yellow
        self.assertIn("பண்டாரம்", html)  # its meaning mentions yellow

    def test_inflected_tamil_finds_headword(self):
        html = self.client.get("/search/", {"q": "மஞ்சளை"}).content.decode()
        self.assertIn(f'href="/term/{Term.objects.get(text="yellow").id}/"', html)
        self.assertIn("meanings of the Tamil word", html)

    def test_term_page(self):
        r = self.client.get(f"/term/{Term.objects.get(text='yellow').id}/")
        self.assertContains(r, "Sources (1)")
        self.assertContains(r, "golden yellow")


class DomainAndOcrTests(TestCase):
    def test_domains(self):
        self.assertEqual(for_source("", "Lexicon of Terminologies, Volume 2, Fisheries (2009)"), "fisheries")
        self.assertEqual(for_source("unknown book"), "")
        self.assertEqual(for_topics(["lifestyle", "pathology"]), "medicine")

    def test_ocr_repair(self):
        self.assertEqual(ocr.fix_tamil("காற்றுச் ௪மிழ்"), "காற்றுச் சமிழ்")
        self.assertEqual(ocr.fix_tamil("உட்கவா்தல்"), "உட்கவர்தல்")
        self.assertEqual(ocr.fix_tamil("௧௨"), "௧௨")  # a real number stays
        self.assertTrue(ocr.tamil_problem(ocr.fix_tamil("உர4 1௨0 ஊடாாஃ")))
        self.assertTrue(ocr.english_problem("Acoustic filter 2 Alpha ray emission filter"))

    def test_tva_import_and_backfill(self):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
        rows = [{"en": "Absorption", "ta": "உட்கவா்தல்", "note": "", "page": 17},
                {"en": "Micrometer 081106", "ta": "நுண்ணளவி", "note": "", "page": 20},
                {"en": "Ledger paper", "ta": "உர4 1௨0", "note": "", "page": 20}]
        for name in ("tva_glossary.jsonl", "tva_kalanjiyam.jsonl"):
            Path(d, name).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        out = StringIO()
        call_command("import_tva", d, stdout=out)
        self.assertEqual(list(Suggestion.objects.values_list("tamil", "domain").distinct()),
                         [("உட்கவர்தல்", "science-technology")])
        self.assertIn("skipped", out.getvalue())

        old = Suggestion.objects.create(term=Term.objects.get(text="absorption"), tamil="உட்க௪ர்", region="kongu",
                                        source="TVA · அறிவியல் கலைச்சொல்லகராதி (OCR)", status=Status.DRAFT)
        Suggestion.objects.filter(pk=old.pk).update(domain="")
        call_command("backfill_lexicon", "--dry-run", stdout=StringIO())
        old.refresh_from_db()
        self.assertEqual((old.tamil, old.domain), ("உட்க௪ர்", ""))
        call_command("backfill_lexicon", stdout=StringIO())
        old.refresh_from_db()
        self.assertEqual((old.tamil, old.domain, old.hidden), ("உட்கசர்", "science-technology", False))


class SemanticIndexTests(TestCase):
    def setUp(self):
        search._index.update(ids=None, mat=None, count=-1, checked=0.0)
        self.addCleanup(search._index.update, ids=None, mat=None, count=-1, checked=0.0)
        for i, text in enumerate(["acid", "base", "salt"]):
            v = np.zeros(search.DIM, dtype=np.float32)
            v[i] = 1
            Term.objects.create(text=text, embedding=v.tobytes())

    def test_loads_once_then_skips_db_until_recheck(self):
        idx = search._load_index()
        self.assertEqual(idx["mat"].shape, (3, search.DIM))
        with self.assertNumQueries(0):
            search._load_index()

    def test_reloads_when_count_changes_after_recheck(self):
        search._load_index()
        Term.objects.create(text="ion", embedding=np.ones(search.DIM, dtype=np.float32).tobytes())
        search._index["checked"] -= search.INDEX_RECHECK_SECONDS
        self.assertEqual(len(search._load_index()["ids"]), 4)

    def test_top_k_in_score_order(self):
        search._load_index()
        q = np.zeros(search.DIM, dtype=np.float32)
        q[:2] = [0.6, 0.8]
        search.embed, real = (lambda texts: np.array([q])), search.embed
        try:
            hits = search.semantic_terms("x", limit=2, min_score=0.5)
        finally:
            search.embed = real
        self.assertEqual([Term.objects.get(id=i).text for i, _ in hits], ["base", "acid"])
