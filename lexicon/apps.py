from django.apps import AppConfig


class LexiconConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lexicon"

    def ready(self):
        from . import signals  # noqa: F401
