from django.contrib import admin

from .models import Rating, Relation, Report, Suggestion, Term


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    search_fields = ["text"]
    exclude = ["embedding"]


@admin.register(Suggestion)
class SuggestionAdmin(admin.ModelAdmin):
    list_display = ["tamil", "term", "region", "rating_avg", "rating_count", "hidden", "author"]
    list_filter = ["region", "hidden"]
    search_fields = ["tamil", "term__text"]
    raw_id_fields = ["term", "author"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["suggestion", "reason", "user", "created", "resolved"]
    list_filter = ["reason", "resolved"]
    raw_id_fields = ["suggestion", "user"]


admin.site.register(Rating)
admin.site.register(Relation)
