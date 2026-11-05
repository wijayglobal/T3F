"""Telegram notifications to the admin group. No token configured -> messages go to the log instead."""
import json
import logging
import threading
import urllib.request

from django.conf import settings
from django.utils.html import escape

log = logging.getLogger("kalaichol.notify")


def configured():
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def api(method, payload):
    """Call the Telegram Bot API. Raises on HTTP errors."""
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as f:
        return json.load(f)


def _send(text, buttons):
    try:
        payload = {"chat_id": settings.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        api("sendMessage", payload)
    except Exception:  # a notification must never break a sign-up
        log.exception("telegram send failed")


def notify_admins(text, buttons=None, background=True):
    """text is HTML (escape user input with `esc`). buttons: rows of {"text", "callback_data"}."""
    if not configured():
        log.warning("[telegram not configured] %s", text.replace("\n", " | "))
        return
    if background:
        threading.Thread(target=_send, args=(text, buttons), daemon=True).start()
    else:
        _send(text, buttons)


esc = escape


def approve_buttons(kind, pk):
    return [[
        {"text": "✅ Approve", "callback_data": f"{kind}:approve:{pk}"},
        {"text": "❌ Reject", "callback_data": f"{kind}:reject:{pk}"},
    ]]
