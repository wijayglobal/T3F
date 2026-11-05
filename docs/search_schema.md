# Search schema: relational tables + vector store

Schema for the hybrid search in `lexicon/search.py`, tuned for fast reads and cheap writes on Postgres 16 +
pgvector. SQLite (local dev) keeps the current BinaryField + NumPy path.

The search does two things:

1. **Lexical**: exact, prefix and substring matches on English `Term.text`, Tamil `Suggestion.tamil`
   and Tanglish `Suggestion.roman`.
2. **Semantic**: nearest English terms to the query, using `paraphrase-multilingual-MiniLM-L12-v2`
   (384-dim, L2-normalised, input wrapped as `the word "<text>"`). Hits need a score of at least 0.7 and
   are scaled by 0.6 so they rank under literal hits.

The writes it has to absorb:

- **Bulk imports:** `import_*`, `ingest` and `machine_draft` use `bulk_create(..., ignore_conflicts=True)`
  in batches of about 2000, with 10k–200k rows per run.
- **Single writes:** a user adds a term or suggestion (`get_or_create`), and ratings, reviews and status
  changes update one suggestion at a time.

Every index speeds up some read and slows down every insert. So the rule below is: index exactly what a
query uses, make indexes partial where the query is, and drop the rest.

---

## 1. Relational tables

### `lexicon_term`: English headwords

| Column | Type | Notes |
|---|---|---|
| `id` | `bigint` PK | |
| `text` | `varchar(120)` NOT NULL UNIQUE | stored lower-case (all write paths already lower-case it) |
| `domain` | `varchar(120)` NOT NULL DEFAULT '' | |
| `gloss` | `varchar(300)` NOT NULL DEFAULT '' | |
| ~~`embedding`~~ | ~~`bytea`~~ | **dropped on Postgres.** It moves to `lexicon_term_embedding`. Each row loses 1.5 KB of TOAST data, and every `Term` fetch gets cheaper |

```sql
-- keep: uniqueness + get_or_create + bulk_create(ignore_conflicts)
UNIQUE (text)
-- new: serves Django's iexact / istartswith, which compile to UPPER(text) = / LIKE 'Q%'
CREATE INDEX lexicon_term_upper_prefix ON lexicon_term (UPPER(text) text_pattern_ops);
-- keep (0008): serves icontains → UPPER(text) LIKE '%Q%'
CREATE INDEX lexicon_term_text_trgm    ON lexicon_term USING gin (UPPER(text) gin_trgm_ops);
```

The indexes are built on `UPPER(...)` so the queries the ORM already generates can use them unchanged. That
avoids a generated column and any code change.

### `lexicon_suggestion`: Tamil renderings

Columns are unchanged: `term_id` FK (cascade), `tamil`, `roman`, `region`, `pos`, `note`, the `source*`
fields, `license`, `author_id`, `status`, `hidden`, `rating_avg`, `rating_count`, `created` and
`decided_at`. Storage and indexes change:

```sql
ALTER TABLE lexicon_suggestion SET (fillfactor = 90);
-- Leaves room on each page so rating_avg / rating_count updates (unindexed columns) are HOT updates
-- and don't touch any index.

-- keep: dedupe for ignore_conflicts and the exists() check in views.py
UNIQUE (term_id, tamil, region)      -- also serves every "suggestions of term X" lookup (leading column)

-- DROP the plain btree on tamil (db_index=True). The unique index and the partial indexes below cover
-- every query that used it.
-- DROP the plain btree on status (db_index=True): low cardinality, and it was updated on every insert.

-- new: search reads public rows only, so only public rows are indexed. Pending user suggestions and
-- rejected rows cost nothing in these indexes when inserted.
CREATE INDEX lexicon_suggestion_public_tamil_trgm ON lexicon_suggestion
       USING gin (tamil gin_trgm_ops)
       WHERE hidden = false AND status IN ('approved', 'draft');            -- tamil LIKE '%q%'
CREATE INDEX lexicon_suggestion_public_tamil_prefix ON lexicon_suggestion (tamil text_pattern_ops)
       WHERE hidden = false AND status IN ('approved', 'draft');            -- tamil = q / LIKE 'q%'
CREATE INDEX lexicon_suggestion_public_roman ON lexicon_suggestion (UPPER(roman))
       WHERE hidden = false AND status IN ('approved', 'draft') AND roman <> '';   -- roman__iexact

-- new: the review queue (views.py) is the only status filter that is not a count over all rows
CREATE INDEX lexicon_suggestion_pending ON lexicon_suggestion (created)
       WHERE status = 'pending' AND hidden = false;
-- (replaces) DROP INDEX lexicon_suggestion_tamil_trgm  -- the full-table UPPER(tamil) trigram from 0008
```

