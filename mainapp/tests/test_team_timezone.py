"""Team-local time zone: the field the daily cap / scheduler read.

The default and the selector shortlist are overridable via settings
(DEFAULT_TEAM_TIMEZONE, TEAM_TIMEZONE_CHOICES). See mainapp/timezones.py.
"""

import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from mainapp.models import Team
from mainapp.timezones import (
    FALLBACK_TEAM_TIMEZONE,
    get_default_team_timezone,
    is_valid_timezone,
    tz_choices,
)


class TeamTimezoneModelTests(TestCase):
    def test_defaults_to_utc_fallback(self):
        team = Team.objects.create(name="Acme", slug="acme")
        self.assertEqual(team.timezone, FALLBACK_TEAM_TIMEZONE)

    @override_settings(DEFAULT_TEAM_TIMEZONE="Europe/Berlin")
    def test_default_is_overridable_via_settings(self):
        # Callable default reads the setting at row creation.
        self.assertEqual(get_default_team_timezone(), "Europe/Berlin")
        team = Team.objects.create(name="B", slug="b")
        self.assertEqual(team.timezone, "Europe/Berlin")

    def test_invalid_timezone_rejected(self):
        team = Team(name="Bad", slug="bad", timezone="Mars/Phobos")
        with self.assertRaises(ValidationError):
            team.full_clean()

    def test_local_today_respects_timezone(self):
        # 2026-01-01 23:30 UTC is already 2026-01-02 in Tokyo (UTC+9).
        moment = datetime.datetime(2026, 1, 1, 23, 30, tzinfo=datetime.timezone.utc)
        tokyo = Team.objects.create(name="T", slug="t", timezone="Asia/Tokyo")
        utc_team = Team.objects.create(name="U", slug="u", timezone="UTC")
        self.assertEqual(tokyo.local_today(moment), datetime.date(2026, 1, 2))
        self.assertEqual(utc_team.local_today(moment), datetime.date(2026, 1, 1))

    def test_tzinfo_falls_back_on_bad_value(self):
        # A row that slipped past validation must not crash the send path.
        team = Team.objects.create(name="Acme", slug="acme")
        Team.objects.filter(pk=team.pk).update(timezone="not/a/zone")
        team.refresh_from_db()
        self.assertEqual(str(team.tzinfo()), FALLBACK_TEAM_TIMEZONE)


class TzChoicesTests(TestCase):
    def test_bare_names_and_current_first(self):
        choices = tz_choices(include="Antarctica/Troll")
        self.assertEqual(choices[0], ("Antarctica/Troll", "Antarctica/Troll"))
        # labels are bare names (no offset)
        self.assertTrue(all(v == label for v, label in choices))

    def test_dedupes_include_already_listed(self):
        choices = tz_choices(include="UTC")
        values = [v for v, _ in choices]
        self.assertEqual(values.count("UTC"), 1)

    @override_settings(TEAM_TIMEZONE_CHOICES=[])
    def test_never_empty_even_with_blank_setting(self):
        choices = tz_choices()
        self.assertTrue(choices)  # falls back to at least UTC
        self.assertIn(("UTC", "UTC"), choices)

    def test_invalid_include_does_not_crash(self):
        # A bad stored value is still offered so the page renders; no ZoneInfo().
        choices = tz_choices(include="not/a/zone")
        self.assertEqual(choices[0], ("not/a/zone", "not/a/zone"))

    def test_is_valid_timezone(self):
        self.assertTrue(is_valid_timezone("Europe/Berlin"))
        self.assertFalse(is_valid_timezone("Mars/Phobos"))
        self.assertFalse(is_valid_timezone(""))
