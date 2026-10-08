#!/usr/bin/env python3
# Copyright (c) 2026 Jean-Baptiste Meyer
# SPDX-License-Identifier: MIT

"""Deliver localized metadata and prepared still images through ASC API 4.5.1.

Media comes from AppStore/exports/delivery/delivery-manifest.json. Runtime
Asset Library reference data determines categories, specs, placement groups
and limits. Native Duo assets remain in their dedicated group. No previews
are selected and no review submission is made. Existing legacy galleries
are never deleted as a fallback.

Run Tools/prepare_appstore_media.py --render first. Use --check-assets for
an offline preflight. Default execution reads the API to plan; --apply is
required for remote writes. Credentials: ASC_KEY_ID, ASC_ISSUER_ID and
ASC_KEY_PATH (or ASC_PRIVATE_KEY_BASE64). Dependencies: pyjwt[crypto], requests.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import json
import os
import sys
import time
from pathlib import Path

try:
    import jwt  # pyjwt[crypto]
    import requests
except ImportError:
    jwt = None
    requests = None

# ─────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "AppStore" / "metadata"
SCREENSHOTS = ROOT / "Screenshots"
BUNDLE_ID = "com.jibstudios.Meet-Your-Memory"

API_BASE = "https://api.appstoreconnect.apple.com/v1"
JWT_AUDIENCE = "appstoreconnect-v1"
JWT_TTL_SECONDS = 20 * 60  # max 20 min per Apple

# App-Store-locale → screenshot folder name. ScreenshotTests.swift
# writes screenshots to Screenshots/<size>-inch/<short-code>/ using the
# short locale code (en, fr, de…), while AppStore/metadata/ uses the
# full App-Store locale code (en-US, fr-FR, es-ES…). The value here is
# the *screenshot* folder name. Metadata folder = the App-Store locale
# itself (the dict key) — read_metadata() uses the key, not the value.
LOCALES = {
    "en-US":   "en",
    "fr-FR":   "fr",
    "it":      "it",
    "es-ES":   "es",
    "pt-PT":   "pt",
    "ja":      "ja",
    "zh-Hans": "zh-Hans",
    "hi":      "hi",
}

# When the App Store account already has an existing localization, Apple
# sometimes stores it under a different code than what the API spec lists.
# For example, French is documented as "fr-FR" but legacy accounts store
# it as just "fr". This map gives us a tolerant lookup — when our target
# locale (left) isn't found verbatim in the existing localizations on
# App Store Connect, also try the alias (right).
LOCALE_ALIASES = {
    "en-US": ("en",),
    "fr-FR": ("fr",),
    "es-ES": ("es",),
    "pt-PT": ("pt",),
}


def resolve_locale_id(by_locale: dict[str, str], target: str) -> str | None:
    """Look up an existing localization id by target locale, allowing
    common aliases (fr-FR → fr, etc.)."""
    if target in by_locale:
        return by_locale[target]
    for alt in LOCALE_ALIASES.get(target, ()):
        if alt in by_locale:
            return by_locale[alt]
    return None

def media_selection(locales, screenshots_only=False, placements=None):
    from appstore_asset_library import selection
    config = json.loads((ROOT / 'AppStore/media/meet-your-memory.json').read_text())
    placements = {'iphone-medium', 'iphone-large', 'ipad', 'duo'} if screenshots_only else placements
    return selection(config, ROOT / config['outputRoot'], locales or list(LOCALES),
                     placements=placements, images=True, previews=False)


def check_local_assets(locales, screenshots_only=False, placements=None):
    try:
        assets = media_selection(locales, screenshots_only, placements)
        print(f"Validated {len(assets)} prepared still images for ASC API 4.5.1; no network requests")
        return True
    except (ValueError, FileNotFoundError, KeyError) as error:
        print(f"Media preflight failed: {error}")
        return False


# ─────────────────────────────────────────────────────────────────────────
# Auth + HTTP
# ─────────────────────────────────────────────────────────────────────────

def load_credentials() -> tuple[str, str, str]:
    if jwt is None or requests is None:
        sys.exit("❌ Missing dependencies. Install with:\n   pip3 install 'pyjwt[crypto]' requests")
    key_id    = os.environ.get("ASC_KEY_ID")
    issuer_id = os.environ.get("ASC_ISSUER_ID")
    key_path  = os.environ.get("ASC_KEY_PATH")
    key_base64 = os.environ.get("ASC_PRIVATE_KEY_BASE64")
    missing = [n for n, v in
               (("ASC_KEY_ID", key_id),
                ("ASC_ISSUER_ID", issuer_id))
               if not v]
    if not key_path and not key_base64:
        missing.append("ASC_KEY_PATH or ASC_PRIVATE_KEY_BASE64")
    if missing:
        sys.stderr.write(
            f"❌ Missing env vars: {', '.join(missing)}\n"
            "   Generate an API key at App Store Connect → Users and Access\n"
            "   → Integrations → App Store Connect API, then:\n"
            "       export ASC_KEY_ID=...\n"
            "       export ASC_ISSUER_ID=...\n"
            "       export ASC_KEY_PATH=~/keys/AuthKey_XXXXX.p8\n"
            "   or set ASC_PRIVATE_KEY_BASE64 as a secret in Xcode Cloud.\n"
        )
        sys.exit(2)

    if key_path:
        expanded = Path(os.path.expanduser(key_path))
        if not expanded.is_file():
            sys.stderr.write(f"❌ ASC_KEY_PATH not found: {expanded}\n")
            sys.exit(2)
        private_key = expanded.read_text(encoding="utf-8")
    else:
        try:
            compact = "".join(key_base64.split())
            private_key = base64.b64decode(
                compact, validate=True
            ).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            sys.stderr.write(
                "❌ ASC_PRIVATE_KEY_BASE64 is not a valid Base64-encoded "
                "UTF-8 App Store Connect private key.\n"
            )
            sys.exit(2)

    if "-----BEGIN PRIVATE KEY-----" not in private_key:
        sys.stderr.write(
            "❌ App Store Connect private key is not a PKCS#8 PEM key.\n"
        )
        sys.exit(2)
    return key_id, issuer_id, private_key


def make_jwt(key_id: str, issuer_id: str, private_key: str) -> str:
    now = int(time.time())
    payload = {
        "iss": issuer_id,
        "exp": now + JWT_TTL_SECONDS,
        "aud": JWT_AUDIENCE,
    }
    headers = {"kid": key_id, "typ": "JWT"}
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


class Client:
    """App Store Connect REST wrapper; signed upload URLs use another client."""

    def __init__(self, token: str, dry_run: bool, token_provider=None):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["Accept"] = "application/json"
        self.dry_run = dry_run
        self.token_provider = token_provider
        self.token_issued_at = time.monotonic()

    def refresh_authorization(self) -> None:
        if self.token_provider and time.monotonic() - self.token_issued_at >= 900:
            self.session.headers['Authorization'] = f'Bearer {self.token_provider()}'
            self.token_issued_at = time.monotonic()

    @staticmethod
    def api_url(path: str) -> str:
        url = path if path.startswith("http") else API_BASE + path
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'api.appstoreconnect.apple.com' or not parsed.path.startswith('/v1/'):
            raise ValueError('Refusing to send an App Store Connect token outside the public API')
        return url

    def get(self, path: str, **params) -> dict:
        url = self.api_url(path)
        for attempt in range(4):
            self.refresh_authorization()
            try:
                r = self.session.get(url, params=params, timeout=60, allow_redirects=False)
                if r.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                    self.wait_for_retry(r, attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError('Read retry exhausted')

    @staticmethod
    def wait_for_retry(response, attempt: int) -> None:
        """Honor Apple's hourly cooldown without a retry storm or stale JWT."""
        fallback = min(60 * 2 ** attempt, 600) if response.status_code == 429 else 2 ** attempt
        value = response.headers.get('Retry-After')
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            try:
                seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                seconds = fallback
        if not math.isfinite(seconds):
            seconds = fallback
        seconds = max(0, seconds)
        if seconds > 3600:
            raise RuntimeError('Apple requested a retry after more than one hour; reservation IDs remain saved')
        if response.status_code != 429:
            seconds = min(seconds, 30)
        else:
            print(f'Apple API rate limit: respecting Retry-After ({seconds:.0f}s); saved assets retained', flush=True)
        # A yielded terminal session remains observable while the client waits.
        # Refresh authorization on the next request, after this entire cooldown.
        while seconds > 0:
            interval = min(seconds, 30)
            time.sleep(interval)
            seconds -= interval

    def _mutate(self, method: str, path: str, payload: dict | None = None,
                expect_json: bool = True) -> dict:
        url = self.api_url(path)
        if self.dry_run:
            print(f"    DRY {method:6s} {path}")
            if payload:
                print(f"      └─ {json.dumps(payload)[:160]}…")
            return {}
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        for attempt in range(4):
            self.refresh_authorization()
            try:
                r = self.session.request(method, url, headers=headers,
                                         data=json.dumps(payload) if payload else None,
                                         timeout=60, allow_redirects=False)
                # An explicit 429 rejects the request before acceptance. An
                # uncertain POST timeout/5xx still requires journal reconciliation.
                if (r.status_code == 429 or (method != 'POST' and r.status_code in {500, 502, 503, 504})) and attempt < 3:
                    self.wait_for_retry(r, attempt)
                    continue
                break
            except (requests.ConnectionError, requests.Timeout):
                if method == 'POST' or attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        if method == 'DELETE' and r.status_code == 404:
            return {}  # A resumed cleanup can encounter an already removed record.
        if not r.ok:
            # Print the FULL body — Apple's error messages can include
            # detail past the first 600 chars (e.g., a complete list of
            # valid enum values).
            sys.stderr.write(f"❌ {method} {path} → {r.status_code}\n{r.text}\n")
            r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return {}
        return r.json() if expect_json else {}

    def post(self, path: str, payload: dict, expect_json: bool = True) -> dict:
        return self._mutate("POST", path, payload, expect_json)

    def patch(self, path: str, payload: dict, expect_json: bool = True) -> dict:
        return self._mutate("PATCH", path, payload, expect_json)

    def delete(self, path: str) -> dict:
        return self._mutate("DELETE", path, None, expect_json=False)


