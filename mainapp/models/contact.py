from django.db import models
from django.utils.translation import gettext_lazy as _

from speedpycom.models import BaseModel


class ContactSubmission(BaseModel):
    class CompanySize(models.TextChoices):
        SMALL = "1-10", _("1-10")
        MEDIUM = "11-30", _("11-30")
        LARGE = "31-50", _("31-50")

    class TeamCategory(models.TextChoices):
        ENGINEERING = "engineering", _("Engineering")
        DESIGN = "design", _("Design")

    class ProjectBudget(models.TextChoices):
        BUDGET_20K = "20000", _("$20,000+")
        BUDGET_50K = "50000", _("$50,000+")

    name = models.CharField(_("Full Name"), max_length=120)
    company = models.CharField(_("Company Name"), max_length=160)
    email = models.EmailField(_("Work Email"))
    phone = models.CharField(_("Phone Number"), max_length=40)
    company_size = models.CharField(
        _("Company Size"),
        max_length=16,
        choices=CompanySize.choices,
        blank=True,
    )
    team = models.CharField(
        _("Team"),
        max_length=32,
        choices=TeamCategory.choices,
        blank=True,
    )
    project_budget = models.CharField(
        _("Project Budget"),
        max_length=16,
        choices=ProjectBudget.choices,
    )
    message = models.TextField(_("Message"))

    class Meta:
        verbose_name = _("Contact Submission")
        verbose_name_plural = _("Contact Submissions")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} <{self.email}>"
