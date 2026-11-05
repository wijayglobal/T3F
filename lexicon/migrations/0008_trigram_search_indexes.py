"""Trigram indexes so search's `icontains` lookups use an index on Postgres instead of scanning.

Django compiles `text__icontains=q` to `UPPER("text"::text) LIKE UPPER('%q%')`; a GIN index on that
same expression with gin_trgm_ops serves it. SQLite (local dev) has no equivalent, so this is a no-op
there. pg_trgm is a trusted extension (Postgres 13+), so the database owner can create it.
"""
from django.db import migrations

INDEXES = [
    ("lexicon_term_text_trgm", "lexicon_term", "text"),
    ("lexicon_suggestion_tamil_trgm", "lexicon_suggestion", "tamil"),
]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in INDEXES:
        schema_editor.execute(
            f'CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (UPPER("{column}"::text) gin_trgm_ops)'
        )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name, _, _ in INDEXES:
        schema_editor.execute(f"DROP INDEX IF EXISTS {name}")


class Migration(migrations.Migration):

    dependencies = [
        ('lexicon', '0007_profile_approval'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
