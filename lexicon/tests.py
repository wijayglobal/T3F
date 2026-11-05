import json
import tempfile
from io import StringIO
from pathlib import Path

import numpy as np
from django.core.management import call_command
from django.test import TestCase
from pydantic import ValidationError

from lexicon import search
from lexicon.models import SourceKind, Status, Suggestion, Term
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
