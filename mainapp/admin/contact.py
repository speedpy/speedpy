from django.contrib import admin

from mainapp.models import ContactSubmission


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "company", "project_budget", "created_at")
    list_filter = ("company_size", "team", "project_budget", "created_at")
    search_fields = ("name", "email", "company", "phone", "message")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)
