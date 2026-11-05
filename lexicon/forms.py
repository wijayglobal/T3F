from django import forms

from .models import Profile, Region, Report, SourceKind, Suggestion


class SuggestionForm(forms.ModelForm):
    source_kind = forms.ChoiceField(
        label="Source",
        choices=[(SourceKind.SELF, SourceKind.SELF.label), (SourceKind.LINK, SourceKind.LINK.label)],
        initial=SourceKind.SELF,
        widget=forms.RadioSelect,
    )

    def clean(self):
        data = super().clean()
        if data.get("source_kind") == SourceKind.LINK and not (
            data.get("source_url") or data.get("source_ref")
        ):
            self.add_error("source_url", "Give a link or a reference for where this word comes from.")
        return data

    class Meta:
        model = Suggestion
        fields = ["tamil", "roman", "region", "source_kind", "source_url", "source_ref", "note"]
        widgets = {
            "tamil": forms.TextInput(attrs={"placeholder": "தமிழ் சொல் · Tamil word", "lang": "ta"}),
            "roman": forms.TextInput(attrs={"placeholder": "Tanglish spelling (optional)"}),
            "source_url": forms.URLInput(attrs={"placeholder": "https://… (link to the source)"}),
            "source_ref": forms.TextInput(attrs={"placeholder": "or a reference: book title, page (optional if link given)"}),
            "note": forms.Textarea(attrs={"rows": 2, "placeholder": "Usage note or example sentence (optional)"}),
        }


class ReportForm(forms.Form):
    reason = forms.ChoiceField(choices=Report.Reason.choices)
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["display_name", "bio", "website", "public"]
        labels = {"public": "Public profile, badge and embed"}


class AddWordForm(forms.Form):
    english = forms.CharField(max_length=120)
    tamil = forms.CharField(max_length=200, widget=forms.TextInput(attrs={"lang": "ta"}))
    roman = forms.CharField(max_length=200, required=False)
    region = forms.ChoiceField(choices=Region.choices, initial=Region.COMMON)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    source_kind = forms.ChoiceField(
        choices=[(SourceKind.SELF, "My own word"), (SourceKind.BOOK, "Book / dictionary"), (SourceKind.WEB, "Web page"), (SourceKind.LINK, "Other reference")],
    )
    source = forms.CharField(max_length=200, required=False, label="Source name (book title, site…)")
    source_url = forms.URLField(required=False)
    source_ref = forms.CharField(max_length=200, required=False, label="Reference (page, section…)")
    license = forms.CharField(max_length=60, required=False, initial="CC BY-SA 4.0")

    def clean(self):
        d = super().clean()
        if d.get("source_kind") != SourceKind.SELF and not (d.get("source") or d.get("source_url") or d.get("source_ref")):
            self.add_error("source", "Say where this word comes from.")
        return d


class BulkWordsForm(forms.Form):
    rows = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 10, "placeholder": "one pair per line:\nserver<TAB>வழங்கி\nnetwork | வலையமைப்பு"}),
        help_text="English and Tamil separated by a tab, a pipe (|) or a comma.",
    )
    source = forms.CharField(max_length=200, label="Source name")
    source_url = forms.URLField(required=False)
    license = forms.CharField(max_length=60, initial="CC BY-SA 4.0")
    kind = forms.ChoiceField(choices=[(SourceKind.BOOK, "Book / dictionary"), (SourceKind.WEB, "Web page"), (SourceKind.LINK, "Other reference")])
    approve = forms.BooleanField(required=False, initial=True, label="Mark as approved (otherwise unreviewed drafts)")
