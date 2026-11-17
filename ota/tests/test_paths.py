"""Unit tests for the path-safety helpers (traversal protection, names)."""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

from ota.exceptions import InvalidRuntimeVersion, UnsafePathError
from ota.paths import (
    ensure_within,
    looks_like_timestamp_dir,
    safe_join,
    safe_relative_path,
    validate_runtime_version,
)


class RuntimeVersionTests(SimpleTestCase):
    def test_accepts_real_world_runtime_versions(self):
        for value in (
            "1.2.2",
            "1.2.2-admin",
            "1.2.2+42",
            "1_2_2",
            "v1.2.2",
            "2.0.0@beta",
        ):
            with self.subTest(value=value):
                self.assertEqual(validate_runtime_version(value), value)

    def test_trims_whitespace(self):
        self.assertEqual(validate_runtime_version("  1.2.2 \n"), "1.2.2")

    def test_rejects_empty(self):
        for value in (None, "", "   "):
            with self.subTest(value=value), self.assertRaises(InvalidRuntimeVersion):
                validate_runtime_version(value)

    def test_rejects_path_traversal_and_separators(self):
        for value in (
            "..",
            "../1.2.2",
            "1.2/2",
            "1.2\\2",
            "a b",
            ".hidden",
            "-leading",
        ):
            with self.subTest(value=value), self.assertRaises(InvalidRuntimeVersion):
                validate_runtime_version(value)

    def test_rejects_too_long_values(self):
        with self.assertRaises(InvalidRuntimeVersion):
            validate_runtime_version("1" * 129)


class SafeRelativePathTests(SimpleTestCase):
    def test_normalizes_separators_and_dots(self):
        cases = {
            "a/b/c": "a/b/c",
            "a\\b\\c": "a/b/c",
            "./a//b/": "a/b",
            "assets/../assets/x": None,  # traversal is rejected, never normalized away
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                if expected is None:
                    with self.assertRaises(UnsafePathError):
                        safe_relative_path(raw)
                else:
                    self.assertEqual(safe_relative_path(raw), expected)

    def test_rejects_empty_absolute_and_nul(self):
        for raw in ("", "   ", "/etc/passwd", "C:\\windows\\system32", "a\x00b"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                safe_relative_path(raw)

    def test_rejects_parent_traversal(self):
        for raw in ("..", "../x", "a/../../b", "a/..", "./../x"):
            with self.subTest(raw=raw), self.assertRaises(UnsafePathError):
                safe_relative_path(raw)


class SafeJoinTests(SimpleTestCase):
    def test_joins_inside_base(self):
        base = Path("/tmp/ota-base")
        self.assertEqual(safe_join(base, "a/b.txt"), base / "a" / "b.txt")

    def test_ensure_within_rejects_escape(self):
        base = Path("/tmp/ota-base")
        with self.assertRaises(UnsafePathError):
            ensure_within(base, base / ".." / "outside")

    def test_ensure_within_accepts_base_itself_and_children(self):
        base = Path("/tmp/ota-base")
        self.assertEqual(ensure_within(base, base), base.resolve())
        self.assertEqual(ensure_within(base, base / "x"), (base / "x").resolve())


class TimestampDirectoryTests(SimpleTestCase):
    def test_only_digits_are_timestamps(self):
        self.assertTrue(looks_like_timestamp_dir("1731000000000"))
        for value in ("", "123abc", ".staging-abc", "1.5", "-1"):
            with self.subTest(value=value):
                self.assertFalse(looks_like_timestamp_dir(value))
