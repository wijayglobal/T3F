"""Subject (domain) slugs for suggestions, from lexicon/domains.json. No Django imports."""
import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).with_name("domains.json")


@lru_cache(maxsize=1)
def _table():
    return json.loads(PATH.read_text(encoding="utf-8"))


def for_source(*names):
    """Slug for the first of `names` (book name in Tamil or English, a source label) that is known."""
    by_source = _table()["by_source"]
    for n in names:
        if n and n.strip() in by_source:
            return by_source[n.strip()]
    return ""


def for_topics(topics):
    """Slug for a Wiktionary sense's topics, e.g. ["cooking", "food", "lifestyle"] -> "food"."""
    table = _table()["wiktionary_topics"]
    return next((table[t] for t in topics or () if t in table), "")
