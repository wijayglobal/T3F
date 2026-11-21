"""Who may do what: sign-in gates, safe redirects and a per-user write rate limit."""
import functools
import time

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Profile


def is_verified(user):
    """Signed in with a confirmed email address (superusers always count)."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or EmailAddress.objects.filter(user=user, verified=True).exists()


def is_approved(user):
    """Admin sign-off. Only enforced when REQUIRE_USER_APPROVAL is on; staff are always approved."""
    if not settings.REQUIRE_USER_APPROVAL or user.is_staff:
        return True
    return Profile.objects.filter(user=user, approval="approved").exists()


def verified_required(view):
    """Signed in, email confirmed and (if required) approved by an admin."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_verified(request.user):
            messages.error(request, "Please confirm your email address first — check your inbox.")
            return redirect("account_email")
        if not is_approved(request.user):
            messages.info(request, "Your account is waiting for an admin to approve it. You can search meanwhile.")
            return redirect("lexicon:home")
        return view(request, *args, **kwargs)

    return wrapper


def staff_required(view):
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_staff:
            messages.error(request, "Admins only.")
            return redirect("lexicon:home")
        return view(request, *args, **kwargs)

    return wrapper


def safe_next(request, url, fallback="lexicon:home"):
    """`url` if it points at this site, otherwise `fallback` (blocks open redirects via ?next= or Referer)."""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return resolve_url(fallback)


def rate_limited(view):
    """Allow each user settings.WRITE_RATE_LIMIT calls per minute to the wrapped views together.

    Uses the default cache (per process unless a shared cache is configured), which is enough to
    stop a runaway script; allauth separately throttles login and sign-up.
    """

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        limit = settings.WRITE_RATE_LIMIT
        if limit and request.user.is_authenticated and request.method == "POST":
            key = f"writes:{request.user.pk}:{int(time.time() // 60)}"
            cache.add(key, 0, timeout=70)
            try:
                count = cache.incr(key)
            except ValueError:  # evicted between add and incr
                count = 1
            if count > limit:
                msg = "Too many changes in a minute. Please wait a moment and try again."
                if "application/json" in request.headers.get("accept", ""):
                    return JsonResponse({"error": msg}, status=429)
                messages.error(request, msg)
                return redirect(safe_next(request, request.headers.get("referer")))
        return view(request, *args, **kwargs)

    return wrapper
