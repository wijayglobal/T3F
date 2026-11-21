from django.contrib import admin

from .models import Rating, Relation, Report, Suggestion, SuggestionRelation, TamilForm, TamilSense, Term


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    search_fields = ["text"]
    exclude = ["embedding"]


@admin.register(Suggestion)
class SuggestionAdmin(admin.ModelAdmin):
    list_display = ["tamil", "term", "domain", "register", "status", "rating_avg", "hidden", "author"]
    list_filter = ["status", "source_kind", "register", "hidden", "domain"]
    search_fields = ["tamil", "term__text"]
    raw_id_fields = ["term", "author"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["suggestion", "reason", "user", "created", "resolved"]
    list_filter = ["reason", "resolved"]
    raw_id_fields = ["suggestion", "user"]


admin.site.register(Rating)
admin.site.register(Relation)


@admin.register(SuggestionRelation)
class SuggestionRelationAdmin(admin.ModelAdmin):
    list_display = ["suggestion", "kind", "word"]
    search_fields = ["word", "suggestion__tamil"]
    raw_id_fields = ["suggestion"]


@admin.register(TamilSense)
class TamilSenseAdmin(admin.ModelAdmin):
    list_display = ["word", "gloss", "pos", "register", "domain", "source"]
    list_filter = ["gloss_lang", "register", "source"]
    search_fields = ["word", "gloss"]


@admin.register(TamilForm)
class TamilFormAdmin(admin.ModelAdmin):
    list_display = ["form", "lemma", "tags"]
    search_fields = ["form", "lemma"]
