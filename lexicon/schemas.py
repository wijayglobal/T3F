"""Pydantic validation for scraped mydictionary.in entries (scripts/scrape_mydictionary.py).

Two layers:
  ScrapedEntry   one line of data_raw/mydictionary/mydictionary.jsonl, cleaned and checked.
  SuggestionIn   one Term -> Tamil rendering, shaped to the DB columns it will be stored in,
                 so a bulk insert never fails on length, licence or emptiness.

ScrapedEntry.renderings() splits a meaning like "கணிப்பொறி; கணினி" into renderings, and
.suggestion() turns each into a SuggestionIn. validate_file() runs the whole file and tallies why rows were dropped.
No Django imports, so the scraper and notebooks can use it too.
"""
import json
import re
from enum import Enum
from pathlib import Path
from urllib.parse import unquote
from typing import Annotated, Iterator, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator

TAMIL = re.compile(r"[஀-௿]")
LATIN = re.compile(r"[A-Za-z]")
SPLIT = re.compile(r"\s*[;,]\s*")
# Vetri dictionary tags headwords like "antedate (verb transitive)(noun)"
POS = re.compile(
    r"\s*\(((?:noun|verb|adjective|adverb|pronoun|preposition|conjunction|interjection)s?"
    r"(?: (?:transitive|intransitive))?)\)\s*$", re.I,
)
POS_ABBR = {
    "noun": "n", "verb": "v", "verb transitive": "vt", "verb intransitive": "vi", "adjective": "adj",
    "adverb": "adv", "pronoun": "pron", "preposition": "prep", "conjunction": "conj", "interjection": "interj",
}
# Vetri meanings read "apart தள்ளி தனியாக": an English gloss, then the Tamil
GLOSS_THEN_TAMIL = re.compile(r"^([^஀-௿]*[A-Za-z][^஀-௿]*?)\s+([஀-௿][^A-Za-z]*)$")

# DB column limits (lexicon.models): Term.text 120, Suggestion.tamil 200, pos 30, source 200, source_url 500
TERM_MAX, TAMIL_MAX, POS_MAX, SOURCE_MAX, URL_MAX = 120, 200, 30, 200, 500


def clean(s: str) -> str:
    if "??" in s or "\ufffd" in s:
        raise ValueError("garbled text from the server ('??' where Tamil letters were)")
    s = s.replace("‌", "").replace("‍", "").replace("`", "")  # ZWNJ / ZWJ / stray backticks
    s = re.sub(r"\s*,\*,?\s*$|\s*\*,\s*$", "", s)  # trailing ",*," marker from the source
    return re.sub(r"\s+", " ", s).strip(" ,;")


Text = Annotated[str, AfterValidator(clean)]


class Licence(str, Enum):
    CC_BY_SA = "CC BY-SA"
    CC_BY_SA_4 = "CC BY-SA 4.0"
    CC0 = "CC0 1.0"


def parse_licence(raw: str) -> Licence:
    s = re.sub(r"[\s-]+", " ", raw.upper()).strip()
    if s.startswith("CC0"):
        return Licence.CC0
    if s.startswith("CC BY SA"):
        return Licence.CC_BY_SA_4 if "4.0" in s else Licence.CC_BY_SA
    raise ValueError(f"unknown licence {raw!r}")


class Direction(str, Enum):
    EN_TA = "en-ta"  # English headword, Tamil meaning: what the app's Term/Suggestion stores
    TA_TA = "ta-ta"  # Tamil headword with a Tamil definition (Sangam / Siddha dictionaries)
    OTHER = "other"


class SuggestionIn(BaseModel):
    """One row for lexicon.Suggestion (plus its Term), constrained like the DB columns."""

    model_config = ConfigDict(frozen=True)

    term: str = Field(min_length=1, max_length=TERM_MAX, pattern=r"^[^A-Z]*$")  # lower-cased
    tamil: str = Field(min_length=1, max_length=TAMIL_MAX)
    pos: str = Field("", max_length=POS_MAX)
    note: str = ""
    source: str = Field(max_length=SOURCE_MAX)
    source_url: str = Field(max_length=URL_MAX, pattern=r"^https?://mydictionary\.in/")  # readable, not %-encoded
    license: Licence
    source_kind: Literal["book"] = "book"
    status: Literal["draft"] = "draft"  # public but flagged as unreviewed

    @field_validator("tamil")
    @classmethod
    def tamil_script(cls, v: str) -> str:
        if not TAMIL.search(v) or len(LATIN.findall(v)) > 2:  # one letter can be a word: ஆ (cow)
            raise ValueError("rendering is not Tamil")
        return v

    def key(self) -> tuple:
        """Matches the DB uniqueness rule (term, tamil, region=common)."""
        return self.term, self.tamil


