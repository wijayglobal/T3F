# OpenSearch search index: data analysis, schema and evaluation

Files:

- `deploy/opensearch/kalaichol-terms.json`: main index (English headword → Tamil renderings), settings,
  analyzers, mapping
- `deploy/opensearch/kalaichol-tamil.json`: phase-2 index (Tamil headword → meanings), same analyzers
- `deploy/opensearch/hybrid-pipeline.json`: search pipeline that blends lexical and vector scores
- `lexicon/domains.json`: source dictionary / Wiktionary topic → search domain (used by the importers)

Postgres stays the source of truth. OpenSearch is a **derived, rebuildable read index**: it holds what search
matches, filters and ranks on, and returns ids. Pages are still rendered from Postgres.

---

## 1. The data

Two views: what is in the database now (local `db.sqlite3`, Nov 2026), and what is in `data_raw/` waiting to
be imported or currently being thrown away by the importers. The second is much bigger than the first.

### 1.1 Database today

| Table | Rows | Notes |
|---|---|---|
| `Term` | 219,925 | 159,830 (73%) have no Tamil. 86,881 multi-word. 182,500 embedded |
| `Suggestion` | 68,009 | Tamil Wikipedia titles 47,324 · Wiktionary 11,317 · TVA OCR 7,704 · NLLB 1,663. All `region = common`. 17% have `roman` |
| `Relation` | 311,894 syn + 7,291 ant | Keyed by Tamil string; 114,271 of its words match no suggestion |
| `Term.domain` | 0 filled | |

### 1.2 `data_raw/mydictionary/`: the largest source, mostly not imported yet

| File | Contents |
|---|---|
| `dictionaries.json` | 73 books, declaring **595,173 headwords** in total, each with a licence (CC BY-SA, a few CC0) |
| `mydictionary.jsonl` | 46,159 entries. **A stale export** (Nov 3): it was written before the scrape finished |
| `queries.jsonl` | The scraper's cache (Nov 19): 118,348 searches, 26,990 with no result, 678,030 result rows → **361,614 unique entries** (351,904 en→ta, 5,108 en→en, 2,457 ta→ta, 2,145 mixed) |

Running the cache through the project's own validator (`lexicon/schemas.py`, same rules as
`import_mydictionary`):

| | Count |
|---|---|
| Valid unique `(term, tamil)` renderings | **439,262**, 6.5× everything in the DB now |
| Distinct English terms | 196,539, of which 128,311 (65%) are multi-word |
| … already in `Term` | 49,502, and **35,417 of those currently have no Tamil and would get some** |
| … new terms | 147,037 |
| Renderings per term | 2.23 on average; *sound* 62, *scale* 61, *bank* 58 (one per subject dictionary) |
| With part of speech / with an English gloss note | 139,895 / 54,312 |
| Rejected | 6,193 renderings (not Tamil / too long), 3,070 empty, 519 garbled (`??`) |

`import_mydictionary` reads `mydictionary.jsonl`, so run `scripts/scrape_mydictionary.py --export-only`
first. Otherwise only about a tenth of the scraped data gets imported.

The 72 books in the results are domain-specific (Technical Terms 59k rows, English–Tamil 39k, Home Science
38k, Agriculture 23k, Administration 23k, Medicine 18k, Veterinary 16k, …). **The source book is the domain**:
`lexicon/domains.json` maps every one of them onto 36 domain slugs (physics, medicine, fisheries, law, computing,
literature, siddha, …). The same English word legitimately gets a different Tamil word per domain (*scale*
in music, fisheries and mathematics), so domain has to stay attached to each rendering, not just to the term.

Also in there:

- **en→en rows** (5,108), mostly *Dictionary of Abbreviations*: `V` → "Five (Roman numeral)", `N` → "North".
  These are aliases and expansions, useful as an English synonym field.
- **ta→ta rows** (2,457 entries, 2,269 headwords) from the Sangam and Siddha dictionaries. `schemas.py` keeps
  them in the jsonl but the app drops them.
- **The 26,990 searches with no result** are a ready-made list of English words no source covers yet.