# ─────────────────────────────────────────────────────────────────────────
# Helpers for the asset-upload dance
# ─────────────────────────────────────────────────────────────────────────

def read_metadata(store_locale: str) -> dict[str, str]:
    """Read AppStore/metadata/<store-locale>/*.txt → dict. Folder name
    matches the App-Store locale (en-US, fr-FR, es-ES, …), NOT the
    short code used by the screenshot tests."""
    base = METADATA / store_locale
    if not base.is_dir():
        return {}
    fields = ("name", "subtitle", "promotional_text", "description",
              "keywords", "release_notes", "support_url",
              "marketing_url", "privacy_url", "copyright")
    out: dict[str, str] = {}
    for f in fields:
        p = base / f"{f}.txt"
        if p.exists():
            out[f] = p.read_text(encoding="utf-8").strip()
    return out


# ─────────────────────────────────────────────────────────────────────────
# Text-field uploads
# ─────────────────────────────────────────────────────────────────────────

def find_app(client: Client) -> str:
    print(f"→ Finding app with bundleId={BUNDLE_ID}")
    resp = client.get("/apps", **{"filter[bundleId]": BUNDLE_ID})
    apps = resp.get("data", [])
    if not apps:
        sys.exit(f"❌ No app found for bundle ID {BUNDLE_ID}")
    app_id = apps[0]["id"]
    name = apps[0]["attributes"]["name"]
    print(f"   id={app_id}  name={name}")
    return app_id


