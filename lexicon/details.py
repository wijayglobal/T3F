"""Per-source detail for the renderings shown on a page.

For each suggestion on `term.sugs` this attaches:
  s.sources        every source vouching for it (Attestation rows), each with its own sense, subject, register
  s.related        {"syn": [...], "ant": [...], "rel": [...]} for this meaning
  s.related_scope  "sense" when the related words were listed under this meaning by the source,
                   "word" when they come from the word-level graph (may mix meanings)
  s.other_meanings other senses of the same Tamil word (TamilSense), excluding the one shown here
"""
import re
from collections import defaultdict

from .models import Attestation, Register, Relation, SourceKind, Status, SuggestionRelation, TamilSense

MAX_RELATED, MAX_MEANINGS = 8, 4
WORDS = re.compile(r"[a-z]+")


def _same_meaning(gloss, senses):
    g = set(WORDS.findall(gloss.lower()))
    return any(g and g == set(WORDS.findall(s.lower())) for s in senses if s)


def enrich(terms):
    sugs = [s for t in terms for s in getattr(t, "sugs", [])]
    if not sugs:
        return terms
    ids = [s.id for s in sugs]
    words = {s.tamil for s in sugs}

    sources = defaultdict(list)
    for a in Attestation.objects.filter(suggestion_id__in=ids).order_by("source_kind", "source"):
        sources[a.suggestion_id].append(a)

    sense_rel = defaultdict(lambda: {"syn": [], "ant": [], "rel": []})
    for r in SuggestionRelation.objects.filter(suggestion_id__in=ids).order_by("kind", "word"):
        sense_rel[r.suggestion_id][r.kind].append(r.word)

    word_rel = defaultdict(lambda: {"syn": [], "ant": [], "rel": []})
    for r in Relation.objects.filter(word__in=words).order_by("other"):
        word_rel[r.word][r.kind].append(r.other)

    meanings = defaultdict(list)
    for m in TamilSense.objects.filter(word__in=words):
        meanings[m.word].append(m)

    for s in sugs:
        s.sources = sources.get(s.id) or [_own_source(s)]
        # Wiktionary lists related words per meaning; when it vouches for this rendering its list is
        # authoritative, even when empty, so the word-level graph (other meanings) is not shown.
        per_sense = s.id in sense_rel or any(a.source_kind == SourceKind.WIKTIONARY for a in s.sources)
        rel = sense_rel[s.id] if per_sense else word_rel.get(s.tamil, {"syn": [], "ant": [], "rel": []})
        s.related = {k: v[:MAX_RELATED] for k, v in rel.items() if v}
        s.related_scope = "sense" if per_sense else "word"
        shown = [a.sense for a in s.sources] + [s.sense]
        s.other_meanings = [m for m in meanings.get(s.tamil, []) if not _same_meaning(m.gloss, shown)][:MAX_MEANINGS]
    for t in terms:
        t.sugs.sort(key=_order)
    return terms


MARKED = {Register.OBSOLETE: 3, Register.ARCHAIC: 3, Register.DATED: 2, Register.RARE: 2}


def _order(s):
    """The viewer's pending words first, then reviewed before drafts, people before machines,
    unmarked words before obsolete / rare ones, best rated, most sources."""
    marked = min((MARKED.get(a.register, 0) for a in s.sources), default=0)
    return (
        s.status != Status.PENDING, s.status == Status.DRAFT, s.source_kind == SourceKind.MACHINE,
        marked, -s.rating_avg, -len(s.sources), -s.rating_count, s.tamil,
    )


def _own_source(s):
    """A suggestion created before attestations existed: its own source fields, unsaved."""
    return Attestation(
        suggestion=s, source=s.source, source_kind=s.source_kind, source_url=s.source_url,
        source_ref=s.source_ref, license=s.license, sense=s.sense, domain=s.domain, register=s.register,
    )


def tamil_words_meaning(query, limit=12, exclude=()):
    """Tamil words whose stated meaning mentions an English word: "yellow" -> பண்டாரம் ("a yellow
    powder…"), மஞ்சட்காமாலை ("jaundice … yellowness of the eyes"). Matches at a word start only,
    so "yellow" doesn't find "fellow"; meanings that start with the query come first."""
    q = query.strip().lower()
    if not q or not WORDS.fullmatch(q.replace(" ", "a")):
        return []
    whole = re.compile(rf"\b{re.escape(q)}")  # word start: yellow, yellowish, yellowness
    rows = TamilSense.objects.filter(gloss_lang="en", gloss__icontains=q).order_by("word", "position")[:400]
    hits = [m for m in rows if whole.search(m.gloss.lower())] or list(rows)
    hits.sort(key=lambda m: (not m.gloss.lower().startswith(q), len(m.gloss)))
    seen, out = set(), []
    for m in hits:
        if m.word not in seen and m.word not in exclude:
            seen.add(m.word)
            out.append(m)
    return out[:limit]
