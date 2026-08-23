"""`manage.py audit_dependencies` — the lockfile against OSV.dev.

Every test mocks the network. That is not squeamishness: a test that really
called OSV.dev would fail the day a new advisory landed against a pinned
package, which is a test that cries wolf about something it was never checking.
The command's job is to read the lockfile, ask, and report honestly; whether
today's answer is empty is not its behaviour.

The case worth the most attention is the last one. A command that printed
"no known vulnerabilities" when it could not reach the database would be worse
than no command at all.
"""

import json
import pathlib
import tempfile
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase
from io import StringIO

LOCK = """
version = 1

[[package]]
name = "django"
version = "6.0.3"

[[package]]
name = "pillow"
version = "12.1.1"

[[package]]
name = "safe-thing"
version = "1.0.0"
"""


def advisory(vuln_id, severity, cve, fixed):
    return {
        "id": vuln_id,
        "aliases": [cve],
        "summary": f"{vuln_id} summary",
        "database_specific": {"severity": severity},
        "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": fixed}]}]}],
    }


class AuditCommandTests(SimpleTestCase):
    def setUp(self):
        self.lock = pathlib.Path(tempfile.mkdtemp()) / "uv.lock"
        self.lock.write_text(LOCK)

    def run_command(self, batch, details, **options):
        """Patch the two OSV endpoints the command uses."""

        def fake_post(self, url, payload):
            return batch

        def fake_get(self, url):
            return details[url.rsplit("/", 1)[-1]]

        out = StringIO()
        with mock.patch(
            "speedpycom.management.commands.audit_dependencies.Command._post",
            fake_post,
        ):
            with mock.patch(
                "speedpycom.management.commands.audit_dependencies.Command._get",
                fake_get,
            ):
                call_command(
                    "audit_dependencies", lock=str(self.lock), stdout=out, **options
                )
        return out.getvalue()

    def clean_batch(self):
        return {"results": [{}, {}, {}]}

    def dirty(self):
        batch = {
            "results": [
                {"vulns": [{"id": "GHSA-django"}]},
                {"vulns": [{"id": "GHSA-pillow"}]},
                {},
            ]
        }
        details = {
            "GHSA-django": advisory("GHSA-django", "HIGH", "CVE-1", "6.0.4"),
            "GHSA-pillow": advisory("GHSA-pillow", "MODERATE", "CVE-2", "12.3.0"),
        }
        return batch, details

    def test_a_clean_lockfile_says_so_and_counts_what_it_checked(self):
        output = self.run_command(self.clean_batch(), {})
        self.assertIn("3 packages", output)
        self.assertIn("no known vulnerabilities", output)

    def test_it_names_the_package_the_version_and_the_FIX(self):
        """The fixed-in version is the whole reason this exists rather than
        reading an alert list — it is the part you need in order to act."""
        batch, details = self.dirty()
        output = self.run_command(batch, details)
        self.assertIn("django 6.0.3", output)
        self.assertIn("fixed in 6.0.4", output)
        self.assertIn("pillow 12.1.1", output)
        self.assertIn("fixed in 12.3.0", output)
        self.assertIn("CVE-1", output)

    def test_a_package_with_no_advisories_is_not_listed(self):
        batch, details = self.dirty()
        self.assertNotIn("safe-thing", self.run_command(batch, details))

    def test_the_same_cve_under_two_ids_is_reported_once(self):
        """OSV returns GHSA and PYSEC entries for the same problem. Listing both
        triples the apparent size of the backlog."""
        batch = {"results": [{"vulns": [{"id": "GHSA-x"}, {"id": "PYSEC-x"}]}, {}, {}]}
        details = {
            "GHSA-x": advisory("GHSA-x", "HIGH", "CVE-9", "6.0.4"),
            "PYSEC-x": advisory("PYSEC-x", "unknown", "CVE-9", "6.0.4"),
        }
        output = self.run_command(batch, details)
        self.assertEqual(output.count("CVE-9"), 1)

    def test_fail_on_raises_at_or_above_the_threshold(self):
        batch, details = self.dirty()
        with self.assertRaises(CommandError):
            self.run_command(batch, details, fail_on="high")

    def test_fail_on_is_quiet_below_the_threshold(self):
        batch, details = self.dirty()
        self.run_command(batch, details, fail_on="critical")  # must not raise

    def test_fail_on_is_quiet_on_a_clean_lockfile(self):
        self.run_command(self.clean_batch(), {}, fail_on="low")

    def test_json_output_is_machine_readable(self):
        batch, details = self.dirty()
        parsed = json.loads(self.run_command(batch, details, **{"json": True}))
        self.assertEqual({f["package"] for f in parsed}, {"django", "pillow"})

    def test_a_missing_lockfile_is_an_error_not_a_pass(self):
        with self.assertRaises(CommandError):
            call_command("audit_dependencies", lock="/nowhere/uv.lock")

    def test_an_unreachable_database_is_an_ERROR_not_a_clean_bill(self):
        """The most important one. A command that printed "no known
        vulnerabilities" because the network was down would be worse than no
        command at all — it would launder an outage into reassurance."""
        import urllib.error

        with mock.patch(
            "speedpycom.management.commands.audit_dependencies.Command._post",
            side_effect=urllib.error.URLError("offline"),
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command("audit_dependencies", lock=str(self.lock))
        self.assertIn("OSV", str(ctx.exception))