After importing: about **367k terms**, about **507k renderings**, and about **242k terms (66%) with Tamil**,
up from 27%.

### 1.3 `data_raw/tamil.jsonl`: Wiktionary, mostly thrown away today

13,878 entries for 11,203 Tamil words, with 28,744 senses. `import_wiktionary` keeps the first English gloss
per sense (as the `Term`), the romanisation, and synonyms/antonyms. It drops:

| Dropped | Count | Search value |
|---|---|---|
| **Inflected forms** (case, number, tense, person tables) | **391,836 forms, 292,794 distinct Tamil strings**, up to 202 per word (`அடி` → `அடிக்கிறேன்`, `அடித்தான்`, …) | **High.** An exact map from an inflected query to its lemma, better than any n-gram trick |
| Register tags | colloquial 591, formal 558, literary 258, archaic 402, obsolete 442, rare 461 | Medium: filter or down-rank archaic forms. Maps onto `Region.FORMAL` / a register field |
| Topics | 1,476 senses (medicine 282, anatomy 207, linguistics 206, botany 106, …) | Medium: domain for Wiktionary rows (`lexicon/domains.json` → `wiktionary_topics`) |
| `derived` / `related` / coordinate terms | 8,730 / 3,432 / 640 | Low: "see also" |
| IPA, etymology, usage examples | 13,495 / 11,249 / 1,514 | Display only, so they belong in Postgres, not the index |
| Senses beyond the first gloss, `raw_glosses` | | The Tamil→English meaning of each word: the core of a Tamil-headword index |

### 1.4 `data_raw/tva_*.jsonl`: OCR'd science glossaries

| File | Rows | Problems |
|---|---|---|
| `tva_glossary.jsonl` | 6,422 (524 English heads repeated) | 97 Tamil cells with OCR damage. **Tamil digits read in place of letters**: `௪` for `ச`, `௫` for `ரு`, `௨` for `உ` (`காற்றுச் ௪மிழ்`). 172 English cells merged across columns (`Acoustic filter 2 Alpha ray emission filter`). Legacy-font `ா்` for `ர்` |
| `tva_kalanjiyam.jsonl` | 1,296 | 98 damaged Tamil cells (`உர4 1௨0 ஊடாாஃ…`). 24 English heads with digits (`Micrometer 081106`). 1,240 have a Tamil definition note (avg 229 chars), heavily garbled |

These are fixed **at import, per source**, not in the analyzer: map the digit look-alikes back inside words,
drop or flag rows whose English contains a digit run, and don't index the kalanjiyam notes. The analyzer only
does the normalisation that is right for every source (ZW chars, `ா்`, NFC).

### 1.5 What this means for the schema

1. **Domain-aware renderings.** 2.2 renderings per term on average and up to 62, each from a different subject
   book, means a rendering must carry its own domain, source and status. → `renderings` becomes `nested`.
2. **Inflection via Wiktionary forms**, not only n-grams: 293k inflected strings map exactly to a lemma.
3. **Generated romanisation for every rendering**: 83% of today's rows and all 439k mydictionary rows have none.
4. **Aliases** from the abbreviations dictionary as an English synonym field.
5. **Register** (colloquial, literary, archaic…) as a ranking and filter signal.
6. **Index every term**, including those without Tamil, ranked lower: people need to find a bare headword to
   suggest a word for it.
7. **A second, Tamil-headword index** now has real content (11k Wiktionary words with 28k English senses,
   2.3k ta→ta entries, 114k relation-only words). It goes in phase 2.

### 1.6 The target query: "yellow"

A search for an English word must return **every Tamil word for it, with each source's meaning and the
related words, grouped by source**. Before the data fixes, `yellow` gave 4 rows. Related words for
`அரன்` were about 60 names of Shiva, because synonyms were stored per word, not per meaning. After
migration `0009` and a re-import (checked on a copy of the local DB):

