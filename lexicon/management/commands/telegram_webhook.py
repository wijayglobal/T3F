"""Register or remove the Telegram webhook (needs a public HTTPS SITE_URL).

    manage.py telegram_webhook set | delete | info
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from lexicon.notify import api


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["set", "delete", "info"])

    def handle(self, action, **opts):
        if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_WEBHOOK_SECRET):
            raise CommandError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET.")
        if action == "set":
            url = f"{settings.SITE_URL.rstrip('/')}/telegram/webhook/{settings.TELEGRAM_WEBHOOK_SECRET}/"
            if not url.startswith("https://"):
                raise CommandError("Telegram only calls https:// URLs; use telegram_poll for local/LAN use.")
            self.stdout.write(str(api("setWebhook", {"url": url, "allowed_updates": ["callback_query"]})))
        elif action == "delete":
            self.stdout.write(str(api("deleteWebhook", {})))
        else:
            self.stdout.write(str(api("getWebhookInfo", {})))
