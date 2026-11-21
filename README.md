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

## Security

What the app does to protect users and the server, and what you must set when deploying.

**Required in production (`DJANGO_DEBUG=0`)**

- `DJANGO_SECRET_KEY`: a random string of 50+ characters
  (`python -c "import secrets; print(secrets.token_urlsafe(50))"`). The app refuses to start in production
  with the built-in development key.
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`: your real domain. `*` is never used, not even in development
  (development defaults to `localhost,127.0.0.1,[::1]`; add a LAN address to `ALLOWED_HOSTS` if you need one).
- Run `manage.py check --deploy` after changing settings. Three warnings are expected unless you opt in:
  HSTS for subdomains, HSTS preload, and `SECURE_SSL_REDIRECT` (Caddy already redirects to HTTPS).

**HTTP headers** (`lexicon/middleware.py`, `config/settings.py`)

- `Content-Security-Policy`: scripts only from this site (no inline scripts or `onclick` handlers anywhere),
  styles and fonts from this site and Google Fonts, no plugins, forms post only to this site, and no framing.
- Only the profile card `/u/<name>/embed/` may be framed by other sites; every other page sends
  `X-Frame-Options: DENY` and `frame-ancestors 'none'` (clickjacking protection).
- `Strict-Transport-Security` (one year by default, `SECURE_HSTS_SECONDS`), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`, `Cross-Origin-Opener-Policy: same-origin`, and a
  `Permissions-Policy` that turns off camera, microphone, geolocation, payment and USB.
- Session and CSRF cookies are `Secure` (HTTPS only), `SameSite=Lax`, and the session cookie is `HttpOnly`.

**Input and output**

- Open redirects are blocked: the `next` field on report forms and the `Referer` used after admin actions
  only redirect to this site (`lexicon/access.py: safe_next`). Login redirects are built with Django's
  `redirect_to_login`, so the return address is URL-encoded.
- Links from imported data (source URLs, profile websites) pass through the `safe_url` template filter, which
  drops anything that is not `http(s)://` (for example `javascript:` links that bypassed form validation in bulk imports).
- External links open with `rel="noopener noreferrer nofollow"`.
- Search queries are cut at 100 characters, report comments at 1000, request bodies at 2 MB, Telegram webhook
  bodies at 64 KB, and a bulk paste at 5000 lines.
- Telegram messages escape user text before they are re-sent as HTML; the webhook compares its secret in
  constant time and logs failed updates instead of hiding them.
- Data commands only fetch `http(s)` URLs.

**Abuse limits**

- Login, sign-up and password reset are throttled by django-allauth.
- Suggesting, rating, reporting and review votes are limited to `WRITE_RATE_LIMIT` (default 30) per user per
  minute. The counter uses Django's default cache, which is per gunicorn worker; configure a shared cache
  (for example Redis) if you need an exact limit across workers.
- Only verified (email-confirmed) users can contribute; admins can also require manual approval
  (`REQUIRE_USER_APPROVAL=1`). Superusers cannot remove their own admin rights from `/manage/`.

**Container**

- The web server runs as the unprivileged `app` user (uid 10001). The entrypoint starts as root only to run
  migrations and hand the `models` volume to `app`, then drops privileges with `setpriv`.
  `docker compose exec web python manage.py …` still runs as root, so data commands can write to `./data_raw`.
- Postgres is not published to the host and the web container listens only on `127.0.0.1`.

Report a security problem privately to the maintainers rather than in a public issue.

## Accessibility

The site aims for WCAG 2.2 AA.

- **Keyboard:** a "Skip to content" link is the first thing you reach with Tab. Every control is a real
  `<button>`, link or form field, with a visible focus outline (also inside the red header). The star rating
  works with Tab and Enter. After a review vote, focus moves to the same button on the next card, so you
  can review a queue from the keyboard without losing your place.
- **Screen readers:**
  - Tamil text is marked `lang="ta"`, so screen readers switch to a Tamil voice. Tamil-only buttons and links
    also carry an English name that only screen readers read (for example "தேடுக (search)").
  - Search boxes and report fields have labels. Star buttons say "4 of 5 stars" and report whether they are
    selected (`aria-pressed`).
  - A polite live region announces new ratings and review results. Messages after a form is sent are
    announced too; errors interrupt.
  - Decorative symbols (✓, ⚙, ஃ, avatars) are hidden from screen readers. Tables have headers with `scope`
    and a caption, and scroll sideways inside a focusable region on small screens.
  - Results pages start with an `<h1>`, each review card has a heading, and tab bars mark the current tab
    with `aria-current="page"`.
- **Forms:** when adding a word fails, the form keeps what you typed, marks the wrong fields with
  `aria-invalid` and shows the message beside them.
- **Colour and motion:**
  - Secondary text was darkened from 3.8:1 to 5.7:1 contrast against the background.
  - Buttons are at least 44 px tall and star buttons 32 px.
  - `prefers-reduced-motion` turns off the button press and card fade animations.
  - Windows high-contrast (`forced-colors`) mode keeps borders and the selected stars visible.
- **Errors:** messages show beside the control instead of in pop-ups where possible; failed ratings and votes
  are announced in an alert.
- The standalone demo in `site/` got the same treatment: a labelled voice-search button that reports its
  state, keyboard-reachable "Recent" and copy actions, and table headers.

## Code quality

- **Lint:** `ruff check .` (configured in `pyproject.toml`) runs pyflakes, pycodestyle, bugbear, pyupgrade,
  import sorting, simplify and the bandit security rules. The codebase passes cleanly.
- **Shared helpers:**
  - Access rules (`is_verified`, `verified_required`, `staff_required`, `safe_next`, `rate_limited`) are in
    one place, `lexicon/access.py`, instead of being copied between `views.py` and `manage_views.py`.
  - Magic numbers have names (`REMOVE_REPORTS_TO_HIDE`, `MAX_QUERY_LENGTH`, `MAX_BULK_LINES`).
  - Contributor points come from a single `contribution_points()` used by profiles and the contributors page.
  - A profile's average rating is computed in the database (`Avg`) instead of in Python.
- **JavaScript (`static/js/site.js`):**
  - One `postForm()` helper handles CSRF, JSON and errors, including sign-in redirects that are not JSON.
  - Results are built with DOM methods instead of `innerHTML`.
  - Autocomplete cancels requests that are out of date.
  - Buttons are disabled while a vote is being sent.
- **Tests:** `manage.py test lexicon` covers:
  - the security headers and the embed exception
  - open redirects through `next` and `Referer`
  - the `safe_url` filter and `javascript:` links from imported data
  - the write rate limit and the length cap on search queries
  - a failed "add word" form keeping the input and marking errors
  - the skip link and labels, and that the staff pages render

## How it works

- **Search** (`lexicon/search.py`): literal match on English or Tamil text plus cosine similarity over
  multilingual MiniLM embeddings of every English term. Literal hits rank first; meaning-only hits are shown
  under "related by meaning". Without embeddings it falls back to literal only.
- **Suggestions**: signed-in users add a Tamil word per English term with a region (Chennai, Madurai, Kongu, …).
- **Ratings**: 1–5 stars, one per user per suggestion, not on your own suggestion.
- **Reports**: remove / incorrect / needs review; three "remove" reports hide a suggestion until a moderator resolves it in admin.
- New English terms added by users need `build_embeddings` re-run to appear in meaning search.
# kalaisol
