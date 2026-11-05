from allauth.account.signals import email_confirmed, user_signed_up
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, Report, Status, Suggestion
from .notify import approve_buttons, esc, notify_admins


@receiver(user_signed_up)
def new_user(request, user, **kw):
    Profile.objects.get_or_create(user=user)
    gate = "waiting for approval" if settings.REQUIRE_USER_APPROVAL else "approval not required"
    notify_admins(
        f"🆕 <b>New user</b> {esc(user.username)}\n{esc(user.email)}\nEmail not confirmed yet · {gate}",
        approve_buttons("u", user.pk) if settings.REQUIRE_USER_APPROVAL else None,
    )


@receiver(email_confirmed)
def email_verified(request, email_address, **kw):
    notify_admins(f"✔ <b>Email confirmed</b> {esc(email_address.user.username)} ({esc(email_address.email)})")


@receiver(post_save, sender=Suggestion)
def new_suggestion(sender, instance, created, **kw):
    if created and instance.status == Status.PENDING:
        notify_admins(
            f"📝 <b>New suggestion</b> by {esc(instance.author.username if instance.author else '?')}\n"
            f"{esc(instance.term.text)} → <b>{esc(instance.tamil)}</b>\n"
            f"Source: {esc(instance.source or instance.source_kind)}",
            approve_buttons("s", instance.pk),
        )


@receiver(post_save, sender=Report)
def new_report(sender, instance, created, **kw):
    if created:
        s = instance.suggestion
        notify_admins(
            f"🚩 <b>Report</b> ({esc(instance.get_reason_display())}) by {esc(instance.user.username)}\n"
            f"{esc(s.term.text)} → {esc(s.tamil)}\n{esc(instance.comment[:200])}"
        )
