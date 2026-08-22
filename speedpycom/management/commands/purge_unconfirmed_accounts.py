"""Run (or preview) the unconfirmed-account purge by hand.

``--dry-run`` is the point of this command: it lists exactly which accounts the
periodic task would delete, which is the only responsible way to switch the
purge on for the first time.
"""

from django.core.management.base import BaseCommand

from speedpycom.services.account_purge import get_purge


class Command(BaseCommand):
    help = "Delete signups that never confirmed an email address."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be deleted and delete nothing.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS for this run.",
        )
        parser.add_argument(
            "--limit", type=int, default=None, help="Stop after this many accounts."
        )

    def handle(self, *args, **options):
        purge = get_purge(days=options["days"])
        if not purge.enabled:
            self.stdout.write(
                "The purge is off. Set SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS "
                "(or pass --days) to switch it on."
            )
            return

        if options["dry_run"]:
            rows = purge.queryset()
            if options["limit"]:
                rows = rows[: options["limit"]]
            for user in rows:
                self.stdout.write(f"{user.pk}  {user.email}  joined {user.date_joined}")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(list(rows))} account(s) match at {purge.days} days. "
                    "Nothing was deleted."
                )
            )
            return

        report = purge.run(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {report['purged']} of {report['matched']} matched; "
                f"{report['failed']} failed."
            )
        )