def find_editable_version(client: Client, app_id: str) -> str:
    print("→ Finding editable App Store version (PREPARE_FOR_SUBMISSION)")
    resp = client.get(
        f"/apps/{app_id}/appStoreVersions",
        **{"filter[platform]": "IOS", "limit": 20},
    )
    editable = [
        v for v in resp.get("data", [])
        if v["attributes"]["appStoreState"] in
           ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED",
            "METADATA_REJECTED", "INVALID_BINARY", "WAITING_FOR_REVIEW",
            "READY_FOR_REVIEW")
    ]
    if not editable:
        sys.exit(
            "❌ No editable App Store version. Create one in the web UI:\n"
            "   App Store Connect → My Apps → Meet Your Memory → "
            "iOS App → ⊕ Version or Platform."
        )
    v = editable[0]
    print(f"   version={v['attributes']['versionString']}  "
          f"state={v['attributes']['appStoreState']}  id={v['id']}")
    return v["id"]


def update_appinfo_localizations(client: Client, app_id: str,
                                 locales: list[str]) -> None:
    print("→ Updating appInfo localizations (name, subtitle, privacy URL)")
    # The current editable appInfo
    appinfos = client.get(f"/apps/{app_id}/appInfos").get("data", [])
    appinfo_id = next(
        (a["id"] for a in appinfos
         if a["attributes"]["appStoreState"] != "READY_FOR_SALE"),
        None,
    ) or appinfos[0]["id"]

    # Copyright is set on appStoreVersions (not appInfos) via
    # update_version_copyright() — called from main(), not here.

    existing = client.get(
        f"/appInfos/{appinfo_id}/appInfoLocalizations"
    ).get("data", [])
    by_locale = {loc["attributes"]["locale"]: loc["id"] for loc in existing}

    for store_locale, folder in LOCALES.items():
        if locales and store_locale not in locales:
            continue
        # Metadata folder is named after the App-Store locale (en-US,
        # fr-FR, …); screenshot folder uses the short code (en, fr, …).
        meta = read_metadata(store_locale)
        if not meta:
            print(f"   [{store_locale}] no metadata folder "
                  f"(AppStore/metadata/{store_locale}/) — skipping")
            continue
        attrs = {
            "name":             meta.get("name"),
            "subtitle":         meta.get("subtitle"),
            "privacyPolicyUrl": meta.get("privacy_url"),
        }
        attrs = {k: v for k, v in attrs.items() if v}
        if not attrs:
            continue
        existing_id = resolve_locale_id(by_locale, store_locale)
        print(f"   [{store_locale}] {sorted(attrs)}"
              + (f"  (existing as alias)" if existing_id and store_locale not in by_locale else ""))
        try:
            if existing_id:
                client.patch(
                    f"/appInfoLocalizations/{existing_id}",
                    {"data": {"id": existing_id,
                              "type": "appInfoLocalizations",
                              "attributes": attrs}},
                )
            else:
                client.post("/appInfoLocalizations", {
                    "data": {
                        "type": "appInfoLocalizations",
                        "attributes": {**attrs, "locale": store_locale},
                        "relationships": {
                            "appInfo": {
                                "data": {"id": appinfo_id, "type": "appInfos"}
                            }
                        },
                    }
                })
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else ""
            sys.stderr.write(
                f"   ⚠️  {store_locale} skipped — {e}\n{body[:400]}\n"
            )


