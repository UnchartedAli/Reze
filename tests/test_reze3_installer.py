"""Installer wizard helpers: masking, .env merging, idempotency and checks."""

import contextlib
import io
import os
import tempfile
import unittest

import support  # noqa: F401  - prepares the environment before reze imports

from reze import installer


class MaskTests(unittest.TestCase):
    def test_mask_never_returns_the_full_secret(self):
        secret = "super-secret-api-key-value"
        masked = installer.mask(secret)
        self.assertNotIn(secret, masked)
        self.assertIn("chars", masked)
        self.assertEqual(installer.mask(""), "(not set)")

    def test_very_short_values_are_hidden_entirely(self):
        masked = installer.mask("abcd")
        self.assertNotIn("abcd", masked)


class MergeTests(unittest.TestCase):
    def test_updates_in_place_and_preserves_comments(self):
        original = "# header\nA=1\n# keep me\nB=2\n"
        merged = installer.merge_env(original, {"B": "3", "C": "4"})
        self.assertIn("# header", merged)
        self.assertIn("# keep me", merged)
        self.assertIn("A=1", merged)
        self.assertIn("B=3", merged)
        self.assertIn("C=4", merged)

    def test_merge_is_idempotent(self):
        updates = {"REZE_LANGUAGE": "fa", "REZE_DATA_DIR": "data"}
        first = installer.merge_env("", updates)
        second = installer.merge_env(first, updates)
        self.assertEqual(first, second)

    def test_known_keys_are_ordered(self):
        merged = installer.merge_env("", {"REZE_VAULT_KEY": "k", "REZE_API_ID": "1"})
        self.assertLess(merged.index("REZE_API_ID"), merged.index("REZE_VAULT_KEY"))


class WriteEnvTests(unittest.TestCase):
    def test_second_write_is_a_no_op_and_creates_no_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, ".env")
            updates = {"REZE_LANGUAGE": "en", "REZE_DATA_DIR": directory}
            changed, status = installer.write_env(path, updates)
            self.assertTrue(changed)
            self.assertEqual(status, "written")
            with open(path, encoding="utf-8") as handle:
                first = handle.read()

            changed, status = installer.write_env(path, updates)
            self.assertFalse(changed)
            self.assertEqual(status, "no changes")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), first)
            self.assertEqual([name for name in os.listdir(directory) if ".bak-" in name], [])

    def test_changing_a_value_creates_a_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, ".env")
            installer.write_env(path, {"REZE_LANGUAGE": "en"})
            changed, _ = installer.write_env(path, {"REZE_LANGUAGE": "fa"})
            self.assertTrue(changed)
            backups = [name for name in os.listdir(directory) if ".bak-" in name]
            self.assertEqual(len(backups), 1)


class ValidatorTests(unittest.TestCase):
    def test_integer_bounds(self):
        validator = installer._int_validator(1, 65535)
        validator("8080")
        with self.assertRaises(ValueError):
            validator("0")
        with self.assertRaises(ValueError):
            validator("70000")
        with self.assertRaises(ValueError):
            validator("abc")

    def test_language_values(self):
        for value in ("en", "fa", "English", "Persian", "farsi"):
            installer._language_validator(value)
        with self.assertRaises(ValueError):
            installer._language_validator("fr")

    def test_data_dir_must_be_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "nested", "data")
            installer.validate_data_dir(target)
            self.assertTrue(os.path.isdir(target))
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            with self.assertRaises(ValueError):
                installer.validate_data_dir(path)
        finally:
            os.remove(path)


class SystemCheckTests(unittest.TestCase):
    def test_check_mode_runs_without_prompting_and_leaks_nothing(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = installer.run(["--check"])
        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[1/8] System check", text)
        self.assertIn("Python", text)
        for marker in ("REZE_API_HASH", "REZE_SESSION_STRING", "REZE_VAULT_KEY"):
            self.assertNotIn(marker + "=", text)


if __name__ == "__main__":
    unittest.main()
