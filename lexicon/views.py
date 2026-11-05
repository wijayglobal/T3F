import functools
import hmac
import json
from urllib.parse import urlparse

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape
from django.views.decorators.cache import cache_control
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import ProfileForm, ReportForm, SuggestionForm
from .models import Profile, Rating, Report, Review, SourceKind, Status, Suggestion, Term
from .search import relations_for, search

User = get_user_model()


# ------------------------------------------------------------------ helpers
def is_verified(user):
    """Signed in with a confirmed email address (staff always count)."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or EmailAddress.objects.filter(user=user, verified=True).exists()


def is_approved(user):
    """Admin sign-off. Only enforced when REQUIRE_USER_APPROVAL is on; staff are always approved."""
    if not settings.REQUIRE_USER_APPROVAL or user.is_staff:
        return True
    return Profile.objects.filter(user=user, approval="approved").exists()


def verified_required(view):
    @functools.wraps(view)
    def wrapper(request, *a, **kw):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.get_full_path()}")
        if not is_verified(request.user):
            messages.error(request, "Please confirm your email address first — check your inbox.")
            return redirect("account_email")
        if not is_approved(request.user):
            messages.info(request, "Your account is waiting for an admin to approve it. You can search meanwhile.")
            return redirect("lexicon:home")
        return view(request, *a, **kw)

    return wrapper


def _source_label(s, user):
    if s.source_kind == SourceKind.SELF:
        return user.username
    return s.source_ref or urlparse(s.source_url).netloc or "Link"


def prep(terms, user):
    """Attach `term.sugs`: public suggestions (plus the viewer's own pending ones), best first."""
    uid = user.id if user.is_authenticated else None
    for t in terms:
        visible = [
            s for s in t.suggestions.all()
            if s.is_public or (uid and s.author_id == uid and s.status == Status.PENDING)
        ]
        visible.sort(key=lambda s: (
            s.status != Status.PENDING, s.status == Status.DRAFT,
            s.source_kind == SourceKind.MACHINE, -s.rating_avg, -s.rating_count, s.tamil,
        ))
        t.sugs = visible
    return terms


def _ratings_for(user):
    if user.is_authenticated:
        return dict(Rating.objects.filter(user=user).values_list("suggestion_id", "value"))
    return {}


# ------------------------------------------------------------------ search
def home(request):
    return render(request, "lexicon/home.html", {
        "term_count": Term.objects.count(),
        "suggestion_count": Suggestion.objects.filter(status__in=[Status.APPROVED, Status.DRAFT]).count(),
        "approved_count": Suggestion.objects.filter(status=Status.APPROVED).count(),
    })


def results(request):
    q = request.GET.get("q", "").strip()
    direct, related, relations = search(q) if q else ([], [], {})
    prep(direct + related, request.user)
    return render(request, "lexicon/results.html", {
        "q": q, "direct": direct, "related": related, "relations": relations,
        "user_ratings": _ratings_for(request.user), "count": len(direct),
        "report_form": ReportForm(),
    })


def term_detail(request, pk):
    term = get_object_or_404(Term.objects.prefetch_related("suggestions__author"), pk=pk)
    prep([term], request.user)
    return render(request, "lexicon/term.html", {
        "term": term, "relations": relations_for([term]),
        "user_ratings": _ratings_for(request.user),
        "form": SuggestionForm(), "report_form": ReportForm(),
    })


def suggest(request):
    """Autocomplete endpoint for the search box."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"items": []})
    return JsonResponse({"items": list(Term.objects.filter(text__istartswith=q).values_list("text", flat=True)[:8])})


# ------------------------------------------------------------------ contributing
def _save_suggestion(request, term, form):
    s = form.save(commit=False)
    s.term, s.author = term, request.user
    s.source = _source_label(s, request.user)
    s.status = Status.APPROVED if request.user.is_staff else Status.PENDING
    s.license = "CC BY-SA 4.0 (contributor)"
    if Suggestion.objects.filter(term=term, tamil=s.tamil, region=s.region).exists():
        messages.info(request, "That suggestion already exists for this region. Review or rate it instead.")
        return False
    s.save()
    if s.status == Status.PENDING:
        messages.success(request, "நன்றி! Your suggestion is waiting for review. It goes live once other verified users approve it.")
    else:
        messages.success(request, "நன்றி! Added and approved.")
    return True


@verified_required
@require_POST
def add_suggestion(request, pk):
    term = get_object_or_404(Term, pk=pk)
    form = SuggestionForm(request.POST)
    if form.is_valid():
        _save_suggestion(request, term, form)
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs) or "Please check the form.")
    return redirect("lexicon:term", pk=pk)


@verified_required
def new_term(request):
    """Add an English word that isn't in the dictionary yet, with a first suggestion."""
    initial = {"word": request.GET.get("q", "")}
    if request.method == "POST":
        form = SuggestionForm(request.POST)
        word = request.POST.get("word", "").strip().lower()
        if form.is_valid() and word:
            term, _ = Term.objects.get_or_create(text=word)
            _save_suggestion(request, term, form)
            return redirect("lexicon:term", pk=term.pk)
        messages.error(request, "Both the English word and the Tamil word are required.")
    return render(request, "lexicon/new_term.html", {"form": SuggestionForm(), "initial": initial})


@verified_required
@require_POST
def rate(request, pk):
    s = get_object_or_404(Suggestion, pk=pk)
    if not s.is_public:
        return JsonResponse({"error": "Only live suggestions can be rated."}, status=403)
    try:
        value = int(request.POST.get("value", ""))
    except ValueError:
        value = 0
    if not 1 <= value <= 5:
        return JsonResponse({"error": "value must be 1-5"}, status=400)
    if s.author_id == request.user.id:
        return JsonResponse({"error": "You can't rate your own suggestion."}, status=403)
    Rating.objects.update_or_create(suggestion=s, user=request.user, defaults={"value": value})
    s.refresh_rating()
    return JsonResponse({"avg": s.rating_avg, "count": s.rating_count, "mine": value})


@verified_required
@require_POST
def report(request, pk):
    s = get_object_or_404(Suggestion, pk=pk)
    form = ReportForm(request.POST)
    if form.is_valid():
        Report.objects.update_or_create(
            suggestion=s, user=request.user,
            defaults={"reason": form.cleaned_data["reason"], "comment": form.cleaned_data["comment"]},
        )
        removes = s.reports.filter(reason=Report.Reason.REMOVE, resolved=False).count()
        if removes >= 3 and not s.hidden:
            s.hidden = True
            s.save(update_fields=["hidden"])
        messages.success(request, "Thanks — a moderator will review this.")
    return redirect(request.POST.get("next") or "lexicon:home")


# ------------------------------------------------------------------ review queue
@verified_required
def review_queue(request):
    kind = request.GET.get("kind", "pending")
    reviewed = Review.objects.filter(user=request.user).values("suggestion_id")
    qs = (
        Suggestion.objects.filter(hidden=False)
        .exclude(author=request.user)
        .exclude(id__in=reviewed)
        .select_related("term", "author")
    )
    if kind == "pending":
        qs = qs.filter(status=Status.PENDING)
    elif kind == "machine":
        qs = qs.filter(status=Status.DRAFT, source_kind=SourceKind.MACHINE)
    elif kind == "ocr":
        qs = qs.filter(status=Status.DRAFT, source_kind=SourceKind.BOOK)
    else:
        qs = qs.filter(status__in=[Status.PENDING, Status.DRAFT])
    qs = qs.annotate(
        prio=Case(When(status=Status.PENDING, then=Value(0)), default=Value(1), output_field=IntegerField())
    ).order_by("prio", "?" if kind != "pending" else "created")
    counts = {
        "pending": Suggestion.objects.filter(status=Status.PENDING, hidden=False).exclude(author=request.user).exclude(id__in=reviewed).count(),
    }
    return render(request, "lexicon/review.html", {
        "items": list(qs[:15]), "kind": kind, "counts": counts,
        "my_reviews": Review.objects.filter(user=request.user).count(),
        "threshold": settings.REVIEW_THRESHOLD,
    })


@verified_required
@require_POST
def review_vote(request, pk):
    s = get_object_or_404(Suggestion, pk=pk, hidden=False)
    verdict = request.POST.get("verdict")
    if verdict not in (Review.ACCEPT, Review.REJECT):
        return JsonResponse({"error": "verdict must be accept or reject"}, status=400)
    if s.author_id == request.user.id:
        return JsonResponse({"error": "You can't review your own suggestion."}, status=403)
    if s.status not in (Status.PENDING, Status.DRAFT):
        return JsonResponse({"error": "This suggestion has already been decided."}, status=409)
    Review.objects.update_or_create(
        suggestion=s, user=request.user,
        defaults={"verdict": verdict, "comment": request.POST.get("comment", "")[:300]},
    )
    s.apply_reviews(staff_verdict=verdict if request.user.is_staff else None)
    agg = s.reviews.aggregate(
        a=Count("id", filter=Q(verdict=Review.ACCEPT)), r=Count("id", filter=Q(verdict=Review.REJECT))
    )
    return JsonResponse({"status": s.status, "accepts": agg["a"], "rejects": agg["r"]})


# ------------------------------------------------------------------ profiles
def user_stats(user):
    mine = Suggestion.objects.filter(author=user)
    approved = mine.filter(status=Status.APPROVED)
    reviews = Review.objects.filter(user=user)
    decided = reviews.filter(suggestion__status__in=[Status.APPROVED, Status.REJECTED])
    agreed = decided.filter(
        Q(verdict=Review.ACCEPT, suggestion__status=Status.APPROVED)
        | Q(verdict=Review.REJECT, suggestion__status=Status.REJECTED)
    ).count()
    rated = approved.filter(rating_count__gt=0)
    avg = round(sum(s.rating_avg for s in rated) / rated.count(), 1) if rated.exists() else None
    n_approved, n_reviews = approved.count(), reviews.count()
    stats = {
        "approved": n_approved,
        "pending": mine.filter(status=Status.PENDING).count(),
        "rejected": mine.filter(status=Status.REJECTED).count(),
        "reviews": n_reviews,
        "agreement": round(100 * agreed / decided.count()) if decided.exists() else None,
        "avg_rating": avg,
        "ratings_given": Rating.objects.filter(user=user).count(),
        "points": 10 * n_approved + n_reviews + agreed,
    }
    badges = []
    if is_verified(user):
        badges.append(("✔", "Verified", "Confirmed email address"))
    if n_approved >= 1:
        badges.append(("ஃ", "Contributor", "Has an approved suggestion"))
    if n_approved >= 10:
        badges.append(("✍", "Wordsmith", "10+ approved suggestions"))
    if n_reviews >= 25:
        badges.append(("✓", "Reviewer", "25+ reviews"))
    if n_reviews >= 100 and (stats["agreement"] or 0) >= 80:
        badges.append(("★", "Trusted reviewer", "100+ reviews, 80%+ agreement"))
    return stats, badges


def _public_profile(username):
    user = get_object_or_404(User, username=username, is_active=True)
    profile, _ = Profile.objects.get_or_create(user=user)
    return user, profile


def profile(request, username):
    user, prof = _public_profile(username)
    own = request.user == user
    if not prof.public and not own:
        raise Http404
    stats, badges = user_stats(user)
    words = (
        Suggestion.objects.filter(author=user, status=Status.APPROVED, hidden=False)
        .select_related("term").order_by("-decided_at", "-created")[:30]
    )
    base = settings.SITE_URL.rstrip("/")
    snippets = {
        "iframe": f'<iframe src="{base}/u/{user.username}/embed/" width="360" height="180" style="border:0" loading="lazy" title="Kalaichol contributions"></iframe>',
        "badge": f'<a href="{base}/u/{user.username}/"><img src="{base}/u/{user.username}/badge.svg" alt="Kalaichol contributor"></a>',
        "markdown": f"[![Kalaichol contributor]({base}/u/{user.username}/badge.svg)]({base}/u/{user.username}/)",
    }
    return render(request, "lexicon/profile.html", {
        "p_user": user, "prof": prof, "stats": stats, "badges": badges, "words": words,
        "own": own, "snippets": snippets, "verified": is_verified(user),
    })


@verified_required
def edit_profile(request):
    prof, _ = Profile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST or None, instance=prof)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile saved.")
        return redirect("lexicon:profile", username=request.user.username)
    return render(request, "lexicon/profile_edit.html", {"form": form})