def update_version_copyright(client: Client, version_id: str) -> None:
    """Copyright is a top-level appStoreVersions attribute (not per-locale).
    Read it from the English metadata folder and PATCH it onto the
    version. Safe to call any time — Apple allows editing this field in
    PREPARE_FOR_SUBMISSION."""
    copyright_text = read_metadata("en-US").get("copyright", "")
    if not copyright_text:
        return
    print(f"→ Updating version copyright: {copyright_text!r}")
    try:
        client.patch(f"/appStoreVersions/{version_id}", {
            "data": {
                "id": version_id,
                "type": "appStoreVersions",
                "attributes": {"copyright": copyright_text},
            }
        })
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        sys.stderr.write(f"   ⚠️  copyright PATCH skipped — {e}\n{body[:400]}\n")


def update_version_localizations(client: Client, version_id: str,
                                 locales: list[str]) -> None:
    print("→ Updating version localizations (description, keywords, URLs, "
          "what's new, promo text)")
    existing = client.get(
        f"/appStoreVersions/{version_id}/appStoreVersionLocalizations"
    ).get("data", [])
    by_locale = {loc["attributes"]["locale"]: loc["id"] for loc in existing}

    # whatsNew is only editable on updates (1.1+). On the very first app
    # version (1.0) Apple returns:
    #   409 STATE_ERROR "Attribute 'whatsNew' cannot be edited at this time"
    # Track whether we've discovered this so subsequent locales skip the
    # field up front instead of round-tripping the error each time.
    whats_new_blocked = False

    for store_locale, folder in LOCALES.items():
        if locales and store_locale not in locales:
            continue
        # Metadata folder is named after the App-Store locale (en-US,
        # fr-FR, …); screenshot folder uses the short code (en, fr, …).
        meta = read_metadata(store_locale)
        if not meta:
            print(f"   [{store_locale}] no metadata folder "
                  f"(AppStore/metadata/{store_locale}/) — skipping")
            continue
        attrs = {
            "description":      meta.get("description"),
            "keywords":         meta.get("keywords"),
            "promotionalText":  meta.get("promotional_text"),
            "marketingUrl":     meta.get("marketing_url"),
            "supportUrl":       meta.get("support_url"),
            "whatsNew":         meta.get("release_notes"),
        }
        attrs = {k: v for k, v in attrs.items() if v}
        if whats_new_blocked:
            attrs.pop("whatsNew", None)

        existing_id = resolve_locale_id(by_locale, store_locale)
        print(f"   [{store_locale}] {sorted(attrs)}"
              + (f"  (existing as alias)" if existing_id and store_locale not in by_locale else ""))
        try:
            if existing_id:
                client.patch(
                    f"/appStoreVersionLocalizations/{existing_id}",
                    {"data": {"id": existing_id,
                              "type": "appStoreVersionLocalizations",
                              "attributes": attrs}},
                )
            else:
                client.post("/appStoreVersionLocalizations", {
                    "data": {
                        "type": "appStoreVersionLocalizations",
                        "attributes": {**attrs, "locale": store_locale},
                        "relationships": {
                            "appStoreVersion": {
                                "data": {"id": version_id,
                                         "type": "appStoreVersions"}
                            }
                        },
                    }
                })
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else ""
            # Detect the whatsNew lockout and retry once without it.
            if "whatsNew" in body and "cannot be edited" in body and "whatsNew" in attrs:
                print(f"      ↻ retry without whatsNew (first release — Apple "
                      "doesn't accept release notes for v1.0)")
                whats_new_blocked = True
                attrs.pop("whatsNew", None)
                if existing_id:
                    client.patch(
                        f"/appStoreVersionLocalizations/{existing_id}",
                        {"data": {"id": existing_id,
                                  "type": "appStoreVersionLocalizations",
                                  "attributes": attrs}},
                    )
                else:
                    client.post("/appStoreVersionLocalizations", {
                        "data": {
                            "type": "appStoreVersionLocalizations",
                            "attributes": {**attrs, "locale": store_locale},
                            "relationships": {
                                "appStoreVersion": {
                                    "data": {"id": version_id,
                                             "type": "appStoreVersions"}
                                }
                            },
                        }
                    })
            else:
                # Surface the failure but keep going to the next locale.
                sys.stderr.write(
                    f"   ⚠️  {store_locale} skipped — {e}\n{body[:400]}\n"
                )


