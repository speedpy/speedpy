"""Opt-in URLs for SES delivery-event tracking.

Not wired by default. Include it from your project urls when you use SES:

.. code-block:: python

    urlpatterns = [
        ...
        path("", include("speedpycom.urls_email_events")),
    ]

Kept separate rather than added to the default urlconf because it is
Amazon-specific, and a project on Mailgun or Postmark should not be serving an
SNS endpoint it will never receive anything on.

The path AND the url name are deliberately fixed. The path is registered in
AWS, so it is a contract with something outside this codebase. The name
``ses_events`` matches what projects already reverse.
"""

from django.urls import path

from speedpycom.views_ses import SESEventWebhookView

urlpatterns = [
    path("webhooks/ses/", SESEventWebhookView.as_view(), name="ses_events"),
]
