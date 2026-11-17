"""``manage.py ota_publish`` — publish an ``expo export`` output as an OTA release.

Typical usage on the server (or locally) after building the JS bundle::

    npx expo export -p android --output-dir dist-ota
    python manage.py ota_publish \
        --export-dir dist-ota \
        --platform android \
        --runtime-version 1.2.2 \
        --notes "fix checkout crash"

The command validates the export, copies (never symlinks) the files into
``<OTA_UPDATES_DIR>/<runtimeVersion>/<timestampMillis>/``, stores a DB row and
prunes releases beyond ``OTA_MAX_RELEASES``. It prints a JSON summary so CI can
parse the resulting update id.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser

from ota.exceptions import OTAError
from ota.publishing import publish_from_directory


class Command(BaseCommand):
    help = (
        "Publish an `expo export` output directory as an Expo Updates (OTA) release. "
        "Files are copied to <OTA_UPDATES_DIR>/<runtimeVersion>/<timestampMillis>/."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--export-dir",
            required=True,
            help="Directory produced by `npx expo export -p android --output-dir dist-ota`.",
        )
        parser.add_argument(
            "--platform",
            required=True,
            choices=("android", "ios"),
            help="Platform this export was built for (must exist in metadata.json).",
        )
        parser.add_argument(
            "--runtime-version",
            required=True,
            dest="runtime_version",
            help=(
                "Exact runtimeVersion of the installed binary, e.g. 1.2.2 or 1.2.2-admin. "
                "It must match app.json runtimeVersion byte-for-byte."
            ),
        )
        parser.add_argument(
            "--notes", default="", help="Free-form release notes (stored in the DB)."
        )
        parser.add_argument(
            "--no-activate",
            action="store_true",
            dest="no_activate",
            help="Store the release without making it the latest served update.",
        )
        parser.add_argument(
            "--created-by",
            default=None,
            help="Username to record as the publisher (optional).",
        )
        parser.add_argument(
            "--max-releases",
            type=int,
            default=None,
            dest="max_releases",
            help="Override OTA_MAX_RELEASES for this run (retention pruning).",
        )

    def handle(self, *args: object, **options: object) -> None:
        export_dir = str(options["export_dir"])
        platform = str(options["platform"])
        runtime_version = str(options["runtime_version"])
        notes = str(options.get("notes") or "")
        activate = not bool(options.get("no_activate"))
        max_releases = options.get("max_releases")

        created_by = None
        created_by_username = options.get("created_by")
        if created_by_username:
            user_model = get_user_model()
            try:
                # USERNAME_FIELD lookup (phone in this project), not a hard-coded `username` field.
                created_by = user_model._default_manager.get_by_natural_key(created_by_username)
            except user_model.DoesNotExist:
                raise CommandError(
                    f"--created-by: no user named {created_by_username!r}"
                ) from None

        try:
            result = publish_from_directory(
                export_dir,
                platform=platform,
                runtime_version=runtime_version,
                notes=notes,
                activate=activate,
                created_by=created_by,
                max_releases=max_releases,
            )
        except OTAError as exc:
            raise CommandError(exc.message) from exc

        self.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    **result.as_dict(),
                    "activated": activate,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