Tamil has no letter case, so search should use `tamil__contains` / `tamil__startswith` instead of `icontains`.
That lets it hit the indexes built on plain `tamil` above.

Check before relying on the trigram index: `SELECT show_trgm('கணினி');` must return trigrams in the
database's locale. Under `C` collation, multibyte letters are not counted as word characters. The index then
stays correct but turns into a full index scan.

### `lexicon_relation`: Tamil synonym / antonym links

```sql
UNIQUE (word, other, kind)   -- keep: dedupe, and its leading column serves word IN (...)
-- DROP the separate btree on word: redundant with the unique index
-- DROP the separate btree on other: no query filters on it
```

Every relation insert goes from three index updates to one.

---

## 2. Vector store (pgvector, same Postgres)

```sql
CREATE EXTENSION IF NOT EXISTS vector;        -- image: pgvector/pgvector:pg16, pgvector >= 0.8

CREATE TABLE lexicon_embedding_model (
    id    smallint PRIMARY KEY,
    name  varchar(100) NOT NULL UNIQUE,         -- 'paraphrase-multilingual-MiniLM-L12-v2'
    dim   smallint NOT NULL,                    -- 384
    prompt varchar(100) NOT NULL                -- 'the word "{}"'
);

CREATE TABLE lexicon_term_embedding (
    term_id    bigint       NOT NULL REFERENCES lexicon_term(id) ON DELETE CASCADE,
    model_id   smallint     NOT NULL REFERENCES lexicon_embedding_model(id),
    embedding  halfvec(384) NOT NULL,           -- L2-normalised, fp16
    input_hash bytea        NOT NULL,           -- 8-byte xxhash/sha1 prefix of the embedded string
    PRIMARY KEY (term_id, model_id)
);

CREATE INDEX lexicon_term_embedding_hnsw_m1
    ON lexicon_term_embedding USING hnsw (embedding halfvec_ip_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE model_id = 1;
```

Why each choice:

| Choice | Search | Insert |
|---|---|---|
| Separate table, not a column on `lexicon_term` | Lexical queries read narrow rows. No per-worker 300 MB NumPy matrix, and no 5-minute staleness check | A term insert never waits on embedding |
| `halfvec` (fp16) | Index is about 150 MB instead of 300 MB, so it stays in `shared_buffers`. Recall loss for MiniLM is negligible | Half the WAL and I/O per row |
| `halfvec_ip_ops` (inner product) | Same ranking as cosine on unit vectors, and the cheapest operator | n/a |
| HNSW `m=16, ef_construction=64` | About 99% recall at `ef_search=40` for 200k rows, in 1–3 ms | Moderate build cost. A higher `ef_construction` buys little at this size |
| Smallint `model_id` + partial index per model | Index holds one model only | A new model is built next to the old one; switch by setting, then drop |
| `input_hash` | n/a | Re-embeds only new or changed terms (see upsert below). `--all` is never needed |

The main cost of HNSW is insertion: each row walks the graph. So:

**Single inserts (a user adds a term):** embed inline in `transaction.on_commit`. The model is already loaded
in every web worker for query embedding, so one term takes about 10–20 ms. The term is in meaning search
immediately, and `build_embeddings` no longer has to be re-run for user-added terms.

**Bulk inserts:** in `build_embeddings`, after an import:

```sql
-- incremental (new rows < ~10% of the table): keep the index, batch-upsert 5000 rows per statement
INSERT INTO lexicon_term_embedding (term_id, model_id, embedding, input_hash)
VALUES ... 
ON CONFLICT (term_id, model_id) DO UPDATE
   SET embedding = EXCLUDED.embedding, input_hash = EXCLUDED.input_hash
   WHERE lexicon_term_embedding.input_hash <> EXCLUDED.input_hash;   -- unchanged rows: no write at all

-- full rebuild or a big import (> ~10%): load first, index after. 5–10× faster than inserting into a live HNSW
DROP INDEX IF EXISTS lexicon_term_embedding_hnsw_m1;
COPY lexicon_term_embedding (term_id, model_id, embedding, input_hash) FROM STDIN;   -- binary COPY
SET maintenance_work_mem = '1GB';                -- graph must fit, or the build slows down sharply
SET max_parallel_maintenance_workers = 4;
CREATE INDEX lexicon_term_embedding_hnsw_m1 ON lexicon_term_embedding
       USING hnsw (embedding halfvec_ip_ops) WITH (m = 16, ef_construction = 64) WHERE model_id = 1;
```

A full rebuild that must stay online can build `model_id = 2` alongside the old model and switch to it.

**Query** (replaces `semantic_terms`):

```sql
SET LOCAL hnsw.ef_search = 40;
SELECT term_id, -(embedding <#> %(q)s::halfvec) AS score
FROM   lexicon_term_embedding
WHERE  model_id = 1
ORDER  BY embedding <#> %(q)s::halfvec
LIMIT  12;          -- filter score >= 0.7 in Python. A WHERE on score would stop the index from being used.
```

Tamil stays lexical, because MiniLM aligns Tamil poorly with English headwords. A Tamil-capable model later
gets a sibling `lexicon_suggestion_embedding (suggestion_id, model_id, embedding, input_hash)` with the same
shape. Index only public rows there, and use `hnsw.iterative_scan = relaxed_order` when filtering.

---

## 3. Query changes that the schema depends on

These are small changes in `search.py`, but without them the indexes above are not used fully.

1. **Clear the default ordering on search queries (`.order_by()`).** `Term.Meta.ordering = ["text"]` and
   `Suggestion.Meta.ordering = [-rating_avg, …]` make Postgres find and sort *every* substring match
   before the `[:400]` slice.
2. **Run tiered, bounded lookups instead of one `icontains[:400]`.** Today, because results are sorted
   alphabetically and then cut at 400, an exact hit like "set" can be lost behind 400 earlier words that
   contain "set" ("asset", "basset", …). Run these in order and stop once there are 30 results:
   - exact match (`UPPER(text) = Q`, unique-index lookup)
   - starts-with (`UPPER(text) LIKE 'Q%'` using `text_pattern_ops`, LIMIT 30)
   - contains (trigram, LIMIT 30)

   Each step is an index scan with a small LIMIT.
3. **Use `tamil__contains` / `tamil__startswith` for Tamil queries** (no `UPPER`), so they hit the partial
   indexes.
4. **Do the vector lookup in SQL as above**, and drop the in-process index, the `_index_lock` and the
   recheck timer.
5. **Cache the home-page counts** (`views.py:89-90`). A count over the whole table is the one read that
   gets slower once the `status` index is dropped.

## 4. Bulk-import settings

- **Session settings:** for big imports, run `SET synchronous_commit = off` and
  `SET gin_pending_list_limit = '32MB'` in the import session. Trigram GIN indexes then batch their
  updates instead of rewriting posting lists row by row. Run `VACUUM (ANALYZE)` on the touched tables
  afterwards, which also flushes the GIN pending list.
- **Batch size:** keep `batch_size` at 2000–5000. Larger batches gain little and hold locks longer.
- **Partial indexes:** because the public indexes are partial, rows imported with status `pending` cost
  only the PK and unique index on insert. They are indexed when their status changes.

## 5. Data flow

```
user adds term ──► lexicon_term ──on_commit──► embed (10-20 ms) ──► lexicon_term_embedding (HNSW insert)
import_* ──bulk_create──► lexicon_term ──► build_embeddings: hash diff ──► upsert  │  or COPY + rebuild index

query ─┬─ Tamil  ──► exact → prefix → contains on public partial indexes ───────────────┐
       └─ English ─► exact → prefix → trigram on UPPER(text), roman on UPPER(roman) ─┐  │
                 └─► embed query ──► HNSW top-12 (<#>, ef_search 40) ─────────────────┴──┴─► merge (semantic × 0.6)
```
