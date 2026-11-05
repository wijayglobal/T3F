"""Staff admin panel at /manage/ — users, adding words, bulk import, reports."""
import functools
import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import AddWordForm, BulkWordsForm
from .management.commands.ingest import save as ingest_save
from .models import Profile, Report, Review, SourceKind, Status, Suggestion, Term
from .telegram import decide_user
from .views import is_verified

User = get_user_model()


def staff_required(view):
    @functools.wraps(view)
    def wrapper(request, *a, **kw):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.get_full_path()}")
        if not request.user.is_staff:
            messages.error(request, "Admins only.")
            return redirect("lexicon:home")
        return view(request, *a, **kw)

    return wrapper


@staff_required
def dashboard(request):
    week = timezone.now() - timezone.timedelta(days=7)
    return render(request, "manage/dashboard.html", {
        "pending_users": Profile.objects.filter(approval="pending", user__is_staff=False).count(),
        "new_users": User.objects.filter(date_joined__gte=week).count(),
        "pending_words": Suggestion.objects.filter(status=Status.PENDING, hidden=False).count(),
        "open_reports": Report.objects.filter(resolved=False).count(),
        "drafts": Suggestion.objects.filter(status=Status.DRAFT).count(),
        "approved": Suggestion.objects.filter(status=Status.APPROVED).count(),
        "terms": Term.objects.count(),
        "users": User.objects.count(),
    })


@staff_required
def users(request):
    f, q = request.GET.get("f", "pending"), request.GET.get("q", "").strip()
    qs = User.objects.select_related("profile").annotate(
        words=Count("suggestions", filter=Q(suggestions__status=Status.APPROVED), distinct=True),
        reviews_n=Count("reviews", distinct=True),
    ).order_by("-date_joined")
    if f == "pending":
        qs = qs.filter(Q(profile__approval="pending") | Q(profile__isnull=True), is_staff=False)
    elif f == "staff":
        qs = qs.filter(is_staff=True)
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q))
    rows = [(u, is_verified(u)) for u in qs[:200]]
    return render(request, "manage/users.html", {"rows": rows, "f": f, "q": q})


@staff_required
@require_POST
def user_action(request, pk):
    user = get_object_or_404(User, pk=pk)
    action = request.POST.get("action")
    Profile.objects.get_or_create(user=user)
    if action in ("approve", "reject"):
        decide_user(user.pk, action == "approve", request.user.username)
        messages.success(request, f"{user.username}: {action}d.")
    elif action in ("make_staff", "remove_staff") and request.user.is_superuser:
        user.is_staff = action == "make_staff"
        user.save(update_fields=["is_staff"])
        messages.success(request, f"{user.username} is {'now' if user.is_staff else 'no longer'} an admin.")
    else:
        messages.error(request, "Not allowed.")
    return redirect(request.META.get("HTTP_REFERER") or "lexicon:manage_users")


@staff_required
def words(request):
    add = AddWordForm(request.POST if request.POST.get("form") == "add" else None)
    bulk = BulkWordsForm(request.POST if request.POST.get("form") == "bulk" else None)
    if request.method == "POST" and request.POST.get("form") == "add" and add.is_valid():
        d = add.cleaned_data
        term, _ = Term.objects.get_or_create(text=d["english"].strip().lower())
        obj, created = Suggestion.objects.get_or_create(
            term=term, tamil=d["tamil"].strip(), region=d["region"],
            defaults=dict(
                roman=d["roman"], note=d["note"], source_kind=d["source_kind"],
                source=request.user.username if d["source_kind"] == SourceKind.SELF else (d["source"] or d["source_ref"]),
                source_url=d["source_url"], source_ref=d["source_ref"], license=d["license"],
                status=Status.APPROVED, author=request.user, decided_at=timezone.now(),
            ),
        )
        messages.success(request, "Added and approved." if created else "That word already exists for this region.")
        return redirect("lexicon:manage_words")
    if request.method == "POST" and request.POST.get("form") == "bulk" and bulk.is_valid():
        d = bulk.cleaned_data
        rows = []
        for line in d["rows"].splitlines():
            parts = [p.strip() for p in re.split(r"\t|\||,", line, maxsplit=1)]
            if len(parts) == 2 and all(parts):
                rows.append({"en": parts[0], "ta": parts[1], "url": d["source_url"]})
        n = ingest_save(
            rows, d["source"], d["license"], kind=d["kind"],
            status=Status.APPROVED if d["approve"] else Status.DRAFT, author=request.user,
        )
        messages.success(request, f"{n} new words added from {len(rows)} lines (duplicates skipped).")
        return redirect("lexicon:manage_words")
    return render(request, "manage/words.html", {"add": add, "bulk": bulk})


@staff_required
def reports(request):
    qs = (
        Report.objects.filter(resolved=False)
        .select_related("suggestion__term", "user")
        .order_by("suggestion_id", "-created")
    )
    return render(request, "manage/reports.html", {"reports": qs[:200]})


@staff_required
@require_POST
def report_action(request, pk):
    r = get_object_or_404(Report.objects.select_related("suggestion"), pk=pk)
    s, action = r.suggestion, request.POST.get("action")
    if action == "hide":
        s.hidden = True
        s.save(update_fields=["hidden"])
    elif action == "reject":
        s.apply_reviews(staff_verdict=Review.REJECT)
    elif action != "dismiss":
        messages.error(request, "Unknown action.")
        return redirect("lexicon:manage_reports")
    s.reports.update(resolved=True)
    messages.success(request, f"{s.term.text} → {s.tamil}: {action}.")
    return redirect("lexicon:manage_reports")
