"""Team timezone UI: the settings selector and create-time auto-detection.

Validation split: settings is STRICT (explicit dropdown choice), creation is
LENIENT (browser-detected input must never block team creation).
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from mainapp.forms.teams import TeamCreateForm, TeamSettingsForm
from mainapp.models import Team, TeamMembership
from usermodel.models import User


class SettingsSelectorTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pass123"
        )
        self.team = Team.objects.create(name="Acme", slug="acme", timezone="Asia/Tokyo")
        TeamMembership.objects.create(team=self.team, user=self.owner, role="owner")
        self.url = reverse("team_settings", kwargs={"team_id": self.team.pk})

    def test_get_renders_dropdown_with_current_selected(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="timezone"')
        self.assertContains(resp, "Asia/Tokyo")

    def test_owner_saves_valid_zone(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            self.url,
            {"name": "Acme", "slug": "acme", "timezone": "Europe/Berlin"},
        )
        self.assertEqual(resp.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.timezone, "Europe/Berlin")

    def test_missing_timezone_is_an_error(self):
        form = TeamSettingsForm(
            data={"name": "Acme", "slug": "acme"}, instance=self.team
        )
        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)

    def test_unlisted_valid_zone_is_rejected_as_tamper(self):
        # ChoiceField only accepts what the menu offered.
        form = TeamSettingsForm(
            data={"name": "Acme", "slug": "acme", "timezone": "America/Adak"},
            instance=self.team,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)

    def test_stored_offlist_zone_stays_selectable(self):
        self.team.timezone = "Antarctica/Troll"  # valid, not on the shortlist
        self.team.save()
        form = TeamSettingsForm(instance=self.team)
        values = [v for v, _ in form.fields["timezone"].choices]
        self.assertIn("Antarctica/Troll", values)

    def test_invalid_stored_zone_does_not_crash_get(self):
        Team.objects.filter(pk=self.team.pk).update(timezone="not/a/zone")
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "not/a/zone")


class CreateAutodetectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="u@example.com", password="pass123"
        )

    def _create(self, tz):
        data = {"name": "New Team", "slug": "new-team"}
        if tz is not None:
            data["timezone"] = tz
        form = TeamCreateForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def test_valid_detected_zone_is_stored(self):
        team = self._create("America/New_York")
        self.assertEqual(team.timezone, "America/New_York")

    @override_settings(DEFAULT_TEAM_TIMEZONE="Europe/Belgrade")
    def test_blank_falls_back_to_default(self):
        team = self._create("")
        self.assertEqual(team.timezone, "Europe/Belgrade")

    @override_settings(DEFAULT_TEAM_TIMEZONE="Europe/Belgrade")
    def test_invalid_falls_back_to_default(self):
        team = self._create("not/a/zone")
        self.assertEqual(team.timezone, "Europe/Belgrade")

    def test_create_page_has_hidden_field_and_detect_js(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("team_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="id_timezone"')
        self.assertContains(resp, "resolvedOptions().timeZone")
