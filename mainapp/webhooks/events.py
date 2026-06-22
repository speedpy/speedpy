"""
Webhook event type constants.

All event names follow the ``resource.sub_resource.action`` convention.
Register new events here so they can be referenced consistently across
signals, serializers, and delivery logic.
"""


class WebhookEvent:
    # -- Team events ----------------------------------------------------------
    TEAM_MEMBER_ADDED = "team.member.added"
    TEAM_INVITATION_CREATED = "team.invitation.created"

    # -- User events ----------------------------------------------------------
    USER_PROFILE_UPDATED = "user.profile.updated"

    # -- Convenience collections ----------------------------------------------
    ALL: frozenset[str] = frozenset(
        {
            TEAM_MEMBER_ADDED,
            TEAM_INVITATION_CREATED,
            USER_PROFILE_UPDATED,
        }
    )

    CHOICES: tuple[tuple[str, str], ...] = tuple(
        (evt, evt) for evt in sorted(ALL)
    )
