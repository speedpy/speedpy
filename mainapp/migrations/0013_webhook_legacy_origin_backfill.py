"""Backfill existing webhook endpoints to the ``legacy`` origin.

Rows that existed before connection-identity tracking cannot have a recoverable
creator or OAuth binding, so they are grandfathered: the delivery lifecycle
checks team eligibility for them and nothing else. This runs during the same
deploy as 0012 (which added ``origin`` with the model default ``dashboard``),
before the new code serves any request, so every row it sees predates the
feature. New rows created afterwards get their real origin from the code. This
is a deliberate, documented security exception — not fail-closed enforcement.
"""

from django.db import migrations


def set_legacy_origin(apps, schema_editor):
    WebhookEndpoint = apps.get_model("mainapp", "WebhookEndpoint")
    WebhookEndpoint.objects.filter(origin="dashboard").update(origin="legacy")


def noop_reverse(apps, schema_editor):
    # Irreversible: once new rows exist we cannot distinguish them from the
    # backfilled ones. Leave data as-is on reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("mainapp", "0012_webhookendpoint_application_and_more"),
    ]

    operations = [
        migrations.RunPython(set_legacy_origin, noop_reverse),
    ]
