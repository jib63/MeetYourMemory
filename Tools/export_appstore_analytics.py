#!/usr/bin/env python3
"""Export App Store Connect metadata, Analytics, and optional Sales & Trends reports.

The script uses the same credentials as the metadata upload tools:

    export ASC_KEY_ID=ABCDE12345
    export ASC_ISSUER_ID=12345678-...
    export ASC_KEY_PATH=~/keys/AuthKey_ABCDE12345.p8

Typical use (context plus all Analytics report definitions and data):

    python3 Tools/export_appstore_analytics.py

For low-volume sales, downloads, lifetime purchases, and subscriptions, add
the vendor number shown in App Store Connect under Payments and Financial
Reports:

    python3 Tools/export_appstore_analytics.py --vendor-number 12345678

On the first run, the script creates a ONE_TIME_SNAPSHOT request if none exists.
Apple normally needs 24-48 hours to generate the reports; run the same command
again later to download them. Context and Sales & Trends can still be exported
immediately. The resulting ZIP contains JSON context, tab-separated reports,
and a manifest, but never contains the API credentials or private key.

Dependencies:

    pip3 install 'pyjwt[crypto]' requests
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, NamedTuple

try:
    import jwt  # pyjwt[crypto]
    import requests
except ImportError:
    sys.stderr.write(
        "Missing dependencies. Install with:\n"
        "  pip3 install 'pyjwt[crypto]' requests\n"
    )
    sys.exit(2)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "Artifacts" / "AppStoreConnectExports"
BUNDLE_ID = "com.jibstudios.Meet-Your-Memory"
API_BASE = "https://api.appstoreconnect.apple.com/v1"
API_ORIGIN = "https://api.appstoreconnect.apple.com"
JWT_AUDIENCE = "appstoreconnect-v1"
JWT_TTL_SECONDS = 20 * 60

# Standard reports are preferable for a low-volume app: detailed variants add
# privacy protections and dimensions that can suppress more rows. Prefix
# matching deliberately tolerates minor name changes made by Apple.
DEFAULT_REPORT_PREFIXES = (
    "App Store Discovery and Engagement",
    "App Store Downloads",
    "App Store Installations and Deletions",
    "App Store Opt-in",
    "App Sessions",
    "App Crashes",
    "App Store Purchases",
    "App Store Subscription State",
    "App Store Subscription Event",
)

REPORT_PREFIX_ALIASES = {
    # Apple documentation and live catalogs have used both of these names.
    "App Store Downloads": ("App Downloads",),
    "App Store Installations and Deletions": (
        "App Store Installation and Deletion",
    ),
    "App Store Subscription State": ("Subscription State",),
    "App Store Subscription Event": ("Subscription Event",),
}


class SalesReportSpec(NamedTuple):
    report_type: str
    report_subtype: str
    version: str


SALES_REPORT_SPECS = (
    SalesReportSpec("SALES", "SUMMARY", "1_0"),
    SalesReportSpec("SUBSCRIPTION", "SUMMARY", "1_3"),
    SalesReportSpec("SUBSCRIPTION_EVENT", "SUMMARY", "1_3"),
    SalesReportSpec("SUBSCRIBER", "DETAILED", "1_3"),
)


class AppStoreConnectError(RuntimeError):
    """An App Store Connect request failed with a useful user-facing message."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        path: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(message)


def load_credentials() -> tuple[str, str, str]:
    """Load the three environment variables used by the existing ASC tools."""
    key_id = os.environ.get("ASC_KEY_ID")
    issuer_id = os.environ.get("ASC_ISSUER_ID")
    key_path = os.environ.get("ASC_KEY_PATH")
    missing = [
        name
        for name, value in (
            ("ASC_KEY_ID", key_id),
            ("ASC_ISSUER_ID", issuer_id),
            ("ASC_KEY_PATH", key_path),
        )
        if not value
    ]
    if missing:
        raise AppStoreConnectError(
            f"Missing environment variables: {', '.join(missing)}\n"
            "Export the same credentials used by Tools/upload_appstore.py."
        )

    expanded = Path(os.path.expanduser(key_path))
    if not expanded.is_file():
        raise AppStoreConnectError(f"ASC_KEY_PATH not found: {expanded}")
    private_key = expanded.read_text(encoding="utf-8")
    if "-----BEGIN PRIVATE KEY-----" not in private_key:
        raise AppStoreConnectError(
            "ASC_KEY_PATH is not an App Store Connect PKCS#8 PEM private key."
        )
    return key_id, issuer_id, private_key


