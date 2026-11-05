from django.urls import path

from . import manage_views, views

app_name = "lexicon"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.results, name="results"),
    path("suggest/", views.suggest, name="suggest"),
    path("term/<int:pk>/", views.term_detail, name="term"),
    path("term/<int:pk>/suggest/", views.add_suggestion, name="add_suggestion"),
    path("new/", views.new_term, name="new_term"),
    path("suggestion/<int:pk>/rate/", views.rate, name="rate"),
    path("suggestion/<int:pk>/report/", views.report, name="report"),
    path("review/", views.review_queue, name="review"),
    path("review/<int:pk>/", views.review_vote, name="review_vote"),
    path("profile/edit/", views.edit_profile, name="edit_profile"),
    path("telegram/webhook/<str:secret>/", views.telegram_webhook, name="telegram_webhook"),
    path("contributors/", views.contributors, name="contributors"),
    path("manage/", manage_views.dashboard, name="manage"),
    path("manage/users/", manage_views.users, name="manage_users"),
    path("manage/users/<int:pk>/", manage_views.user_action, name="manage_user_action"),
    path("manage/words/", manage_views.words, name="manage_words"),
    path("manage/reports/", manage_views.reports, name="manage_reports"),
    path("manage/reports/<int:pk>/", manage_views.report_action, name="manage_report_action"),
    path("u/<str:username>/", views.profile, name="profile"),
    path("u/<str:username>/embed/", views.embed_card, name="embed"),
    path("u/<str:username>/badge.svg", views.badge_svg, name="badge"),
]
