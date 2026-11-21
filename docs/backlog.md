# Backlog (beta → next)

Starting issues for https://github.com/godisai-in/kalaisol/issues. Each heading is one issue title.

## Hugging Face integration: sync dataset to and from the app
`export_dataset` and `push_hf` already push one way. Still to do: pull corrections from the HF repo back in,
put both directions on a schedule, and record which version was synced.

## Admin approval: add email notification
The flag already exists (`REQUIRE_USER_APPROVAL=1`, approve in `/manage/users/` or Telegram).
Still to do: email the user when they're approved or blocked, and email admins about new pending accounts
when Telegram isn't set up.

## Bulk data ingestion pipeline
Bring `ingest`, `import_*` and `build_embeddings` together into one repeatable run: validate
(`lexicon/schemas.py`), dedupe, import, re-embed only what changed, and report the counts.

## Term suggestions and corrections from users
Users can already suggest Tamil words. Still to do: suggest new English terms through review, and propose
corrections to existing rows (gloss, region) with a diff that reviewers can see.

## Moderation of ratings and comments
Reports cover suggestions only. Add moderation for abusive rating patterns (one user rating down many
suggestions) and for any free-text comments once they exist.

## Analytics: top searches and searches with no results
Log each query (normalised, no user id) with its hit count. Add a `/manage/` page for the top queries and
the zero-result queries, which then feed data collection.

## Search quality: fuzzy matching, Tamil/English transliteration
Trigram indexes exist (migration 0008). Add typo tolerance for English, Tamil written in Latin script
(e.g. "kanini" → கணினி), and test against the zero-result queries.

## Performance and caching
Cache popular term pages and search results, measure p95 search latency on the full dataset, and keep the
embedding index in memory once per worker.