def load_vendor_number(value: str | None = None) -> str:
    """Read and validate the optional Sales & Trends vendor number."""
    vendor_number = (
        value if value is not None else os.environ.get("ASC_VENDOR_NUMBER", "")
    ).strip()
    if vendor_number and not vendor_number.isdigit():
        raise AppStoreConnectError("ASC_VENDOR_NUMBER must contain digits only.")
    return vendor_number


def make_jwt(key_id: str, issuer_id: str, private_key: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer_id,
            "exp": now + JWT_TTL_SECONDS,
            "aud": JWT_AUDIENCE,
        },
        private_key,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"},
    )


class Client:
    """Small App Store Connect client with pagination and clear API errors."""

    def __init__(
        self,
        token: str,
        session: requests.Session | None = None,
        download_session: requests.Session | None = None,
    ):
        self.session = session or requests.Session()
        self.download_session = download_session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )

    @staticmethod
    def _url(path: str) -> str:
        if path.startswith("http"):
            return path
        if path.startswith(("/v1/", "/v2/")):
            return API_ORIGIN + path
        return API_BASE + path

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response: requests.Response | None = None
        for attempt in range(4):
            response = self.session.request(
                method,
                self._url(path),
                timeout=60,
                **kwargs,
            )
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            if attempt < 3:
                retry_after = response.headers.get("Retry-After")
                time.sleep(min(float(retry_after or 2**attempt), 8.0))
        assert response is not None
        self._raise(response, method, path)
        return response

    @staticmethod
    def _raise(response: requests.Response, method: str, path: str) -> None:
        if response.ok:
            return
        detail = response.text[:2_000]
        hint = ""
        if response.status_code == 403:
            hint = (
                "\nThe API key needs the Admin role to create a report request, "
                "or Admin/Sales and Reports/Finance to download existing reports."
            )
        raise AppStoreConnectError(
            f"{method} {path} returned HTTP {response.status_code}:\n{detail}{hint}",
            status_code=response.status_code,
            path=path,
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return self._request("GET", path, params=params).json()

    def get_all(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[dict]:
        return self.get_collection(path, params)["data"]

    def get_collection(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        items: list[dict] = []
        included: list[dict] = []
        next_path: str | None = path
        next_params = params
        last_meta: dict[str, Any] = {}
        while next_path:
            payload = self.get(next_path, next_params)
            items.extend(payload.get("data", []))
            included.extend(payload.get("included", []))
            last_meta = payload.get("meta", last_meta)
            next_path = payload.get("links", {}).get("next")
            next_params = None
        result: dict[str, Any] = {"data": items, "included": included}
        if last_meta:
            result["meta"] = last_meta
        return result

    def post(self, path: str, payload: dict) -> dict:
        response = self._request(
            "POST",
            path,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
        )
        return response.json()

    def get_binary(self, path: str, params: dict[str, Any]) -> bytes:
        response = self._request(
            "GET",
            path,
            params=params,
            headers={"Accept": "application/a-gzip"},
        )
        return response.content

    def download(self, url: str) -> bytes:
        # Signed Analytics URLs can point outside Apple's API origin. The
        # unauthenticated session prevents forwarding the ASC bearer token.
        response = self.download_session.request("GET", url, timeout=120)
        self._raise(response, "GET", "analytics-segment")
        return response.content


def find_app(client: Client, bundle_id: str) -> dict:
    apps = client.get_all(
        "/apps",
        {"filter[bundleId]": bundle_id, "limit": 10},
    )
    if not apps:
        raise AppStoreConnectError(f"No app found for bundle ID {bundle_id}")
    return apps[0]


def list_report_requests(client: Client, app_id: str, access_type: str) -> list[dict]:
    return client.get_all(
        f"/apps/{app_id}/analyticsReportRequests",
        {
            "filter[accessType]": access_type,
            "fields[analyticsReportRequests]": "accessType,stoppedDueToInactivity",
            "limit": 200,
        },
    )


def create_report_request(client: Client, app_id: str, access_type: str) -> dict:
    return client.post(
        "/analyticsReportRequests",
        {
            "data": {
                "type": "analyticsReportRequests",
                "attributes": {"accessType": access_type},
                "relationships": {
                    "app": {"data": {"type": "apps", "id": app_id}}
                },
            }
        },
    )["data"]


def list_reports(client: Client, request_id: str) -> list[dict]:
    return client.get_all(
        f"/analyticsReportRequests/{request_id}/reports",
        {"fields[analyticsReports]": "name,category", "limit": 200},
    )


def choose_ready_request(
    client: Client, requests_: Iterable[dict]
) -> tuple[dict | None, list[dict]]:
    """Choose an active request that already has the largest report catalog."""
    best_request: dict | None = None
    best_reports: list[dict] = []
    for request in requests_:
        if request.get("attributes", {}).get("stoppedDueToInactivity"):
            continue
        reports = list_reports(client, request["id"])
        if len(reports) > len(best_reports):
            best_request = request
            best_reports = reports
    return best_request, best_reports


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def select_reports(
    reports: Iterable[dict],
    prefixes: Iterable[str] = DEFAULT_REPORT_PREFIXES,
) -> tuple[list[dict], list[str]]:
    """Select one privacy-friendlier report per desired report family."""
    reports = list(reports)
    selected: list[dict] = []
    missing: list[str] = []

    for prefix in prefixes:
        prefix_keys = [
            _name_key(candidate)
            for candidate in (prefix, *REPORT_PREFIX_ALIASES.get(prefix, ()))
        ]
        candidates = [
            report
            for report in reports
            if any(
                _name_key(report.get("attributes", {}).get("name", "")).startswith(
                    prefix_key
                )
                for prefix_key in prefix_keys
            )
        ]
        if not candidates:
            missing.append(prefix)
            continue

        def preference(report: dict) -> tuple[int, str]:
            name = report.get("attributes", {}).get("name", "")
            key = _name_key(name)
            if key.endswith("standard"):
                rank = 0
            elif not key.endswith("detailed"):
                rank = 1
            else:
                rank = 2
            return rank, name

        selected.append(min(candidates, key=preference))

    # A prefix list containing aliases could otherwise select the same report twice.
    unique = {report["id"]: report for report in selected}
    return sorted(unique.values(), key=lambda item: item["attributes"]["name"]), missing


def list_instances(client: Client, report_id: str, granularity: str) -> list[dict]:
    instances = client.get_all(
        f"/analyticsReports/{report_id}/instances",
        {
            "filter[granularity]": granularity,
            "fields[analyticsReportInstances]": "granularity,processingDate",
            "limit": 200,
        },
    )
    return sorted(
        instances,
        key=lambda item: (
            item.get("attributes", {}).get("processingDate", ""),
            item["id"],
        ),
    )


def list_segments(client: Client, instance_id: str) -> list[dict]:
    return client.get_all(
        f"/analyticsReportInstances/{instance_id}/segments",
        {
            "fields[analyticsReportSegments]": "checksum,sizeInBytes,url",
            "limit": 200,
        },
    )


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "report"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _record_error(errors: list[dict], section: str, error: Exception) -> None:
    entry: dict[str, Any] = {"section": section, "error": str(error)}
    if isinstance(error, AppStoreConnectError):
        if error.status_code is not None:
            entry["statusCode"] = error.status_code
        if error.path is not None:
            entry["path"] = error.path
    errors.append(entry)


def _capture_collection(
    client: Client,
    destination: Path,
    section: str,
    path: str,
    errors: list[dict],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        payload = client.get_collection(path, params)
        write_json(destination, payload)
        return payload
    except (AppStoreConnectError, ValueError) as error:
        _record_error(errors, section, error)
        return {"data": [], "included": []}


def _capture_object(
    client: Client,
    destination: Path,
    section: str,
    path: str,
    errors: list[dict],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        payload = client.get(path, params)
        write_json(destination, payload)
        return payload
    except (AppStoreConnectError, ValueError) as error:
        _record_error(errors, section, error)
        return {}


def export_context(
    client: Client,
    app: dict,
    destination: Path,
    errors: list[dict],
) -> tuple[set[str], dict[str, Any]]:
    """Export product-page metadata and commercial context for the selected app."""
    context = destination / "context"
    write_json(context / "app.json", {"data": app})
    app_id = app["id"]
    attributes = app.get("attributes", {})
    identifiers = {app_id, attributes.get("bundleId", BUNDLE_ID)}

    versions = _capture_collection(
        client,
        context / "versions.json",
        "versions",
        f"/v1/apps/{app_id}/appStoreVersions",
        errors,
        {"limit": 200},
    )
    for version in versions["data"]:
        version_id = version["id"]
        platform = version.get("attributes", {}).get("platform", "unknown")
        _capture_collection(
            client,
            context
            / "version-localizations"
            / f"{safe_filename(platform)}-{version_id}.json",
            f"version-localizations:{version_id}",
            f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations",
            errors,
            {"limit": 200},
        )

    app_infos = _capture_collection(
        client,
        context / "app-infos.json",
        "app-infos",
        f"/v1/apps/{app_id}/appInfos",
        errors,
        {"limit": 200},
    )
    for info in app_infos["data"]:
        info_id = info["id"]
        _capture_collection(
            client,
            context / "app-info-localizations" / f"{info_id}.json",
            f"app-info-localizations:{info_id}",
            f"/v1/appInfos/{info_id}/appInfoLocalizations",
            errors,
            {"limit": 200},
        )

    reviews = _capture_collection(
        client,
        context / "customer-reviews.json",
        "customer-reviews",
        f"/v1/apps/{app_id}/customerReviews",
        errors,
        {"limit": 200, "sort": "-createdDate"},
    )

    availability = _capture_object(
        client,
        context / "availability.json",
        "availability",
        f"/v1/apps/{app_id}/appAvailabilityV2",
        errors,
    )
    availability_id = availability.get("data", {}).get("id")
    if availability_id:
        _capture_collection(
            client,
            context / "territory-availabilities.json",
            "territory-availabilities",
            f"/v2/appAvailabilities/{availability_id}/territoryAvailabilities",
            errors,
            {"limit": 200, "include": "territory"},
        )

    groups = _capture_collection(
        client,
        context / "subscription-groups.json",
        "subscription-groups",
        f"/v1/apps/{app_id}/subscriptionGroups",
        errors,
        {"limit": 200},
    )
    subscription_count = 0
    for group in groups["data"]:
        group_id = group["id"]
        subscriptions = _capture_collection(
            client,
            context / "subscriptions" / f"group-{group_id}.json",
            f"subscriptions:{group_id}",
            f"/v1/subscriptionGroups/{group_id}/subscriptions",
            errors,
            {"limit": 200},
        )
        subscription_count += len(subscriptions["data"])
        for subscription in subscriptions["data"]:
            subscription_id = subscription["id"]
            product_id = subscription.get("attributes", {}).get("productId")
            if product_id:
                identifiers.add(product_id)
            base = context / "subscriptions" / subscription_id
            _capture_collection(
                client,
                base / "introductory-offers.json",
                f"subscription-introductory-offers:{subscription_id}",
                f"/v1/subscriptions/{subscription_id}/introductoryOffers",
                errors,
                {"limit": 200, "include": "territory,subscriptionPricePoint"},
            )
            _capture_collection(
                client,
                base / "prices.json",
                f"subscription-prices:{subscription_id}",
                f"/v1/subscriptions/{subscription_id}/prices",
                errors,
                {"limit": 200, "include": "territory,subscriptionPricePoint"},
            )
            _capture_collection(
                client,
                base / "localizations.json",
                f"subscription-localizations:{subscription_id}",
                f"/v1/subscriptions/{subscription_id}/subscriptionLocalizations",
                errors,
                {"limit": 200},
            )

    iaps = _capture_collection(
        client,
        context / "in-app-purchases.json",
        "in-app-purchases",
        f"/v1/apps/{app_id}/inAppPurchasesV2",
        errors,
        {"limit": 200},
    )
    for iap in iaps["data"]:
        iap_id = iap["id"]
        product_id = iap.get("attributes", {}).get("productId")
        if product_id:
            identifiers.add(product_id)
        base = context / "in-app-purchases" / iap_id
        _capture_collection(
            client,
            base / "localizations.json",
            f"iap-localizations:{iap_id}",
            f"/v2/inAppPurchases/{iap_id}/inAppPurchaseLocalizations",
            errors,
            {"limit": 200},
        )
        schedule = _capture_object(
            client,
            base / "price-schedule.json",
            f"iap-price-schedule:{iap_id}",
            f"/v2/inAppPurchases/{iap_id}/iapPriceSchedule",
            errors,
        )
        schedule_id = schedule.get("data", {}).get("id")
        if schedule_id:
            for price_kind in ("manualPrices", "automaticPrices"):
                _capture_collection(
                    client,
                    base / f"{price_kind}.json",
                    f"iap-{price_kind}:{iap_id}",
                    f"/v1/inAppPurchasePriceSchedules/{schedule_id}/{price_kind}",
                    errors,
                    {"limit": 200, "include": "inAppPurchasePricePoint,territory"},
                )

    summary = {
        "appId": app_id,
        "bundleId": attributes.get("bundleId", BUNDLE_ID),
        "versions": len(versions["data"]),
        "customerReviews": len(reviews["data"]),
        "subscriptionGroups": len(groups["data"]),
        "subscriptions": subscription_count,
        "inAppPurchases": len(iaps["data"]),
        "reportIdentifiers": sorted(identifiers),
    }
    write_json(context / "summary.json", summary)
    return identifiers, summary


def filter_tsv_report(content: bytes, identifiers: set[str]) -> tuple[bytes, int]:
    text_content = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text_content), delimiter="\t")
    rows = list(reader)
    if not rows:
        return b"", 0
    kept = [
        row
        for row in rows[1:]
        if any(cell.strip() in identifiers for cell in row)
    ]
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(rows[0])
    writer.writerows(kept)
    return output.getvalue().encode("utf-8"), len(kept)


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def export_sales_reports(
    client: Client,
    destination: Path,
    errors: list[dict],
    *,
    vendor_number: str,
    start_date: date,
    end_date: date,
    identifiers: set[str],
) -> dict[str, Any]:
    """Export Sales & Trends reports and keep only rows for the selected app."""
    sales = destination / "sales"
    downloaded = matching_rows = unavailable = 0
    dates = list(_date_range(start_date, end_date))
    for day_index, report_date in enumerate(dates, start=1):
        rendered_date = report_date.isoformat()
        if day_index == 1 or day_index % 10 == 0 or day_index == len(dates):
            print(f"  Sales & Trends day {day_index}/{len(dates)}: {rendered_date}")
        for spec in SALES_REPORT_SPECS:
            params = {
                "filter[frequency]": "DAILY",
                "filter[reportDate]": rendered_date,
                "filter[reportSubType]": spec.report_subtype,
                "filter[reportType]": spec.report_type,
                "filter[vendorNumber]": vendor_number,
                "filter[version]": spec.version,
            }
            try:
                content = client.get_binary("/v1/salesReports", params)
                if content.startswith(b"\x1f\x8b"):
                    content = gzip.decompress(content)
                filtered, row_count = filter_tsv_report(content, identifiers)
                downloaded += 1
                matching_rows += row_count
                if row_count:
                    path = sales / spec.report_type / f"{rendered_date}.tsv"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(filtered)
            except AppStoreConnectError as error:
                if error.status_code in (400, 404):
                    unavailable += 1
                else:
                    _record_error(
                        errors, f"sales:{spec.report_type}:{rendered_date}", error
                    )
            except (OSError, UnicodeDecodeError, gzip.BadGzipFile) as error:
                _record_error(
                    errors, f"sales:{spec.report_type}:{rendered_date}", error
                )

    summary = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "reportsDownloaded": downloaded,
        "reportsUnavailable": unavailable,
        "matchingRows": matching_rows,
        "note": "TSV files contain only rows matching the selected app identifiers.",
    }
    write_json(sales / "summary.json", summary)
    return summary


def decode_segment(content: bytes, expected_size: int | None, checksum: str | None) -> bytes:
    if expected_size is not None and len(content) != expected_size:
        raise AppStoreConnectError(
            f"Downloaded segment size mismatch: expected {expected_size}, got {len(content)}"
        )
    if checksum:
        expected = checksum.casefold()
        if re.fullmatch(r"[0-9a-f]{32}", expected):
            actual = hashlib.md5(content).hexdigest()  # Apple currently uses MD5.
        elif re.fullmatch(r"[0-9a-f]{64}", expected):
            actual = hashlib.sha256(content).hexdigest()
        else:
            actual = expected  # Unknown future encoding: size + gzip checks remain.
        if actual != expected:
            raise AppStoreConnectError(
                f"Downloaded segment checksum mismatch: expected {checksum}, got {actual}"
            )
    try:
        return gzip.decompress(content)
    except (gzip.BadGzipFile, EOFError) as error:
        raise AppStoreConnectError("Downloaded report segment is not valid gzip data") from error


def download_segment(client: Client, segment: dict) -> tuple[bytes, dict]:
    attributes = segment.get("attributes", {})
    url = attributes.get("url")
    if not url:
        raise AppStoreConnectError(f"Report segment {segment['id']} has no download URL")

    # The URL is short-lived and pre-signed. Do not attach the ASC bearer token.
    content = client.download(url)
    decoded = decode_segment(
        content,
        attributes.get("sizeInBytes"),
        attributes.get("checksum"),
    )
    metadata = {
        "segmentId": segment["id"],
        "compressedSizeInBytes": len(content),
        "uncompressedSizeInBytes": len(decoded),
        "checksum": attributes.get("checksum"),
    }
    return decoded, metadata


def default_output_path(app_name: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUTPUT_DIR / f"{safe_filename(app_name)}-ASC-export-{timestamp}.zip"


def write_archive(
    client: Client,
    app: dict,
    request: dict,
    reports: list[dict],
    missing_reports: list[str],
    catalog: list[dict],
    granularity: str,
    output_path: Path,
    *,
    skip_context: bool,
    vendor_number: str,
    sales_start_date: date,
    sales_end_date: date,
) -> tuple[Path, int]:
    output_path = output_path.expanduser().resolve()
    if output_path.suffix.casefold() != ".zip":
        output_path = output_path.with_suffix(".zip")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise AppStoreConnectError(f"Destination already exists: {output_path}")

    exported_at = datetime.now(timezone.utc).isoformat()
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "exportedAt": exported_at,
        "app": {
            "id": app["id"],
            "name": app.get("attributes", {}).get("name"),
            "bundleId": app.get("attributes", {}).get("bundleId", BUNDLE_ID),
        },
        "request": {
            "id": request["id"],
            "accessType": request.get("attributes", {}).get("accessType"),
        },
        "granularity": granularity,
        "privacyNote": (
            "Usage reports can be absent or sparse when too few users opted in "
            "or Apple's privacy thresholds are not met."
        ),
        "missingPreferredReports": missing_reports,
        "reports": [],
    }

    file_count = 0
    errors: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="appstore-connect-export-") as temporary:
        staging = Path(temporary)
        analytics_dir = staging / "analytics"
        analytics_dir.mkdir()

        identifiers = {
            app["id"],
            app.get("attributes", {}).get("bundleId", BUNDLE_ID),
        }
        if skip_context:
            manifest["context"] = {"skipped": True}
        else:
            print("Exporting metadata, availability, products, prices, and reviews...")
            context_identifiers, context_summary = export_context(
                client, app, staging, errors
            )
            identifiers |= context_identifiers
            manifest["context"] = context_summary

        if vendor_number:
            print(
                f"Exporting Sales & Trends ({sales_start_date} to "
                f"{sales_end_date})..."
            )
            manifest["sales"] = export_sales_reports(
                client,
                staging,
                errors,
                vendor_number=vendor_number,
                start_date=sales_start_date,
                end_date=sales_end_date,
                identifiers=identifiers,
            )
        else:
            manifest["sales"] = {
                "skipped": True,
                "reason": "No --vendor-number or ASC_VENDOR_NUMBER supplied.",
            }

        catalog_payload = [
            {
                "id": item["id"],
                "name": item.get("attributes", {}).get("name"),
                "category": item.get("attributes", {}).get("category"),
            }
            for item in sorted(catalog, key=lambda row: row["attributes"].get("name", ""))
        ]
        write_json(analytics_dir / "catalog.json", {"data": catalog_payload})

        reports_without_instances = 0
        for report_index, report in enumerate(reports, start=1):
            attributes = report.get("attributes", {})
            name = attributes.get("name", report["id"])
            print(f"  Analytics report {report_index}/{len(reports)}: {name}")
            category = safe_filename(attributes.get("category", "uncategorized"))
            report_directory = (
                analytics_dir
                / category
                / f"{safe_filename(name)}-{safe_filename(report['id'])[:8]}"
            )
            write_json(report_directory / "report.json", {"data": report})
            report_manifest: dict[str, Any] = {
                "id": report["id"],
                "name": name,
                "category": attributes.get("category"),
                "instances": [],
            }
            try:
                instances = list_instances(client, report["id"], granularity)
                write_json(report_directory / "instances.json", {"data": instances})
            except (AppStoreConnectError, ValueError) as error:
                _record_error(errors, f"analytics-instances:{report['id']}", error)
                instances = []
            if not instances:
                reports_without_instances += 1

            for instance in instances:
                instance_attributes = instance.get("attributes", {})
                processing_date = instance_attributes.get("processingDate", "unknown-date")
                try:
                    segments = list_segments(client, instance["id"])
                    write_json(
                        report_directory / "segments" / f"{instance['id']}.json",
                        {"data": segments},
                    )
                except (AppStoreConnectError, ValueError) as error:
                    _record_error(
                        errors, f"analytics-segments:{instance['id']}", error
                    )
                    segments = []
                instance_manifest: dict[str, Any] = {
                    "id": instance["id"],
                    "processingDate": processing_date,
                    "granularity": instance_attributes.get("granularity", granularity),
                    "files": [],
                }

                for index, segment in enumerate(segments, start=1):
                    try:
                        decoded, segment_metadata = download_segment(client, segment)
                        filename = (
                            f"{safe_filename(processing_date)}__"
                            f"{safe_filename(instance['id'])[:12]}__{index:03d}.tsv"
                        )
                        path = report_directory / "data" / filename
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(decoded)
                        segment_metadata["file"] = str(path.relative_to(staging))
                        instance_manifest["files"].append(segment_metadata)
                        file_count += 1
                    except (AppStoreConnectError, OSError, ValueError) as error:
                        _record_error(
                            errors,
                            f"analytics-download:{segment.get('id', 'unknown')}",
                            error,
                        )

                report_manifest["instances"].append(instance_manifest)
            manifest["reports"].append(report_manifest)

        manifest["analyticsSummary"] = {
            "catalogReports": len(catalog),
            "reportsExported": len(reports),
            "reportsWithoutInstances": reports_without_instances,
            "segmentFiles": file_count,
        }
        manifest["errors"] = errors

        write_json(staging / "manifest.json", manifest)
        (staging / "README.txt").write_text(
            "App Store Connect Analytics export\n\n"
            "This archive contains App Store context, Apple's tab-delimited "
            "Analytics data, optional filtered Sales & Trends reports, and a "
            "manifest. It contains no App Store Connect API key, issuer "
            "credential, vendor number, private-key path, or signed token.\n\n"
            "Usage and crash reports may be empty for a low-volume app because "
            "Apple only reports opted-in data that clears its privacy thresholds.\n",
            encoding="utf-8",
        )

        archive_base = output_path.with_suffix("")
        created = Path(shutil.make_archive(str(archive_base), "zip", staging))
    if errors:
        print(f"Warning: {len(errors)} optional section(s) failed; see manifest.json.")
    return created, file_count


def print_catalog(reports: Iterable[dict]) -> None:
    for report in sorted(reports, key=lambda item: item["attributes"].get("name", "")):
        attributes = report.get("attributes", {})
        print(f"{attributes.get('category', '?'):24s} {attributes.get('name', '?')}")


def _parse_date(value: str, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise AppStoreConnectError(
            f"{flag} must use YYYY-MM-DD: {value}"
        ) from error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export App Store context, Analytics, and optional Sales & Trends "
            "reports for an acquisition, engagement, quality, and monetization diagnosis."
        )
    )
    parser.add_argument("--bundle-id", default=BUNDLE_ID)
    parser.add_argument(
        "--access-type",
        choices=("ONE_TIME_SNAPSHOT", "ONGOING"),
        default="ONE_TIME_SNAPSHOT",
        help="ONE_TIME_SNAPSHOT includes all available history (default).",
    )
    parser.add_argument(
        "--granularity",
        choices=("DAILY", "WEEKLY", "MONTHLY"),
        default="DAILY",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination ZIP. Defaults to Artifacts/AppStoreConnectExports/.",
    )
    parser.add_argument(
        "--list-reports",
        action="store_true",
        help="List the generated report catalog without downloading segments.",
    )
    parser.add_argument(
        "--all-reports",
        action="store_true",
        help="Compatibility flag; every available report is now exported by default.",
    )
    parser.add_argument(
        "--diagnostic-reports-only",
        action="store_true",
        help="Export only the acquisition, usage, quality, and commerce subset.",
    )
    parser.add_argument(
        "--no-create",
        action="store_true",
        help="Do not create a missing analytics request; only inspect/export.",
    )
    parser.add_argument(
        "--skip-context",
        action="store_true",
        help="Skip metadata, reviews, availability, products, prices, and offers.",
    )
    parser.add_argument(
        "--vendor-number",
        default=os.environ.get("ASC_VENDOR_NUMBER", ""),
        help="Optional Sales & Trends vendor number (or ASC_VENDOR_NUMBER).",
    )
    parser.add_argument(
        "--sales-days",
        type=int,
        default=90,
        help="Number of daily Sales & Trends dates to request (default: 90).",
    )
    parser.add_argument("--sales-start-date", default="")
    parser.add_argument("--sales-end-date", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.sales_days < 1 or args.sales_days > 366:
            raise AppStoreConnectError("--sales-days must be between 1 and 366")

        key_id, issuer_id, private_key = load_credentials()
        vendor_number = load_vendor_number(args.vendor_number)
        client = Client(make_jwt(key_id, issuer_id, private_key))

        print(f"Finding App Store app for {args.bundle_id}...")
        app = find_app(client, args.bundle_id)
        app_name = app.get("attributes", {}).get("name") or args.bundle_id
        print(f"Found {app_name} (Apple ID {app['id']}).")

        requests_ = list_report_requests(client, app["id"], args.access_type)
        active_requests = [
            item
            for item in requests_
            if not item.get("attributes", {}).get("stoppedDueToInactivity")
        ]
        request, reports = choose_ready_request(client, active_requests)
        if request is None:
            if active_requests:
                request = active_requests[0]
                reports = []
                print(
                    f"Analytics request {request['id']} exists, but Apple has not "
                    "generated its catalog yet. Context and Sales & Trends will "
                    "still be exported."
                )
            elif args.no_create:
                raise AppStoreConnectError(
                    f"No active {args.access_type} analytics request exists."
                )
            else:
                print(f"Creating {args.access_type} Analytics request...")
                request = create_report_request(client, app["id"], args.access_type)
                reports = []
                print(
                    f"Created request {request['id']}. Apple normally needs 24-48 "
                    "hours for Analytics, but the other sections will be exported now."
                )
        else:
            print(f"Using Analytics request {request['id']} ({len(reports)} reports).")

        if args.list_reports:
            if not reports:
                print("No Analytics report catalog is available yet.")
            print_catalog(reports)
            return 0

        if args.diagnostic_reports_only:
            selected, missing = select_reports(reports)
        else:
            selected = reports
            missing = []

        sales_end_date = (
            _parse_date(args.sales_end_date, "--sales-end-date")
            if args.sales_end_date
            else date.today() - timedelta(days=1)
        )
        sales_start_date = (
            _parse_date(args.sales_start_date, "--sales-start-date")
            if args.sales_start_date
            else sales_end_date - timedelta(days=args.sales_days - 1)
        )
        if sales_start_date > sales_end_date:
            raise AppStoreConnectError(
                "--sales-start-date must not be after --sales-end-date"
            )

        print(f"Exporting {len(selected)} Analytics report definitions...")
        output = args.output or default_output_path(app_name)
        archive, count = write_archive(
            client,
            app,
            request,
            selected,
            missing,
            reports,
            args.granularity,
            output,
            skip_context=args.skip_context,
            vendor_number=vendor_number,
            sales_start_date=sales_start_date,
            sales_end_date=sales_end_date,
        )
        print(f"Created {archive} with {count} report segment(s).")
        if missing:
            print("Unavailable preferred reports: " + ", ".join(missing))
        print("Send the ZIP for analysis; it contains no API credentials.")
        return 0
    except AppStoreConnectError as error:
        sys.stderr.write(f"Error: {error}\n")
        return 2
    except requests.RequestException as error:
        sys.stderr.write(f"Network error: {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
