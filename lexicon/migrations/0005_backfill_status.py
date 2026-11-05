from django.db import migrations


def backfill(apps, schema_editor):
    S = apps.get_model("lexicon", "Suggestion")
    S.objects.filter(source_kind="wiktionary").update(status="approved", license="CC BY-SA 4.0")
    S.objects.filter(source_kind="book").update(status="draft", license="check publisher rights")
    S.objects.filter(source_kind="machine").update(status="draft", license="machine output")


class Migration(migrations.Migration):
    dependencies = [("lexicon", "0004_review_profile_status")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
