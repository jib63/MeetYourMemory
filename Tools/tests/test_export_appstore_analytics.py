import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parents[1]
SCRIPT = TOOLS / "export_appstore_analytics.py"
SPEC = importlib.util.spec_from_file_location("export_appstore_analytics", SCRIPT)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def report(identifier: str, name: str, category: str = "APP_USAGE") -> dict:
    return {
        "id": identifier,
        "attributes": {"name": name, "category": category},
    }


class FakeClient:
    def __init__(self, catalogs: dict[str, list[dict]]) -> None:
        self.catalogs = catalogs

    def get_all(self, path: str, params=None) -> list[dict]:
        request_id = path.split("/")[2]
        return self.catalogs[request_id]


class FakeResponse:
    def __init__(self, *, json_body=None, content=b"", status_code=200):
        self._json_body = json_body
        self.content = content
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = content.decode("utf-8", errors="replace")
        self.headers = {}

    def json(self):
        return self._json_body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected {method} {url}")
        return self.responses.pop(0)


class ExportAppStoreAnalyticsTests(unittest.TestCase):
    def test_vendor_number_reads_environment_and_validates_digits(self) -> None:
        with patch.dict("os.environ", {"ASC_VENDOR_NUMBER": "123456"}, clear=False):
            self.assertEqual(exporter.load_vendor_number(), "123456")
        with self.assertRaises(exporter.AppStoreConnectError):
            exporter.load_vendor_number("ABC123")

    def test_prefers_standard_report_over_detailed_report(self) -> None:
        selected, missing = exporter.select_reports(
            [
                report("detailed", "App Sessions Detailed"),
                report("standard", "App Sessions Standard"),
            ],
            ["App Sessions"],
        )

        self.assertEqual([item["id"] for item in selected], ["standard"])
        self.assertEqual(missing, [])

    def test_reports_missing_requested_families(self) -> None:
        selected, missing = exporter.select_reports(
            [report("downloads", "App Store Downloads Standard")],
            ["App Store Downloads", "App Crashes"],
        )

        self.assertEqual([item["id"] for item in selected], ["downloads"])
        self.assertEqual(missing, ["App Crashes"])

    def test_accepts_download_and_subscription_catalog_aliases(self) -> None:
        selected, missing = exporter.select_reports(
            [
                report("downloads", "App Downloads Standard", "COMMERCE"),
                report("subscription", "Subscription Event", "COMMERCE"),
            ],
            ["App Store Downloads", "App Store Subscription Event"],
        )

        self.assertEqual(
            {item["id"] for item in selected}, {"downloads", "subscription"}
        )
        self.assertEqual(missing, [])

    def test_choose_ready_request_skips_stopped_and_uses_largest_catalog(self) -> None:
        client = FakeClient(
            {
                "small": [report("one", "App Crashes")],
                "large": [
                    report("one", "App Crashes"),
                    report("two", "App Sessions Standard"),
                ],
            }
        )
        requests = [
            {"id": "stopped", "attributes": {"stoppedDueToInactivity": True}},
            {"id": "small", "attributes": {}},
            {"id": "large", "attributes": {}},
        ]

        request, catalog = exporter.choose_ready_request(client, requests)

        self.assertEqual(request["id"], "large")
        self.assertEqual(len(catalog), 2)

    def test_decode_segment_checks_size_checksum_and_decompresses(self) -> None:
        raw = b"Date\tCounts\n2026-08-01\t3\n"
        compressed = gzip.compress(raw)

        decoded = exporter.decode_segment(
            compressed,
            len(compressed),
            hashlib.md5(compressed).hexdigest(),
        )

        self.assertEqual(decoded, raw)

    def test_decode_segment_rejects_checksum_mismatch(self) -> None:
        compressed = gzip.compress(b"data")

        with self.assertRaises(exporter.AppStoreConnectError):
            exporter.decode_segment(compressed, len(compressed), "0" * 32)

    def test_decode_segment_accepts_sha256_checksum(self) -> None:
        raw = b"Date\tSessions\n2026-08-01\t2\n"
        compressed = gzip.compress(raw)

        decoded = exporter.decode_segment(
            compressed,
            len(compressed),
            hashlib.sha256(compressed).hexdigest(),
        )

        self.assertEqual(decoded, raw)

    def test_safe_filename_removes_path_characters(self) -> None:
        self.assertEqual(
            exporter.safe_filename("App Store / Downloads: Standard"),
            "App-Store-Downloads-Standard",
        )

    def test_signed_download_does_not_use_authenticated_session(self) -> None:
        authenticated = FakeSession([])
        downloader = FakeSession([FakeResponse(content=b"report")])
        client = exporter.Client(
            "secret-token",
            session=authenticated,
            download_session=downloader,
        )

        content = client.download("https://example.invalid/signed-report")

        self.assertEqual(content, b"report")
        self.assertEqual(authenticated.calls, [])
        self.assertNotIn("Authorization", downloader.headers)

    def test_sales_binary_request_uses_gzip_accept_header(self) -> None:
        authenticated = FakeSession([FakeResponse(content=b"gzip")])
        client = exporter.Client("token", session=authenticated)

        content = client.get_binary(
            "/v1/salesReports", {"filter[reportType]": "SALES"}
        )

        self.assertEqual(content, b"gzip")
        self.assertEqual(
            authenticated.calls[0][2]["headers"]["Accept"],
            "application/a-gzip",
        )

    def test_filter_sales_report_keeps_only_selected_app_rows(self) -> None:
        raw = (
            "Provider\tApple Identifier\tSKU\tProduct ID\tUnits\n"
            "ME\t6000000002\tmeet-your-memory\tcom.jibstudios.Meet-Your-Memory.free\t1\n"
            "ME\t1234567890\tother\tcom.example.other\t9\n"
        ).encode("utf-8")

        filtered, row_count = exporter.filter_tsv_report(
            raw,
            {
                "6000000002",
                "com.jibstudios.Meet-Your-Memory",
                "com.jibstudios.Meet-Your-Memory.free",
            },
        )

        rendered = filtered.decode("utf-8")
        self.assertEqual(row_count, 1)
        self.assertIn("6000000002", rendered)
        self.assertNotIn("1234567890", rendered)

    def test_sales_specs_use_supported_versions(self) -> None:
        specs = {spec.report_type: spec for spec in exporter.SALES_REPORT_SPECS}

        self.assertEqual(specs["SALES"].version, "1_0")
        self.assertEqual(specs["SUBSCRIPTION"].version, "1_3")
        self.assertEqual(specs["SUBSCRIPTION_EVENT"].version, "1_3")
        self.assertEqual(specs["SUBSCRIBER"].version, "1_3")

    def test_all_analytics_reports_are_the_default(self) -> None:
        args = exporter.parse_args([])

        self.assertFalse(args.diagnostic_reports_only)

    def test_archive_is_created_while_analytics_are_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pending.zip"
            archive, count = exporter.write_archive(
                FakeClient({}),
                {
                    "id": "6000000002",
                    "attributes": {
                        "name": "Meet Your Memory",
                        "bundleId": "com.jibstudios.Meet-Your-Memory",
                    },
                },
                {
                    "id": "request-id",
                    "attributes": {"accessType": "ONE_TIME_SNAPSHOT"},
                },
                [],
                [],
                [],
                "DAILY",
                output,
                skip_context=True,
                vendor_number="",
                sales_start_date=date(2026, 5, 25),
                sales_end_date=date(2026, 8, 22),
            )

            self.assertEqual(count, 0)
            with zipfile.ZipFile(archive) as exported:
                manifest = json.loads(exported.read("manifest.json"))
            self.assertTrue(manifest["context"]["skipped"])
            self.assertTrue(manifest["sales"]["skipped"])
            self.assertEqual(manifest["analyticsSummary"]["catalogReports"], 0)


if __name__ == "__main__":
    unittest.main()
