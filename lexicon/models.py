from django.conf import settings
from django.db import models
from django.db.models import Avg, Count


class Region(models.TextChoices):
    COMMON = "common", "பொது வழக்கு · Common"
    CHENNAI = "chennai", "சென்னை · Chennai"
    MADURAI = "madurai", "மதுரை · Madurai"
    KONGU = "kongu", "கொங்கு · Kongu"
    NELLAI = "nellai", "நெல்லை · Nellai"
    JAFFNA = "jaffna", "யாழ்ப்பாணம் · Jaffna"
    MALAYSIA = "malaysia", "மலேசியா · Malaysia"
    SINGAPORE = "singapore", "சிங்கப்பூர் · Singapore"
    FORMAL = "formal", "இலக்கியம் · Literary"


class SourceKind(models.TextChoices):
    SELF = "self", "என் சொந்த சொல் · My own word"
    LINK = "link", "இணைப்பு · Link / reference"
    BOOK = "book", "நூல் · Book"
    WIKTIONARY = "wiktionary", "Wiktionary"
    WEB = "web", "இணையம் · Web source"
    MACHINE = "machine", "இயந்திர வரைவு · Machine draft (unreviewed)"


class Status(models.TextChoices):
    PENDING = "pending", "காத்திருப்பு · Awaiting review"  # user-suggested, not public yet
    DRAFT = "draft", "வரைவு · Unreviewed draft"  # machine / OCR / scraped, public but flagged
    APPROVED = "approved", "ஏற்கப்பட்டது · Approved"
    REJECTED = "rejected", "மறுக்கப்பட்டது · Rejected"


class Term(models.Model):
    """An English headword users look up (e.g. "server")."""

    text = models.CharField(max_length=120, unique=True)
    domain = models.CharField(max_length=120, blank=True)
    gloss = models.CharField(max_length=300, blank=True)  # short English meaning (WordNet)
    embedding = models.BinaryField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["text"]

    def __str__(self):
        return self.text

    def ordered_suggestions(self):
        """Human-sourced first, best rated first; machine drafts last."""
        return sorted(
            (s for s in self.suggestions.all() if s.is_public),
            key=lambda s: (s.source_kind == SourceKind.MACHINE, -s.rating_avg, -s.rating_count, s.tamil),
        )


class Suggestion(models.Model):
    """A Tamil rendering of a Term, from a user or a seed dataset."""

    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="suggestions")
    tamil = models.CharField(max_length=200, db_index=True)
    roman = models.CharField(max_length=200, blank=True)
    region = models.CharField(max_length=20, choices=Region.choices, default=Region.COMMON)
    pos = models.CharField(max_length=30, blank=True)
    note = models.TextField(blank=True)
    source = models.CharField(max_length=200, blank=True)  # human-readable label
    source_kind = models.CharField(max_length=12, choices=SourceKind.choices, default=SourceKind.SELF)
    source_url = models.URLField(max_length=500, blank=True)
    source_ref = models.CharField(max_length=200, blank=True)  # e.g. "TVA_BOK_0006216, p. 223"
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="suggestions",
    )
    created = models.DateTimeField(auto_now_add=True)
    hidden = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    license = models.CharField(max_length=60, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    rating_avg = models.FloatField(default=0)
    rating_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-rating_avg", "-rating_count", "tamil"]
        constraints = [
            models.UniqueConstraint(
                fields=["term", "tamil", "region"], name="uniq_term_tamil_region"
            )
        ]

    def __str__(self):
        return f"{self.term} → {self.tamil} ({self.region})"

    @property
    def is_public(self):
        return not self.hidden and self.status in (Status.APPROVED, Status.DRAFT)

    def apply_reviews(self, staff_verdict=None):
        """Approve / reject from review votes. Staff verdicts decide immediately."""
        from django.conf import settings as dj
        from django.utils import timezone

        if self.status in (Status.APPROVED, Status.REJECTED) and staff_verdict is None:
            return
        if staff_verdict:
            new = Status.APPROVED if staff_verdict == Review.ACCEPT else Status.REJECTED
        else:
            agg = self.reviews.aggregate(
                a=Count("id", filter=models.Q(verdict=Review.ACCEPT)),
                r=Count("id", filter=models.Q(verdict=Review.REJECT)),
            )
            need = getattr(dj, "REVIEW_THRESHOLD", 2)
            if agg["a"] - agg["r"] >= need:
                new = Status.APPROVED
            elif agg["r"] - agg["a"] >= need:
                new = Status.REJECTED
            else:
                return
        self.status, self.decided_at = new, timezone.now()
        self.save(update_fields=["status", "decided_at"])

    def refresh_rating(self):
        agg = self.ratings.aggregate(a=Avg("value"), c=Count("id"))
        self.rating_avg = round(agg["a"] or 0, 2)
        self.rating_count = agg["c"]
        self.save(update_fields=["rating_avg", "rating_count"])


class Rating(models.Model):
    suggestion = models.ForeignKey(Suggestion, on_delete=models.CASCADE, related_name="ratings")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    value = models.PositiveSmallIntegerField()  # 1..5
    created = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["suggestion", "user"], name="one_rating_per_user"),
            models.CheckConstraint(
                condition=models.Q(value__gte=1, value__lte=5), name="rating_1_to_5"
            ),
        ]


class Relation(models.Model):
    """Synonym / antonym link between two Tamil words."""

    SYNONYM, ANTONYM = "syn", "ant"
    KINDS = [(SYNONYM, "Synonym"), (ANTONYM, "Antonym")]

    word = models.CharField(max_length=200, db_index=True)
    other = models.CharField(max_length=200, db_index=True)
    kind = models.CharField(max_length=3, choices=KINDS)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["word", "other", "kind"], name="uniq_relation")
        ]


class Report(models.Model):
    """User flag on a suggestion (the wireframe's 'report' button)."""

    class Reason(models.TextChoices):
        REMOVE = "remove", "உடனடியாக நீக்க · Remove immediately"
        WRONG = "wrong", "பிழையான தகவல் · Incorrect info"
        REVIEW = "review", "நிபுணர் ஆய்வு தேவை · Needs expert review"

    suggestion = models.ForeignKey(Suggestion, on_delete=models.CASCADE, related_name="reports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reason = models.CharField(max_length=10, choices=Reason.choices)
    comment = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["suggestion", "user"], name="one_report_per_user")
        ]


class Review(models.Model):
    """A verified user's tick (accept) or cross (reject) on a suggestion."""

    ACCEPT, REJECT = "accept", "reject"
    VERDICTS = [(ACCEPT, "Correct"), (REJECT, "Incorrect")]

    suggestion = models.ForeignKey(Suggestion, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    verdict = models.CharField(max_length=6, choices=VERDICTS)
    comment = models.CharField(max_length=300, blank=True)
    created = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["suggestion", "user"], name="one_review_per_user")
        ]


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=80, blank=True)
    bio = models.CharField(max_length=300, blank=True)
    website = models.URLField(blank=True)
    public = models.BooleanField(default=True, help_text="Allow a public profile page, badge and embed.")
    # admin sign-off for new accounts (only enforced when REQUIRE_USER_APPROVAL is on)
    APPROVAL = [("pending", "Awaiting approval"), ("approved", "Approved"), ("rejected", "Rejected")]
    approval = models.CharField(max_length=10, choices=APPROVAL, default="pending", db_index=True)
    approved_by = models.CharField(max_length=80, blank=True)  # admin username or "telegram:@name"
    approved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.display_name or self.user.username
