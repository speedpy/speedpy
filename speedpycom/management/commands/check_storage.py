"""Round-trip test the S3-compatible storage wiring against the real bucket.

Proves the three things that actually break in production, in order:

1. Public media uploads and is then readable by plain URL (through the CDN when
   ``S3_CDN_BASE`` is set).
2. Private media uploads and is **not** readable without a signature.
3. The same private object IS readable with a signature.

Point 2 is the one worth running: a bucket that is public by mistake will pass
points 1 and 3 and quietly serve private files to anyone.

Run it after setting the S3_* variables:

    python manage.py check_storage
    python manage.py check_storage --keep   # leave the probe objects behind
"""

import uuid

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

_TIMEOUT = 30


class Command(BaseCommand):
    help = "Round-trip test for the public and private S3 storage backends."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Do not delete the probe objects (useful for inspecting ACLs).",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "USE_S3", False):
            raise CommandError(
                "USE_S3 is False — media is on local disk, nothing to check. "
                "Set the S3_* variables first (see STORAGE_SETUP.md)."
            )
        try:
            from speedpycom.storages import PrivateMediaStorage, PublicMediaStorage
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on extras
            raise CommandError(
                f"{exc}. The S3 backends need the optional dependency: "
                "uv sync --extra s3"
            ) from exc

        token = uuid.uuid4().hex
        failures = []
        cleanup = []

        def check(label, ok, detail=""):
            self.stdout.write(f"[{'OK  ' if ok else 'FAIL'}] {label} {detail}")
            if not ok:
                failures.append(label)

        self.stdout.write(
            f"bucket={settings.S3_BUCKET_NAME} "
            f"endpoint={settings.S3_ENDPOINT_URL or 'AWS default'} "
            f"cdn={settings.S3_CDN_BASE or 'none'} "
            f"acl={settings.S3_DEFAULT_ACL or 'none'}"
        )

        # 1. Public round-trip.
        public = PublicMediaStorage()
        public_name = public.save(f"_check/{token}.txt", ContentFile(b"public probe"))
        cleanup.append((public, public_name))
        public_url = public.url(public_name)
        try:
            resp = requests.get(public_url, timeout=_TIMEOUT)
            check(
                "public object readable by plain URL",
                resp.status_code == 200,
                f"{resp.status_code} {public_url}",
            )
        except requests.RequestException as exc:
            check("public object readable by plain URL", False, str(exc))

        # 2 + 3. Private object must need its signature.
        private = PrivateMediaStorage()
        private_name = private.save(f"_check/{token}.txt", ContentFile(b"private probe"))
        cleanup.append((private, private_name))
        signed_url = private.url(private_name)
        unsigned_url = signed_url.split("?")[0]
        try:
            resp = requests.get(unsigned_url, timeout=_TIMEOUT)
            check(
                "private object REFUSED without a signature",
                resp.status_code in (401, 403, 404),
                f"{resp.status_code} {unsigned_url}",
            )
        except requests.RequestException as exc:
            check("private object REFUSED without a signature", False, str(exc))
        try:
            resp = requests.get(signed_url, timeout=_TIMEOUT)
            check(
                "private object readable WITH a signature",
                resp.status_code == 200,
                str(resp.status_code),
            )
        except requests.RequestException as exc:
            check("private object readable WITH a signature", False, str(exc))

        if options["keep"]:
            self.stdout.write("--keep: probe objects left in place.")
        else:
            for storage, name in cleanup:
                try:
                    storage.delete(name)
                except Exception as exc:  # noqa: BLE001 - cleanup must not mask results
                    self.stdout.write(f"warning: could not delete {name}: {exc}")

        if failures:
            raise CommandError(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        self.stdout.write(self.style.SUCCESS("All storage checks passed."))
