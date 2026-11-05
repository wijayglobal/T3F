"""Receive admin button presses by long-polling (no public URL needed). Run it next to the web server.

    manage.py telegram_poll
For a public HTTPS deployment use the webhook instead:  manage.py telegram_webhook set
"""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from lexicon.notify import api
from lexicon.telegram import handle_update


class Command(BaseCommand):
    help = __doc__

    def handle(self, **opts):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("Set TELEGRAM_BOT_TOKEN first.")
        api("deleteWebhook", {})  # polling and webhooks are mutually exclusive
        offset = None
        self.stdout.write("polling Telegram… (Ctrl-C to stop)")
        while True:
            try:
                payload = {"timeout": 30, "allowed_updates": ["callback_query"]}
                if offset:
                    payload["offset"] = offset
                for u in api("getUpdates", payload).get("result", []):
                    offset = u["update_id"] + 1
                    handle_update(u)
            except KeyboardInterrupt:
                return
            except Exception:
                logging.getLogger("kalaichol.telegram").exception("poll error")
                time.sleep(5)
