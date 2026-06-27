"""Plan application — the only place billing logic mutates an account's plan.

For teams, both ``Team.plan`` and ``Team.limits_max_team_members`` are kept in
sync from the canonical registry. For users (teams disabled) there is no plan
field on the user model — the effective plan is derived from the active
subscription (see :func:`mainapp.billing.state.effective_plan_key`), so plan
application is a no-op on the account itself.
"""

import structlog

from mainapp.subscription_plans import DEFAULT_PLAN_KEY, get_plan_limit

logger = structlog.get_logger(__name__)


def _is_team(billable):
    from mainapp.models import Team

    return isinstance(billable, Team)


def apply_plan_to_billable(billable, plan_key):
    """Set the account's plan and recalculate derived limits from the registry.

    Called by webhook processing and the grace/downgrade periodic task.
    """
    if billable is None:
        return
    if _is_team(billable):
        billable.plan = plan_key
        billable.limits_max_team_members = get_plan_limit(plan_key, "max_team_members")
        billable.save(update_fields=["plan", "limits_max_team_members", "updated_at"])
        logger.info(
            "billing_plan_applied",
            billable_type="team",
            billable_id=str(billable.pk),
            plan_key=plan_key,
        )
    # User mode: nothing to persist on the account; the subscription row carries
    # the plan and state helpers derive the effective plan from it.


def downgrade_to_free(billable):
    """Downgrade an account to the free plan."""
    apply_plan_to_billable(billable, DEFAULT_PLAN_KEY)