| Tamil | Source | Sense (source's wording) | Register | Related (this sense only) |
|---|---|---|---|---|
| மஞ்சள் | Wiktionary · TVA kalanjiyam (science) | yellow (colour) | | |
| மஞ்சன் | Wiktionary | yellow (color) | | |
| பிங்கலம் | Wiktionary | gold (colour), yellow | | |
| அரி | Wiktionary | yellow, brown, tawny, fawn colour | rare | |
| அரன் | Wiktionary | yellow | obsolete | மஞ்சள் |
| யெல்லோ | Tamil Wikipedia | | | |

Plus 51 "yellow …" phrase terms (yellow fever, yellow rust, yellow oleander, …), and 25 Tamil senses whose
meaning mentions yellow (`பண்டாரம்` "a yellow powder…", `மஞ்சட்காமாலை` "jaundice…", the second meaning
of `மஞ்சள்`, "turmeric"). *yellow fever* → மஞ்சள் காய்ச்சல் is now **one rendering with 6 sources** (medicine,
biology, veterinary ×2, home science, Wikipedia) instead of whichever book was imported last.

Storage that makes this possible (`lexicon/models.py`, migration `0009`):

| Model | Holds | Rows after import |
|---|---|---|
| `Suggestion` + `sense`, `domain`, `register` | one rendering, rated and reviewed once | about 526k |
| `Attestation` | one row per (rendering, source): source, URL/page, licence, that source's sense, domain, register, note | 41k renderings have 2+ sources |
| `SuggestionRelation` | synonyms / antonyms / related words **of the sense** that produced the rendering | 48.6k |
| `TamilSense` | every meaning of a Tamil headword (Wiktionary, English gloss; ta→ta books, Tamil gloss), with example | 30.8k |
| `TamilForm` | inflected form → headword | 289.7k |
| `Relation` (unchanged) | word-level synonym graph, kept for recall | |

The importers no longer overwrite each other. A pair that already exists keeps its row and gains an
attestation. Wiktionary confirming a draft promotes it to approved and fills a missing romanisation.

Run order on an existing database:

```bash
uv run python manage.py migrate
uv run python manage.py backfill_lexicon            # own source → attestation, domains, TVA OCR repair
uv run python manage.py import_wiktionary
uv run python manage.py import_tva
uv run python scripts/scrape_mydictionary.py data_raw/mydictionary --export-only   # 361k entries
uv run python manage.py import_mydictionary
uv run python manage.py build_embeddings            # about 147k new terms
```

## 2. Main index `kalaichol-terms`: one document per English term

`_id = term_id`. Only **public** renderings (`hidden = false AND status IN ('approved','draft')`) are
included, so visibility is enforced at index time.

```json
{
  "term_id": 48213,
  "text": "scale",
  "aliases": [],
  "gloss": ["an ordered reference standard", "a thin plate on fish skin"],
  "renderings": [
    { "suggestion_id": 9001, "tamil": "அளவுகோல்", "roman": ["aḷavukōl", "alavukol"],
      "forms": [], "domain": "mathematics", "source_kind": "book", "status": "draft",
      "register": null, "region": "common", "pos": "n", "rating": 0 },
    { "suggestion_id": 9002, "tamil": "செதில்", "roman": ["cetil"],
      "forms": ["செதில்கள்", "செதிலை", "செதிலுக்கு", "…"], "domain": "fisheries",
      "source_kind": "wiktionary", "status": "approved", "register": null, "region": "common",
      "pos": "n", "rating": 4.5 },
    { "suggestion_id": 9003, "tamil": "சுரவரிசை", "roman": ["curavaricai"], "forms": [],
      "domain": "arts", "source_kind": "book", "status": "draft", "region": "common", "pos": "n", "rating": 0 }
  ],
  "tamil_synonyms": ["செதிள்"],
  "has_tamil": true, "has_approved": true, "machine_only": false,
  "best_rating": 4.5, "rendering_count": 3, "source_count": 3,
  "domains": ["mathematics", "fisheries", "arts"],
  "source_kinds": ["book", "wiktionary"],
  "sources": ["Lexicon of Terminologies, Volume 1, Mathematics (2008)", "Wiktionary (CC BY-SA)", "…"],
  "licenses": ["CC BY-SA"],
  "registers": [],
  "pos": ["n"],
  "embedding": [0.0213, -0.0871, "… 384 floats …"],
  "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2@the-word-v1",
  "indexed_at": "2026-11-20T08:15:00Z"
}
```

How the indexer fills it:

| Field | From |
|---|---|
| `aliases` | en→en rows of *Dictionary of Abbreviations* (both directions: `RAM` ↔ "random access memory") |
| `gloss` | WordNet `Term.gloss` + the English gloss notes in mydictionary (`apart தள்ளி` → "apart") |
| `renderings[].roman` | stored `roman`, plus a generated ISO 15919 transliteration (`aksharamukha` / `indic-transliteration`) |
| `renderings[].forms` | Wiktionary `forms` for the rendering's lemma, when the rendering is a Wiktionary headword (Tamil strings only, capped at about 200) |
| `renderings[].domain` | `lexicon/domains.json`: source book → slug; Wiktionary topic → slug |
| `renderings[].register` | Wiktionary sense tags (colloquial / formal / literary / archaic / obsolete / rare) |
| `tamil_synonyms` | `Relation` syn for every rendering, capped at about 20 |
| root `domains`, `source_kinds`, … | de-duplicated from the renderings, for cheap facets and filters that don't need nesting |

### Field reference

| Field | Indexed as | Used for |
|---|---|---|
| `text` | `en_text` | multi-word match, fuzzy (`fuzziness: AUTO`) |
| `text.exact` | keyword, lowercase | exact headword, top boost |
| `text.prefix` | whole-phrase edge n-gram 1–20 | autocomplete, starts-with across spaces (65% of new terms are phrases) |
| `text.stem` | light English stemmer | plurals |
| `text.gram` | 3-grams | substring, lowest boost |
| `aliases` (+ `.exact`) | `en_text` / keyword | abbreviations and expansions |
| `gloss` | English stemmer | meaning words, low boost |
| `renderings.tamil` (+ `.exact`, `.prefix`, `.gram`) | `ta_text`: ZW strip, `ா்`→`ர்`, NFC | Tamil exact / prefix / inflected overlap |
| `renderings.forms` | keyword, same normalisation | inflected query → lemma, exact |
| `renderings.roman` (+ `.plain`) | `roman_key` / `en_text` | Tanglish |
| `renderings.domain`, `source_kind`, `status`, `register`, `region`, `pos`, `rating` | keyword / half_float | per-rendering filter and rank ("fisheries word for *scale*") |
| `tamil_synonyms` | `ta_text` + exact | recall via synonyms |
| `has_tamil`, `has_approved`, `machine_only`, `best_rating`, `source_count` | boolean / number | ranking |
| `domains`, `source_kinds`, `sources`, `licenses`, `registers`, `pos` | keyword | facets; licence-clean exports |
| `embedding` | `knn_vector` 384, HNSW lucene cosine, m=16, ef_construction=128 | meaning search |

**Left out on purpose:** notes, source URLs and refs, authors, reviews, IPA, etymology, examples. They are
display-only and live in Postgres. Leaving them out keeps documents small, and most edits then don't need a
reindex.

**Why `nested`:** with flattened arrays, "domain = fisheries AND Tamil matches செதில்" would also match a term
whose fisheries rendering is something else and whose maths rendering matched. With 2.2 renderings per term
and up to 62, that would happen constantly. Cost: about 507k hidden nested docs next to about 367k roots,
which is small. `inner_hits` also tells the UI *which* rendering matched.

### The `roman_key` analyzer

Tamil has no voiced/unvoiced or aspirated distinction, and Latin spellings vary. So the romanisation and the
query are reduced to the same lossy key: lower-case → strip diacritics → `th/dh/kh…`→`t/d/k` → `zh/z`→`l`
→ `sh/ch/s/j`→`c` → `g`→`k`, `d`→`t`, `b/f`→`p`, `w`→`v` → `ee`→`i`, `oo`→`u`, `ai/ay/ei`→`e` → drop `y`
glides → collapse doubled letters. Checked with a Python simulation of the chain:

| Inputs | Key |
|---|---|
| kanini, kaNini, kaṇiṉi, kaninee | `kanini` |
| cēvaiyakam, sevaiyagam, sevayakam | `ceveakam` |
| eḻuttu, ezhuthu, eluttu | `elutu` |
| tamiḻ, thamizh, tamil | `tamil` |
| muṭukkam, mudukkam, mudukam | `mutukam` |

`kaṭal`/`kaṭai` stay apart. `l/ḷ/ḻ` and `n/ṇ/ṉ` merge on purpose, and the exact boosts keep the precise hit
on top.

## 3. Query

The app embeds the query itself (fastembed is already loaded in every worker, and the `the word "…"`
wrapper must match indexing), then sends:

```json
POST kalaichol-terms/_search?search_pipeline=kalaichol-hybrid
{
  "size": 30,
  "_source": ["term_id"],
  "query": {
    "hybrid": {
      "queries": [
        {
          "function_score": {
            "query": {
              "bool": {
                "filter": [ /* optional: { "term": { "domains": "fisheries" } } */ ],
                "should": [
                  { "term":  { "text.exact":    { "value": "scale", "boost": 10 } } },
                  { "term":  { "aliases.exact": { "value": "scale", "boost": 8 } } },
                  { "match": { "text.prefix":   { "query": "scale", "boost": 4 } } },
                  { "match": { "text":          { "query": "scale", "fuzziness": "AUTO", "prefix_length": 1, "boost": 2 } } },
                  { "match": { "text.stem":     { "query": "scale", "boost": 1.5 } } },
                  { "match": { "gloss":         { "query": "scale", "boost": 0.5 } } },
                  { "match": { "text.gram":     { "query": "scale", "minimum_should_match": "75%", "boost": 0.3 } } },
                  { "nested": { "path": "renderings", "score_mode": "max",
                      "query": { "match": { "renderings.roman": { "query": "scale", "boost": 5 } } } } }
                ],
                "minimum_should_match": 1
              }
            },
            "functions": [
              { "filter": { "term": { "has_tamil": true } },    "weight": 1.5 },
              { "filter": { "term": { "has_approved": true } }, "weight": 1.2 },
              { "filter": { "term": { "machine_only": true } }, "weight": 0.8 },
              { "field_value_factor": { "field": "best_rating", "modifier": "log2p", "missing": 0 } },
              { "field_value_factor": { "field": "source_count", "modifier": "log2p", "missing": 0 } }
            ],
            "score_mode": "multiply",
            "boost_mode": "multiply"
          }
        },
        { "knn": { "embedding": { "vector": [0.01, "…384…"], "k": 12 } } }
      ]
    }
  }
}
```

- **Tamil-script query:** one `nested` clause on `renderings` with `should` on `tamil.exact` (10),
  `forms` (8, inflected → lemma), `tamil.prefix` (4) and `tamil.gram` (`minimum_should_match: 70%`, 1), and
  `inner_hits` for the matched rendering. Add `tamil_synonyms` (1.5) at the root. No kNN, because the model
  aligns Tamil poorly with English headwords.
- **Domain filter:** at the root (`domains`) for "terms in this domain". Inside the nested query
  (`renderings.domain`) when it must be *the matching rendering* that is in that domain.
- **Register:** `renderings.register` in `archaic`/`obsolete` gets weight 0.7.
- **The pipeline** (min-max, weights 0.75 / 0.25) replaces the hand-tuned `× 0.6` and the 0.7 cutoff. A hit
  is "related" when the lexical sub-query didn't match it (no highlight on `text`/`renderings`).
- **Autocomplete:** `text.prefix` + `renderings.tamil.prefix` + `renderings.roman`, `size: 8`, no kNN.
- **Relations** (`relations_for`) stay a Postgres lookup.
- **`source_count`** as a boost: a rendering agreed on by several independent books is a good confidence
  signal now that there are 72 of them.

## 4. Phase 2 index `kalaichol-tamil`: one document per Tamil headword

For Tamil → meaning lookups ("what does உட்கவர்தல் mean?"), which a term-centric index can't answer well.
Mapping in `kalaichol-tamil.json`, same analyzers, no vectors.

| Field | From |
|---|---|
| `headword` (+ exact / prefix / gram), `roman`, `forms` | Wiktionary word, romanisation, inflection forms |
| `senses_en` | all Wiktionary glosses (28,744 senses), not just the first |
| `definition_ta` | mydictionary ta→ta meanings (Sangam / Siddha dictionaries) |
| `synonyms`, `antonyms` | `Relation`, the 114k relation-only words included |
| `pos`, `registers`, `domains`, `sources` | Wiktionary tags / topics, book |
| `linked_term_ids` | English `Term`s this word is a rendering of, to jump across |

About 130k documents, mostly tiny. Build it once the main index works. The Tamil-script query then searches
both indexes (`kalaichol-terms,kalaichol-tamil`) and shows two result groups.

## 5. Keeping it in sync

```
Term / Suggestion / Rating change ──on_commit──► search_outbox (term_id PK, enqueued_at)   upsert, dedupes
                                                    │
manage.py search_sync (compose service, like telegram_poll), every 1 s, 500 ids
        ──► build docs from Postgres (one query + prefetch, domains.json, forms lookup)
        ──► _bulk index / delete ──► delete from outbox

import_* / ingest / machine_draft (bulk_create skips signals)
        ──► manage.py search_reindex: kalaichol-terms-<ts>, refresh_interval -1, replicas 0,
            bulk load, refresh, swap alias kalaichol-terms, drop old
```

- **Everything the index needs is in Postgres** (migration `0009`): `Suggestion.sense/domain/register`,
  `Attestation` (per-source sense, domain, page), `SuggestionRelation`, `TamilSense`, `TamilForm`. A reindex is
  a pure read. Each nested rendering carries `sources`, `source_count` and the union of its attestations'
  `domain` and `sense`.
- **Embeddings** stay stored in Postgres so a reindex never re-embeds. With OpenSearch, **don't build** the
  pgvector HNSW index from `search_schema.md`.
- **Full rebuild:** about 367k docs plus 507k nested renderings at 1–2k docs/s is about 4–8 minutes.
- **Fallback:** if OpenSearch is unreachable (300 ms timeout), `search.py` uses its current Postgres path.
- **Consistency:** about 1–2 s lag. The review queue and term pages read Postgres, so they're never stale.

## 6. Running it

```yaml
  search:
    image: opensearchproject/opensearch:2.19.2   # pin; needs analysis-icu
    restart: unless-stopped
    environment:
      discovery.type: single-node
      OPENSEARCH_JAVA_OPTS: -Xms1g -Xmx1g
      bootstrap.memory_lock: "true"
      DISABLE_SECURITY_PLUGIN: "true"           # internal compose network only, never published
    ulimits: { memlock: { soft: -1, hard: -1 } }
    mem_limit: 2560m
    volumes: [./data/opensearch:/usr/share/opensearch/data]
```

- The host needs `vm.max_map_count=262144` (add it to `deploy/setup_server.sh`).
- **Sizing after the mydictionary import:** vectors 367k × 384 × 4 B ≈ 560 MB plus about 50 MB of graph
  (page cache, lucene engine). Text with n-grams and nested renderings ≈ 0.5–0.8 GB on disk. The
  Tamil index adds < 100 MB. **Budget a 1 GB heap and about 2.5 GB for the container.** Only embed terms that
  have Tamil, or switch to faiss with `sq` fp16 encoding, to roughly halve the vector part if memory is tight.
- **Backups:** none. The index is rebuilt from Postgres.
- **Never publish** port 9200.

## 7. Evaluation

### What changes once `data_raw` is counted

The DB alone (220k terms, 68k renderings, 1 domain, 1 region) is a weak case for a search engine. Counting
`data_raw` changes that:

- **6.5× more renderings** across **72 subject books**: per-rendering domain filtering and ranking become a
  core feature. That's nested documents plus aggregations, which OpenSearch does natively and Postgres does
  with `GROUP BY`s over joins.
- **293k inflected forms**: exact inflection → lemma lookup. Either engine can store this, but OpenSearch can
  combine it with prefix, n-gram, romanisation and synonym signals in one scored query.
- **Every rendering lacks romanisation** after the import: the analyzer-based Tanglish key earns its place.
- **65% phrases** among new terms: phrase-aware autocomplete and fuzzy matching matter more.

### What OpenSearch gives you

| Need | Postgres (planned) | OpenSearch |
|---|---|---|
| Typo tolerance | `pg_trgm` similarity, tuning by hand | `fuzziness: AUTO` |
| Tanglish → Tamil | a new column + Python key | `roman_key` analyzer + generated romanisation |
| Inflected Tamil | forms table + extra join | `forms` keyword inside the nested query |
| Domain-aware results ("fisheries word for *scale*") | join + filter + manual scoring | nested query + `inner_hits` |
| Ranking over about 10 signals | hand-written tiers | BM25 + boosts + `function_score`, `_explain` |
| Lexical + vector blending | `× 0.6` constant | hybrid pipeline with normalisation |
| Facets (domain, source, licence, approved) | `GROUP BY` per facet | aggregations in the same request |
| Query analytics | new table | `kalaichol-queries` data stream, seeded with the 26,990 known gaps |

### What it costs

- **Memory on a shared server:** about 2.5 GB, against well under 1 GB for Postgres with the same data.
- **A second system to run:** JVM, `vm.max_map_count`, upgrades.
- **Code:** outbox, `search_sync`, `search_reindex` with an alias swap, fallback, plus the new
  `Suggestion.domain` / `register` columns and the forms table. About 500 lines plus tests.
- **About 1–2 s eventual consistency.**
- **Scale still isn't the reason.** About 370k terms and 500k renderings is fine for Postgres too.

### Verdict

**Yes, adopt OpenSearch, if the server can give it about 2.5 GB.** With the `data_raw` content counted, this
is a multi-domain, multi-source lexicon with inflection tables and no romanisation, and its search quality
depends on combining many weak signals per rendering. That's what OpenSearch is built for. On the database
alone the case was marginal; with `data_raw` it's clear.

Order of work:

1. **Data first, any engine:** re-export mydictionary (`--export-only`), add `Suggestion.domain` /
   `register` and the forms table, keep everything `import_wiktionary` currently drops that search uses, and
   fix the TVA OCR digit look-alikes at import. All of this helps the Postgres fallback too.
2. Build outbox + `search_sync` + `search_reindex` (alias swap) and load `kalaichol-terms`.
3. Put it behind `SEARCH_BACKEND=postgres|opensearch` and compare the two on the 26,990 gap words and on real
   zero-result queries.
4. Keep the Postgres lexical path and its trigram indexes as the fallback. Drop the pgvector HNSW plan.
5. Phase 2: `kalaichol-tamil`.

If the server **can't spare 2.5 GB**, do step 1 anyway and stay on Postgres: a `roman_key` column, the forms
table, `pg_trgm` similarity and pgvector. You lose phrase autocomplete, facets and principled blending, but
keep most of the recall gain.

### Risks and open questions

- **`analysis-icu`** may not be in the stock image. If it can't be installed, NFC-normalise in Python at both
  index and query time and drop `ta_nfc`.
- **Code-point n-grams split Tamil graphemes** (`கி` = `க` + `ி`). Require at least 2 characters before
  running Tamil prefix search.
- **The roman key over-matches** `l/ḷ/ḻ` and `n/ṇ/ṉ`. Check it against real queries.
- **Licence:** the `queries.jsonl` rows carry no licence. `scrape_mydictionary.py --export-only` resolves it
  per book from `dictionaries.json`, so import from the export, not the cache. The OCR'd TVA books stay
  excluded from public exports, as they are now.
- **Machine and OCR noise at scale:** 439k draft rows will outnumber reviewed ones roughly 40:1. Down-weight
  `status: draft` with a single source, and boost renderings that several books agree on (`source_count`).
- The counts are from local data. Re-run them on production before sizing the container.