class ScrapedEntry(BaseModel):
    """One line of mydictionary.jsonl."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    term: Text = Field(min_length=1)
    term_note: Text = ""
    meaning: Text = Field(min_length=1)
    meaning_note: Text = ""
    dictionary: Text = Field(min_length=1)
    dictionary_en: Text = ""
    dictionary_url: HttpUrl
    license: Licence

    @field_validator("license", mode="before")
    @classmethod
    def _licence(cls, v):
        return parse_licence(v) if isinstance(v, str) else v

    @field_validator("dictionary_url")
    @classmethod
    def _from_site(cls, v: HttpUrl) -> HttpUrl:
        if v.host != "mydictionary.in":
            raise ValueError("dictionary_url is not on mydictionary.in")
        return v

    @property
    def direction(self) -> Direction:
        en, ta = LATIN.search(self.term), TAMIL.search(self.term)
        if en and not ta and TAMIL.search(self.meaning):
            return Direction.EN_TA
        if ta and not en:
            return Direction.TA_TA
        return Direction.OTHER

    @property
    def headword(self) -> tuple[str, str]:
        """('antedate', 'vt, n') from 'antedate (verb transitive)(noun)'."""
        term, tags = self.term, []
        while m := POS.search(term):
            tag = POS_ABBR[re.sub(r"s$|s(?= )", "", m.group(1).lower())]
            if tag not in tags:
                tags.insert(0, tag)
            term = term[: m.start()]
        return term.strip(), ", ".join(tags)

    @property
    def truncated(self) -> bool:
        """The site itself cut some meanings off mid-bracket, e.g. 'delivery' ends in '('."""
        return self.meaning.count("(") > self.meaning.count(")")

    def renderings(self) -> Iterator[tuple[str, str]]:
        """(tamil, english gloss) per ;/,-separated part of the meaning."""
        for part in SPLIT.split(self.meaning):
            part = part.strip(" .()")
            m = GLOSS_THEN_TAMIL.match(part)
            if m:
                yield m.group(2).strip(), m.group(1).strip()
            elif part:
                yield part, ""

    def suggestion(self, tamil: str, gloss: str = "") -> SuggestionIn:
        """Raises ValidationError if this rendering would not fit the DB."""
        term, pos = self.headword
        return SuggestionIn(
            term=term.lower(), tamil=tamil, pos=pos,
            note="; ".join(n for n in (gloss, self.term_note, self.meaning_note) if n),
            source=self.dictionary, source_url=unquote(str(self.dictionary_url)), license=self.license,
        )


class Report(BaseModel):
    lines: int = 0
    entries: int = 0  # passed ScrapedEntry
    by_direction: dict[str, int] = Field(default_factory=dict)
    truncated: int = 0
    suggestions: int = 0  # unique SuggestionIn produced (en-ta only)
    rejected: dict[str, int] = Field(default_factory=dict)  # reason -> count
    examples: dict[str, str] = Field(default_factory=dict)  # reason -> first offending input


def _reason(err: ValidationError) -> str:
    e = err.errors()[0]
    return f"{'.'.join(map(str, e['loc'])) or 'row'}: {e['msg']}"


def validate_file(path: Path) -> tuple[list[SuggestionIn], Report]:
    rep, out, seen = Report(), [], set()

    def reject(reason, sample):
        rep.rejected[reason] = rep.rejected.get(reason, 0) + 1
        rep.examples.setdefault(reason, sample[:160])

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rep.lines += 1
        try:
            entry = ScrapedEntry.model_validate(json.loads(line))
        except ValidationError as e:
            reject(_reason(e), line)
            continue
        rep.entries += 1
        rep.by_direction[entry.direction.value] = rep.by_direction.get(entry.direction.value, 0) + 1
        rep.truncated += entry.truncated
        if entry.direction is not Direction.EN_TA:
            continue  # the app's Term is an English headword; ta-ta entries are kept in the jsonl
        for tamil, gloss in entry.renderings():
            try:
                s = entry.suggestion(tamil, gloss)
            except ValidationError as e:
                reject(_reason(e), f"{entry.term} → {tamil}")
                continue
            if s.key() not in seen:
                seen.add(s.key())
                out.append(s)
    rep.suggestions = len(out)
    return out, rep