@xframe_options_exempt
def embed_card(request, username):
    user, prof = _public_profile(username)
    if not prof.public:
        raise Http404
    stats, badges = user_stats(user)
    return render(request, "lexicon/embed.html", {"p_user": user, "prof": prof, "stats": stats, "badges": badges})


@cache_control(max_age=600, public=True)
def badge_svg(request, username):
    user, prof = _public_profile(username)
    if not prof.public:
        raise Http404
    stats, _ = user_stats(user)
    label = "கலைச்சொல்"
    value = f"{stats['approved']} words · {stats['reviews']} reviews"
    w1, w2 = 92, 12 + 7 * len(value)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w1 + w2}" height="24" role="img" aria-label="{escape(label)}: {escape(value)}">'
        f'<rect width="{w1}" height="24" rx="4" fill="#c3161c"/><rect x="{w1}" width="{w2}" height="24" rx="4" fill="#f4c430"/>'
        f'<rect x="{w1 - 4}" width="8" height="24" fill="#c3161c"/><rect x="{w1 - 4 + 4}" width="4" height="24" fill="#f4c430"/>'
        f'<g font-family="Verdana,sans-serif" font-size="12" text-anchor="middle">'
        f'<text x="{w1 / 2}" y="16" fill="#fff">ஃ {escape(label)}</text>'
        f'<text x="{w1 + w2 / 2}" y="16" fill="#17110e">{escape(value)}</text></g></svg>'
    )
    return HttpResponse(svg, content_type="image/svg+xml")


# ------------------------------------------------------------------ Telegram webhook
@csrf_exempt
@require_POST
def telegram_webhook(request, secret):
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if not expected or not hmac.compare_digest(secret, expected):
        raise Http404
    from .telegram import handle_update

    try:
        handle_update(json.loads(request.body))
    except Exception:
        pass  # always 200 so Telegram doesn't retry forever
    return HttpResponse("ok")


# ------------------------------------------------------------------ contributors
def contributors(request):
    people = (
        User.objects.filter(is_active=True)
        .filter(Q(profile__public=True) | Q(profile__isnull=True))
        .annotate(
            words=Count("suggestions", filter=Q(suggestions__status=Status.APPROVED, suggestions__hidden=False), distinct=True),
            reviews_n=Count("reviews", distinct=True),
        )
        .filter(Q(words__gt=0) | Q(reviews_n__gt=0) | Q(is_staff=True))
    )
    rows = sorted(
        ({"user": u, "role": "Admin" if u.is_staff else "Contributor", "words": u.words,
          "reviews": u.reviews_n, "points": 10 * u.words + u.reviews_n} for u in people),
        key=lambda r: (r["role"] != "Admin", -r["points"], r["user"].username),
    )
    return render(request, "lexicon/contributors.html", {"rows": rows})
