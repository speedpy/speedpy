"""Deleting signups that can never become accounts.

Email verification is mandatory, so a signup whose address is never confirmed
leaves a row that nobody can ever use: the person cannot sign in, and if their
address is on the suppression list they cannot even be sent another
confirmation — the mail is dropped before it reaches the provider. The account
exists, holds a team, and does nothing but sit there.

The alternative — refusing such an address at the signup form and saying why —
was considered and rejected (Kostja, 2026-08-22): telling somebody which
addresses are refused teaches a throwaway-mail user which providers still work,
and the blocklist exists precisely so we never have that conversation. So the
signup succeeds and this removes it later.

**Deleting user accounts on a timer is dangerous**, so the predicate is
deliberately narrow. It is off unless ``SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS``
is set, and it only ever matches a row that:

* is active, and is neither staff nor a superuser;
* **has never logged in** — ``last_login`` is null, so an account that ever got
  in is out of scope whatever its addresses look like now;
* **has at least one EmailAddress row, none of them verified.** The "at least
  one" is what protects a user created by hand in the admin: such a row often
  has no ``EmailAddress`` at all, and would otherwise match a bare
  "no verified address" test;
* is older than the configured window. That window must exceed
  ``ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS`` (allauth's default is 3), or the
  purge races the last valid click on a confirmation link.

Override by subclassing, not by editing: point
``SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_CLASS`` at your own subclass and change one
method. ``queryset()`` and ``purge_user()`` are the interesting ones.
"""

import structlog
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

logger = structlog.get_logger(__name__)


class AccountPurgeCleanupFailed(Exception):
    """A cleanup hook failed, so the account was kept for the next run."""


class UnconfirmedAccountPurge:
    """Finds and deletes signups that never confirmed an email address."""

    def __init__(self, now=None, days=None):
        self.now = now or timezone.now()
        self._days = days

    # -- configuration ------------------------------------------------
    @property
    def days(self):
        """The age a row must reach. 0 (the default) disables the purge."""
        if self._days is not None:
            return max(0, int(self._days))
        return max(0, int(getattr(settings, "SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_DAYS", 0)))

    @property
    def enabled(self):
        return self.days > 0

    def cleanup_hooks(self):
        """Dotted paths called with the user before the row goes.

        Same contract as the team deletion hooks: idempotent, and **raise** on
        failure so the transaction rolls back and the account is retried rather
        than half removed. This is where a project disposes of what hangs off a
        user but is not reached by the cascade — in the boilerplate, the team
        the signup was given.
        """
        return list(getattr(settings, "SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_HOOKS", []))

    # -- selection ----------------------------------------------------
    def queryset(self):
        """The rows this purge is allowed to delete. Override to narrow it."""
        from allauth.account.models import EmailAddress
        from django.db.models import Exists, OuterRef

        User = get_user_model()
        addresses = EmailAddress.objects.filter(user_id=OuterRef("pk"))
        return (
            User.objects.filter(
                is_active=True,
                is_staff=False,
                is_superuser=False,
                last_login__isnull=True,
                date_joined__lte=self.now - timezone.timedelta(days=self.days),
            )
            .annotate(
                has_any_address=Exists(addresses),
                has_verified_address=Exists(addresses.filter(verified=True)),
            )
            .filter(has_any_address=True, has_verified_address=False)
            .order_by("date_joined")
        )

    # -- action -------------------------------------------------------
    def purge_user(self, user):
        """Run the hooks, then delete the row. One transaction per account."""
        user_id, user_email = str(user.pk), user.email
        try:
            with transaction.atomic():
                for path in self.cleanup_hooks():
                    import_string(path)(user)
                user.delete()
        except Exception as exc:
            logger.error(
                "unconfirmed_account_purge_failed",
                user_id=user_id,
                error=str(exc),
                exc_info=True,
            )
            raise AccountPurgeCleanupFailed(str(exc)) from exc

        # The domain, not the address: this is an audit line, and the person is
        # gone, so keeping their address in the logs serves nobody.
        logger.warning(
            "unconfirmed_account_purged",
            user_id=user_id,
            email_domain=user_email.rpartition("@")[2].lower(),
        )
        return True

    def run(self, dry_run=False, limit=None):
        """Purge everything the queryset matches. Returns a small report."""
        if not self.enabled:
            logger.info("unconfirmed_account_purge_disabled")
            return {"enabled": False, "purged": 0, "failed": 0, "matched": 0}

        rows = self.queryset()
        if limit:
            rows = rows[:limit]
        # Listed before deleting: the queryset is evaluated lazily and deleting
        # as we iterate would walk a moving cursor.
        users = list(rows)
        purged = failed = 0
        for user in users:
            if dry_run:
                continue
            try:
                self.purge_user(user)
                purged += 1
            except AccountPurgeCleanupFailed:
                failed += 1

        logger.info(
            "unconfirmed_account_purge_completed",
            matched=len(users),
            purged=purged,
            failed=failed,
            dry_run=dry_run,
            days=self.days,
        )
        return {
            "enabled": True,
            "matched": len(users),
            "purged": purged,
            "failed": failed,
            "dry_run": dry_run,
        }


def get_purge(**kwargs):
    """The configured purge class, so a project can subclass ours."""
    path = getattr(
        settings,
        "SPEEDPY_UNCONFIRMED_ACCOUNT_PURGE_CLASS",
        "speedpycom.services.account_purge.UnconfirmedAccountPurge",
    )
    return import_string(path)(**kwargs)
