"""Write the community dataset for Hugging Face: JSONL + Parquet + a dataset card.

    manage.py export_dataset [--out export] [--include-drafts] [--include-books]

By default only APPROVED rows are exported. Book (OCR) rows are left out unless you pass
--include-books, because their publisher's redistribution rights are not established.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Count

from lexicon.models import Profile, SourceKind, Status, Suggestion

CARD = """---
license: cc-by-sa-4.0
language:
- ta
- en
task_categories:
- translation
pretty_name: Kalaichol — English to Tamil terms, community reviewed
size_categories:
- {size}
---

# Kalaichol (கலைச்சொல்) — English → Tamil terms

Community-reviewed English→Tamil term pairs with regional variants, ratings and full provenance.

## Columns
`english`, `tamil`, `roman` (Tanglish), `region`, `pos`, `note`, `status`, `rating_avg`, `rating_count`,
`accepts`, `rejects`, `source_kind`, `source`, `source_url`, `source_ref`, `license`, `contributor`.

## Status
- `approved`: accepted by verified reviewers (or a moderator).
- `draft` (only with `--include-drafts`): scraped, OCR'd or machine-translated and **not yet reviewed**.

## Contributors
{contributors}

## Sources and licences
{sources}

Contributor usernames appear only for people who made their profile public.
Contributions are licensed CC BY-SA 4.0. Reuse must credit the sources above.

Contribute or review at your Kalaichol server.
"""


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--out", default="export")
        parser.add_argument("--include-drafts", action="store_true")
        parser.add_argument("--include-books", action="store_true")

    def handle(self, out, include_drafts, include_books, **opts):
        statuses = [Status.APPROVED] + ([Status.DRAFT] if include_drafts else [])
        qs = (
            Suggestion.objects.filter(status__in=statuses, hidden=False)
            .select_related("term", "author")
            .annotate(
                acc=Count("reviews", filter=__import__("django.db.models", fromlist=["Q"]).Q(reviews__verdict="accept")),
                rej=Count("reviews", filter=__import__("django.db.models", fromlist=["Q"]).Q(reviews__verdict="reject")),
            )
        )
        if not include_books:
            qs = qs.exclude(source_kind=SourceKind.BOOK)
        public = set(Profile.objects.filter(public=True).values_list("user_id", flat=True))
        rows = [
            {
                "english": s.term.text, "tamil": s.tamil, "roman": s.roman, "region": s.region,
                "pos": s.pos, "note": s.note, "status": s.status, "rating_avg": s.rating_avg,
                "rating_count": s.rating_count, "accepts": s.acc, "rejects": s.rej,
                "source_kind": s.source_kind, "source": s.source, "source_url": s.source_url,
                "source_ref": s.source_ref, "license": s.license,
                "contributor": s.author.username if s.author_id in public else None,
            }
            for s in qs.iterator(chunk_size=5000)
        ]
        contributors = self.contributors(rows, public)
        d = Path(out)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "kalaichol.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            pq.write_table(pa.Table.from_pylist(rows), d / "kalaichol.parquet")
        except ImportError:
            self.stdout.write("pyarrow not installed; skipped parquet")
        from collections import Counter

        c = Counter((r["source"], r["license"]) for r in rows)
        src = "\n".join(f"- {n} rows — {s} — licence: {l or 'n/a'}" for (s, l), n in c.most_common())
        n = len(rows)
        size = "n<1K" if n < 1000 else "1K<n<10K" if n < 10000 else "10K<n<100K" if n < 100000 else "100K<n<1M"
        (d / "contributors.json").write_text(json.dumps(contributors, ensure_ascii=False, indent=2), encoding="utf-8")
        people = "\n".join(
            f"- **{c['name']}** (@{c['username']}) — {c['role']}, {c['words']} words, {c['reviews']} reviews" for c in contributors
        )
        (d / "README.md").write_text(
            CARD.format(size=size, sources=src or "- (none yet)", contributors=people or "- (none yet)"), encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS(f"{n} rows -> {d}/"))

    def contributors(self, rows, public):
        """Admins and everyone with exported words or reviews, if their profile is public."""
        from django.contrib.auth import get_user_model
        from django.db.models import Q

        from lexicon.models import Review

        names = {r["contributor"] for r in rows if r["contributor"]}
        qs = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(username__in=names))
        out = []
        for u in qs.filter(id__in=public) | qs.filter(profile__isnull=True):
            profile = Profile.objects.filter(user=u).first()
            out.append({
                "username": u.username, "name": (profile.display_name if profile else "") or u.username,
                "role": "admin" if u.is_staff else "contributor",
                "words": sum(1 for r in rows if r["contributor"] == u.username),
                "reviews": Review.objects.filter(user=u).count(),
            })
        return sorted(out, key=lambda c: (c["role"] != "admin", -c["words"], c["username"]))
