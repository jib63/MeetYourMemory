import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
import upload_appstore as uploader

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "Meet Your Memory/ci_scripts/ci_post_xcodebuild.sh"


class AppStoreMetadataCITests(unittest.TestCase):
    def test_post_build_skips_unwanted_contexts(self):
        cases = (
            ("feature/demo", "refs/heads/feature/demo", "", "archive", "0"),
            ("main", "refs/tags/1.1.1", "", "archive", "0"),
            ("main", "refs/heads/main", "42", "archive", "0"),
            ("main", "refs/heads/main", "", "test", "0"),
            ("main", "refs/heads/main", "", "archive", "65"),
            ("main", "refs/heads/main", "", "archive", ""),
        )
        for branch, ref, pull_request, action, exit_code in cases:
            with self.subTest(branch=branch, ref=ref, action=action,
                              exit_code=exit_code):
                env = {**os.environ, "CI_BRANCH": branch, "CI_GIT_REF": ref,
                       "CI_PULL_REQUEST_NUMBER": pull_request,
                       "CI_XCODEBUILD_ACTION": action,
                       "CI_XCODEBUILD_EXIT_CODE": exit_code}
                result = subprocess.run(["sh", str(SCRIPT)], env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Skipping App Store metadata", result.stdout)

    def test_main_archive_checks_version_before_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Products/Applications/Meet Your Memory.app"
            app.mkdir(parents=True)
            with (app / "Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier": uploader.BUNDLE_ID,
                               "CFBundleShortVersionString": "1.1.1"}, stream)
            env = {**os.environ, "CI_BRANCH": "main",
                   "CI_GIT_REF": "refs/heads/main",
                   "CI_PULL_REQUEST_NUMBER": "",
                   "CI_XCODEBUILD_ACTION": "archive",
                   "CI_XCODEBUILD_EXIT_CODE": "0",
                   "CI_ARCHIVE_PATH": tmp}
            for name in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY_BASE64"):
                env.pop(name, None)
            result = subprocess.run(["sh", str(SCRIPT)], env=env,
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("✓ hi: metadata ready", result.stdout)
        self.assertIn("ASC_PRIVATE_KEY_BASE64", result.stderr)

    def test_local_notes_and_version_guard(self):
        self.assertTrue(uploader.check_local_metadata([], "1.1.1"))
        self.assertFalse(uploader.check_local_metadata([], "1.1.0"))
        client = Mock()
        client.get.return_value = {"data": [{"id": "wrong-version",
            "attributes": {"versionString": "1.1.0",
                           "appStoreState": "PREPARE_FOR_SUBMISSION"}}]}
        with self.assertRaises(SystemExit):
            uploader.find_editable_version(client, "app", "1.1.1")

    def test_strict_upload_and_readback_surface_failure(self):
        client = Mock()
        client.get.return_value = {"data": [{"id": "localization",
            "attributes": {"locale": "en-US"}}]}
        client.patch.side_effect = requests.HTTPError("rejected")
        with patch.object(uploader, "LOCALES", {"en-US": "en"}), \
                patch.object(uploader, "read_metadata",
                             return_value={"release_notes": "Version 1.1.1"}):
            with self.assertRaises(requests.HTTPError):
                uploader.update_version_localizations(client, "version", [],
                                                      strict=True)
        with self.assertRaisesRegex(RuntimeError, "en-US: whatsNew"):
            uploader.verify_text_localizations(
                client, "/appStoreVersions/version/appStoreVersionLocalizations",
                {"en-US": {"whatsNew": "Version 1.1.1"}})


if __name__ == "__main__":
    unittest.main()
