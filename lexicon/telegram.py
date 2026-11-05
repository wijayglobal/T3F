"""Handle button presses from the admin group (webhook or `telegram_poll`)."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Profile, Review, Status, Suggestion
from .notify import api, esc

log = logging.getLogger("kalaichol.telegram")


def admin_ids():
    return {int(x) for x in settings.TELEGRAM_ADMIN_IDS.split(",") if x.strip().isdigit()}


def _answer(cb, text, alert=False):
    try:
        api("answerCallbackQuery", {"callback_query_id": cb["id"], "text": text, "show_alert": alert})
    except Exception:
        log.exception("answerCallbackQuery failed")


def _mark_message(cb, note):
    msg = cb.get("message")
    if not msg:
        return
    try:
        api("editMessageText", {
            "chat_id": msg["chat"]["id"], "message_id": msg["message_id"], "parse_mode": "HTML",
            "text": (msg.get("text") or "") + f"\n\n{note}",
        })
    except Exception:
        log.exception("editMessageText failed")


def decide_user(user_id, approve, by):
    prof = Profile.objects.select_related("user").get(user_id=user_id)
    prof.approval = "approved" if approve else "rejected"
    prof.approved_by, prof.approved_at = by, timezone.now()
    prof.save(update_fields=["approval", "approved_by", "approved_at"])
    if prof.user.email:
        send_mail(
            "Your கலைச்சொல் account " + ("is approved" if approve else "was not approved"),
            "You can now suggest, rate and review words." if approve
            else "An admin did not approve this account. Reply to this mail if you think that's a mistake.",
            None, [prof.user.email], fail_silently=True,
        )
    return prof.user.username


def decide_suggestion(pk, approve):
    s = Suggestion.objects.select_related("term").get(pk=pk)
    s.apply_reviews(staff_verdict=Review.ACCEPT if approve else Review.REJECT)
    return f"{s.term.text} → {s.tamil}"


def handle_update(update):
    cb = update.get("callback_query")
    if not cb:
        return
    sender = cb["from"]
    if sender["id"] not in admin_ids():
        _answer(cb, f"Not authorised. Your Telegram id is {sender['id']}; ask the site owner to add it to TELEGRAM_ADMIN_IDS.", alert=True)
        return
    who = "@" + sender["username"] if sender.get("username") else sender.get("first_name", str(sender["id"]))
    try:
        kind, action, pk = cb["data"].split(":")
        approve = action == "approve"
        if kind == "u":
            name = decide_user(int(pk), approve, f"telegram:{who}")
        elif kind == "s":
            name = decide_suggestion(int(pk), approve)
        else:
            raise ValueError(kind)
    except Exception:
        log.exception("bad callback %r", cb.get("data"))
        _answer(cb, "That item no longer exists or the button is invalid.", alert=True)
        return
    verb = "✅ Approved" if approve else "❌ Rejected"
    _answer(cb, f"{verb}: {name}")
    _mark_message(cb, f"{verb} by {esc(who)}")