# ─────────────────────────────────────────────────────────────────────────
# Screenshot upload (3-step: create, PUT bytes, commit)
# ─────────────────────────────────────────────────────────────────────────

def upload_screenshots(client, app_id, version_id, locales, *, screenshots_only=False,
                       verify_only=False, processing_timeout=600, placements=None):
    """Deliver screenshots plus header/search artwork through the Asset Library."""
    from appstore_asset_library import collection, execute, verify, Journal, run_lock
    assets = media_selection(locales, screenshots_only, placements)
    localizations, _ = collection(client, f'/appStoreVersions/{version_id}/appStoreVersionLocalizations', limit=200)
    by_locale = {item['attributes']['locale']: item['id'] for item in localizations}
    selected = {asset['locale'] for asset in assets}
    mapping = {locale: resolve_locale_id(by_locale, locale) for locale in selected}
    if any(identifier is None for identifier in mapping.values()):
        raise ValueError('Every selected locale must have its own App Store version localization')
    cache = ROOT / 'AppStore/exports/.work/api'
    cache.mkdir(parents=True, exist_ok=True)
    with run_lock(cache / 'delivery.lock'):
        journal = Journal(cache / 'journal.json', app_id)
        if not verify_only:
            execute(client, app_id, version_id, mapping, assets, journal,
                    report_path=cache / 'upload-report.json', cache_root=cache,
                    processing_timeout=processing_timeout, cleanup_library=False)
        if verify_only or not client.dry_run:
            report = verify(client, version_id, mapping, assets, journal, cache / 'verification-report.json')
            print(f"Independent server check: {len(assets)} assets, {len(report['placements'])} ordered galleries verified")


