# கலைச்சொல் · Tamil term lookup (Django)

English → Tamil lookup with regional variants, community suggestions, ratings,
synonyms/antonyms and meaning-based (vector) search. Theme follows Mozhi (kumkum red + manjal yellow).

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`, Python 3.11).

```bash
uv sync                                                              # creates .venv from uv.lock
uv run python manage.py migrate
uv run python manage.py import_wiktionary data_raw/tamil.jsonl       # seed terms, Tamil words, syn/ant
uv run python manage.py build_embeddings                             # vector index (downloads ~220 MB model once)
uv run python manage.py createsuperuser                              # for /admin (moderation)
uv run python manage.py runserver
```

Website dependencies are in `dependencies`. The data tools (NLLB, NLTK, pyarrow, Hugging Face) are in the
`data` group, which local `uv sync` installs but the Docker image leaves out.
Add a dependency with `uv add <package>` (or `uv add --group data <package>`) (updates `pyproject.toml` and `uv.lock`; commit both).
After changing either file by hand, run `uv lock`. CI and the Docker build use `--locked` and fail if
the lockfile is out of date.

## Accounts, verification and review

- Sign-up needs username, email and password, and a **confirmation email** must be clicked before first login.
  In development mails print in the server log; set `EMAIL_HOST*` in `.env` for real SMTP.
- Only verified users can suggest, rate, report or review.
- **User suggestions start as `pending` and are invisible to others.** On `/review/` verified users tick (correct) or cross
  (incorrect). Net `REVIEW_THRESHOLD` (default 2) accepts makes it live; net rejects hides it. Staff votes decide at once.
  Authors cannot review their own words.
- Machine, OCR and scraped rows are public but flagged **unreviewed draft** until reviewers confirm them.
- Profile pages `/u/<name>/` show points, reviews, agreement rate, badges and approved words, plus an embeddable
  card (`/u/<name>/embed/`) and an SVG badge (`/u/<name>/badge.svg`). Users can make their profile private.

## Admins

- **Telegram group alerts:** new users, confirmed emails, new pending words and reports are posted to a group.
  Approve/Reject buttons on users and words work only for the Telegram ids in `TELEGRAM_ADMIN_IDS`
  (an unlisted person who presses a button is told their own id so you can add it).
  Create the bot with @BotFather, add it to the group, set the four `TELEGRAM_*` variables, then run
  `manage.py telegram_poll` next to the web server (no public URL needed), or on a public HTTPS site use
  `manage.py telegram_webhook set`. Without a token, alerts are written to the server log.
- **Approval:** set `REQUIRE_USER_APPROVAL=1` so new accounts can browse but not contribute until an admin approves.
- **Admin panel `/manage/`:** overview, users (approve/reject; superusers can promote admins), add one word or paste many with
  source and licence, and a reports queue. Words added here are approved immediately and credited to the admin.
- **Credits:** `/contributors/` lists admins and contributors; exports include `contributors.json` and a dataset-card section.

This app is deliberately only the Tamil glossary. Another corpus (for example Thirukkural) would be a separate
deployment of the same code, not a mode inside this one.

## Collecting data

```bash
manage.py import_wiktionary            # English Wiktionary (CC BY-SA)
manage.py import_english               # WordNet + system word list: every English headword
manage.py import_tva                   # TVA science glossaries (OCR; check publisher rights before redistributing)
python3 -I scripts/scrape_mydictionary.py data_raw/mydictionary   # mydictionary.in, 73 books (CC BY-SA / CC0); days, resumable
manage.py import_mydictionary          # …then import it, validated by lexicon/schemas.py (--dry-run to just report)
manage.py ingest wikipedia_ta          # Tamil Wikipedia interlanguage titles (CC BY-SA); resumable
manage.py ingest file my.tsv --name "Source" --license "CC BY 4.0" --url https://…   # any en/ta table
manage.py machine_draft --limit 20000  # NLLB-200 drafts for words with no Tamil, labelled unreviewed
```

All rows keep source, URL and licence.

## Hugging Face dataset

```bash
manage.py export_dataset               # approved rows only -> export/ (jsonl, parquet, dataset card)
HF_TOKEN=hf_... manage.py push_hf --repo yourname/kalaichol
```

`--include-drafts` adds unreviewed rows; `--include-books` adds the OCR'd book rows (off by default for licensing).

## Deploy

```bash
cp .env.example .env   # edit secrets, hosts, SMTP; WEB_PORT (default 8081)
ss -tlnp               # make sure WEB_PORT is free on this server
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Gunicorn + WhiteNoise + Postgres. The compose project is named `kalaichol`, so it won't clash with other
apps on the same server. Postgres keeps its data in `./data/pgdata` and isn't published to the host
(uncomment the `127.0.0.1:5433` line only for debugging). The web container listens only on
`127.0.0.1:${WEB_PORT}`. Put it behind HTTPS with `deploy/Caddyfile` (an nginx example is included there).
Models (embeddings, NLLB) live in the `models` volume and `data_raw/`.

**Backups:** `deploy/backup.sh` writes `backups/kalaichol-YYYY-MM-DD.sql.gz` and keeps 14 days. Add it to cron:

```
15 3 * * * /path/to/tamil_translation/deploy/backup.sh >> /path/to/tamil_translation/backups/backup.log 2>&1
```

**Release:** run locally with `docker compose up`, import data, deploy behind the proxy, turn on backups,
then share with a small group first. The open work is in `docs/backlog.md`.

**CI/CD:** pushes to `main` are tested and deployed by GitHub Actions; server setup and secrets are in `docs/DEPLOY.md`.

## How it works

- **Search** (`lexicon/search.py`): literal match on English or Tamil text plus cosine similarity over
  multilingual MiniLM embeddings of every English term. Literal hits rank first; meaning-only hits are shown
  under "related by meaning". Without embeddings it falls back to literal only.
- **Suggestions**: signed-in users add a Tamil word per English term with a region (Chennai, Madurai, Kongu, …).
- **Ratings**: 1–5 stars, one per user per suggestion, not on your own suggestion.
- **Reports**: remove / incorrect / needs review; three "remove" reports hide a suggestion until a moderator resolves it in admin.
- New English terms added by users need `build_embeddings` re-run to appear in meaning search.
# kalaisol
