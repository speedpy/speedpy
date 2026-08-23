"""Check the lockfile against OSV.dev for known vulnerabilities.

Why this exists rather than "read the Dependabot tab":

* it needs **no credentials** — OSV.dev's query API is public, so this runs in CI,
  on a laptop, or from an agent with no GitHub token;
* it reports the **fixed-in version** for each advisory, which is the thing you
  actually need in order to act, and which the alert list does not give you;
* it reads the **lockfile**, so it audits what will be installed rather than what
  the range in `pyproject.toml` permits.

It is deliberately dumb about severity ranking. OSV reports what the upstream
database says, and "HIGH" in a library that only ever sees your own input matters
less than "MODERATE" in the one that decodes images an anonymous visitor uploaded.
Read the package names, not just the labels.

    manage.py audit_dependencies
    manage.py audit_dependencies --fail-on high    # for CI
"""

import json
import pathlib
import tomllib
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/"
TIMEOUT = 60

#: Lowest to highest, so a --fail-on threshold is a simple index comparison.
SEVERITIES = ["unknown", "low", "moderate", "high", "critical"]


class Command(BaseCommand):
    help = "Audit uv.lock against the OSV.dev vulnerability database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lock",
            default=None,
            help="Path to uv.lock (default: BASE_DIR/uv.lock).",
        )
        parser.add_argument(
            "--fail-on",
            choices=SEVERITIES[1:],
            default=None,
            help="Exit non-zero if any advisory is at least this severe.",
        )
        parser.add_argument(
            "--json", action="store_true", help="Machine-readable output."
        )

    def handle(self, *args, **options):
        lock_path = pathlib.Path(
            options["lock"] or pathlib.Path(settings.BASE_DIR) / "uv.lock"
        )
        if not lock_path.exists():
            raise CommandError(f"No lockfile at {lock_path}")

        packages = self._packages(lock_path)
        try:
            findings = self._audit(packages)
        except (urllib.error.URLError, TimeoutError) as exc:
            # A network failure is not a clean bill of health, and a command that
            # printed "0 vulnerabilities" here would be actively harmful.
            raise CommandError(f"Could not reach OSV.dev: {exc}")

        if options["json"]:
            self.stdout.write(json.dumps(findings, indent=2))
        else:
            self._report(len(packages), findings)

        if options["fail_on"]:
            floor = SEVERITIES.index(options["fail_on"])
            worst = max(
                (SEVERITIES.index(a["severity"]) for f in findings for a in f["advisories"]),
                default=0,
            )
            if worst >= floor:
                raise CommandError(
                    f"Advisories at or above '{options['fail_on']}' are present."
                )

    def _packages(self, lock_path):
        with open(lock_path, "rb") as fh:
            lock = tomllib.load(fh)
        return [
            (p["name"], p["version"])
            for p in lock.get("package", [])
            if p.get("version")
        ]

    def _audit(self, packages):
        queries = [
            {"package": {"name": n, "ecosystem": "PyPI"}, "version": v}
            for n, v in packages
        ]
        results = self._post(OSV_BATCH, {"queries": queries})["results"]

        findings = []
        for (name, version), result in zip(packages, results):
            ids = [v["id"] for v in result.get("vulns", [])]
            if not ids:
                continue
            advisories = [self._advisory(vid) for vid in ids]
            # GHSA entries carry a severity label; the PYSEC alias of the same
            # advisory usually does not, so dedupe by CVE to avoid reporting one
            # problem three times.
            findings.append(
                {"package": name, "version": version, "advisories": advisories}
            )
        return findings

    def _advisory(self, vuln_id):
        detail = self._get(OSV_VULN + vuln_id)
        fixed = sorted(
            {
                event["fixed"]
                for affected in detail.get("affected", [])
                for rng in affected.get("ranges", []) or []
                for event in rng.get("events", [])
                if "fixed" in event
            }
        )
        db = detail.get("database_specific") or {}
        severity = str(db.get("severity") or "unknown").lower()
        if severity not in SEVERITIES:
            severity = "unknown"
        cves = [a for a in detail.get("aliases", []) if a.startswith("CVE")]
        return {
            "id": vuln_id,
            "cve": cves[0] if cves else "",
            "severity": severity,
            "fixed_in": fixed,
            "summary": (detail.get("summary") or "").strip(),
        }

    def _post(self, url, payload):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)

    def _get(self, url):
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            return json.load(response)

    def _report(self, scanned, findings):
        if not findings:
            self.stdout.write(
                self.style.SUCCESS(f"{scanned} packages, no known vulnerabilities.")
            )
            return
        self.stdout.write(
            self.style.WARNING(
                f"{scanned} packages, {len(findings)} with advisories:\n"
            )
        )
        for finding in findings:
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"{finding['package']} {finding['version']}"
                )
            )
            seen = set()
            for advisory in finding["advisories"]:
                # One line per distinct CVE; the PYSEC/GHSA pair describes the
                # same problem twice.
                key = advisory["cve"] or advisory["id"]
                if key in seen:
                    continue
                seen.add(key)
                fixed = ", ".join(advisory["fixed_in"]) or "unknown"
                self.stdout.write(
                    f"  [{advisory['severity']:8}] {key:18} fixed in {fixed}"
                )
                if advisory["summary"]:
                    self.stdout.write(f"             {advisory['summary'][:100]}")
            self.stdout.write("")