def probe_locales(client: Client, app_id: str, version_id: str) -> None:
    """Print what locales App Store Connect already has for this app + the
    editable version. Use this to debug locale-mismatch issues — Apple
    sometimes uses fr vs fr-FR, en vs en-US, etc."""
    print("→ Probing existing localizations")
    appinfos = client.get(f"/apps/{app_id}/appInfos").get("data", [])
    appinfo_id = next(
        (a["id"] for a in appinfos
         if a["attributes"]["appStoreState"] != "READY_FOR_SALE"),
        None,
    ) or appinfos[0]["id"]

    info_locs = client.get(
        f"/appInfos/{appinfo_id}/appInfoLocalizations"
    ).get("data", [])
    print(f"   appInfo locales:    "
          f"{sorted(l['attributes']['locale'] for l in info_locs)}")

    ver_locs = client.get(
        f"/appStoreVersions/{version_id}/appStoreVersionLocalizations"
    ).get("data", [])
    print(f"   appVersion locales: "
          f"{sorted(l['attributes']['locale'] for l in ver_locs)}")

    expected = sorted(LOCALES.keys())
    have_app = {l["attributes"]["locale"] for l in info_locs}
    have_ver = {l["attributes"]["locale"] for l in ver_locs}

    print(f"   our target codes:   {expected}")
    print(f"   missing on appInfo: "
          f"{sorted(set(expected) - have_app - set().union(*(set(v) for v in LOCALE_ALIASES.values())))}")
    print(f"   missing on appVer:  "
          f"{sorted(set(expected) - have_ver - set().union(*(set(v) for v in LOCALE_ALIASES.values())))}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to App Store Connect "
                             "(default is dry-run).")
    parser.add_argument("--locales", default="",
                        help="Comma-separated subset of App-Store locale "
                             "codes (e.g. 'en-US,fr-FR'). Empty = all.")
    parser.add_argument("--skip-text", action="store_true",
                        help="Skip name/subtitle/description/etc. uploads.")
    parser.add_argument("--skip-screenshots", action="store_true",
                        help="Skip screenshot uploads.")
    parser.add_argument("--probe", action="store_true",
                        help="Just dump what locales already exist on App "
                             "Store Connect, then exit. No writes.")
    parser.add_argument("--check-assets", action="store_true",
                        help="Validate and list local screenshots, "
                             "then exit without credentials or network I/O.")
    parser.add_argument('--screenshots-only', action='store_true',
                        help='Select screenshot galleries; exclude header/search creatives.')
    parser.add_argument('--placements', default='',
                        help='Comma-separated subset: header,search,duo,iphone-medium,iphone-large,ipad.')
    parser.add_argument('--verify-assets', action='store_true',
                        help='Read-only verification of selected uploaded assets and placement order.')
    parser.add_argument('--processing-timeout', type=int, default=600,
                        help='Whole-batch processing wait in seconds; reservations are kept on timeout.')
    args = parser.parse_args()
    placements = {p.strip() for p in args.placements.split(',') if p.strip()} or None
    if placements and (placements - {'header','search','duo','iphone-medium','iphone-large','ipad'}):
        parser.error('Unknown placement')
    if placements and args.screenshots_only:
        parser.error('Choose either placements or screenshots-only')
    if args.processing_timeout < 0:
        parser.error('processing-timeout must be non-negative')
    if args.verify_assets:
        args.apply = False
        args.skip_text = True

    locales = [l.strip() for l in args.locales.split(",") if l.strip()]
    unknown = set(locales) - set(LOCALES.keys())
    if unknown:
        sys.exit(f"❌ Unknown locale(s): {sorted(unknown)}. "
                 f"Valid: {sorted(LOCALES.keys())}")

    should_check_assets = not args.skip_screenshots
    if args.check_assets or (args.apply and should_check_assets):
        assets_valid = check_local_assets(locales, args.screenshots_only, placements)
        if args.check_assets or not assets_valid:
            return 0 if assets_valid else 1

    key_id, issuer_id, key_path = load_credentials()
    token = make_jwt(key_id, issuer_id, key_path)
    client = Client(token, dry_run=not args.apply, token_provider=lambda: make_jwt(key_id, issuer_id, key_path))

    mode = "VERIFY (read-only)" if args.verify_assets else "APPLY ✏️" if args.apply else "DRY-RUN 🟡 (use --apply to write)"
    print(f"App Store Connect upload — {mode}")
    print(f"  bundle: {BUNDLE_ID}")
    print(f"  locales: {locales or 'ALL 8'}")
    print()

    app_id = find_app(client)
    version_id = find_editable_version(client, app_id)
    print()

    if args.probe:
        probe_locales(client, app_id, version_id)
        return 0

    if not args.skip_text:
        update_appinfo_localizations(client, app_id, locales)
        print()
        update_version_copyright(client, version_id)
        print()
        update_version_localizations(client, version_id, locales)
        print()

    if not args.skip_screenshots:
        upload_screenshots(client, app_id, version_id, locales,
                           screenshots_only=args.screenshots_only,
                           verify_only=args.verify_assets, processing_timeout=args.processing_timeout,
                           placements=placements)
        print()


    # Final state probe so you can see exactly what's now on App Store.
    print("→ Final state on App Store Connect:")
    probe_locales(client, app_id, version_id)

    print()
    print("✅ Verification complete." if args.verify_assets else
          "✅ Done." if args.apply else "✅ Dry-run complete. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
