#!/usr/bin/env python3
# Copyright (c) 2026 Jean-Baptiste Meyer
# SPDX-License-Identifier: MIT

"""
upload_appstore.py — push the per-locale metadata and screenshots to
App Store Connect via the public REST API.

What it uploads
───────────────
• Per-locale text fields, read from AppStore/metadata/<locale>/:
    name, subtitle               → appInfoLocalizations
    promotionalText, description,
    keywords, whatsNew (release_notes),
    marketingUrl, supportUrl     → appStoreVersionLocalizations
    privacyPolicyUrl             → appInfoLocalizations
    copyright                    → appInfo

• Screenshots, read from Screenshots/<size>/<lang>/<NN>-*.jpg
    iPhone:
      6.9-inch       → APP_IPHONE_67
    iPad:
      ipad-13-inch   → APP_IPAD_PRO_3GEN_129
  The folder name is decided by the captured PNG pixel size — see
  ScreenshotRig.displayClass in Meet Your MemoryUITests.

Auth
────
Generates an ES256-signed JWT against your App Store Connect API key.
You need a Team or Individual API key — generate one at:

  App Store Connect → Users and Access → Integrations →
  App Store Connect API → Team Keys → Generate API Key

Then export the three credentials. Local runs can point at the downloaded
key file; Xcode Cloud can provide the same key as a Base64 secret:

  export ASC_KEY_ID=ABCDE12345           # the Key ID column
  export ASC_ISSUER_ID=12345678-...      # Issuer ID at the top of the page
  export ASC_KEY_PATH=~/keys/AuthKey_ABCDE12345.p8

  # Xcode Cloud alternative to ASC_KEY_PATH:
  export ASC_PRIVATE_KEY_BASE64="$(base64 < AuthKey_ABCDE12345.p8)"

Usage
─────
  python3 Tools/upload_appstore.py                   # dry-run (default)
  python3 Tools/upload_appstore.py --apply           # actually push
  python3 Tools/upload_appstore.py --apply --locales en-US,fr-FR   # subset
  python3 Tools/upload_appstore.py --check-assets --locales en-US
  python3 Tools/upload_appstore.py --apply --skip-screenshots
  python3 Tools/upload_appstore.py --apply --skip-text

Safety
──────
• Default is `--dry-run`: prints every request that would be made, no
  network writes.
• `--apply` is required to mutate live data.
• Targets the version currently in `PREPARE_FOR_SUBMISSION` state — does
  NOT create a new version. Add one in the web UI first.
• Existing screenshots in each device-class set are deleted before the
  new ones are uploaded (otherwise the set accumulates).
• A complete six-image local gallery is required before a live screenshot
  set is deleted. Use --check-assets to inspect the plan without credentials.

Dependencies
────────────
  pip3 install pyjwt[crypto] requests
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
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
    "fr-FR": ("fr", "fr-CA"),
    "es-ES": ("es", "es-MX"),
    "pt-PT": ("pt", "pt-BR"),
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

# App Store Connect accepts one largest-display set per device family and
# scales it for smaller displays. APP_IPHONE_67 is Apple's API enum for the
# 6.9-inch iPhone set; APP_IPAD_PRO_3GEN_129 is the 13-inch iPad set.
#
# Maps Apple-enum candidates (first hit wins) → local folder name written
# by ScreenshotTests. The folder name is derived from the captured PNG/JPEG
# pixel size — see displayClass(forImageData:) in ScreenshotRig.swift.
#
SCREENSHOT_DEVICE_CLASSES: list[tuple[list[str], str]] = [
    # ── iPhone ─────────────────────────────────────────────────────────
    # 6.9-inch is the only iPhone size Apple currently requires; uploading
    # just this set covers the full iPhone store listing.
    (["APP_IPHONE_67"], "6.9-inch"),

    # ── iPad ───────────────────────────────────────────────────────────
    # Apple scales this 13-inch set for smaller iPad displays.
    (["APP_IPAD_PRO_3GEN_129"], "ipad-13-inch"),
]

# Screen ordering — Apple displays whatever order we upload; pin it
# explicitly so 01-map appears first in the listing. Must match the
# files written by ScreenshotRig.swift (8-stage flow as of v1.4 with
# the Groups feature).
SCREENSHOT_ORDER = [
    "01-home.jpg",
    "02-visual-memory.jpg",
    "03-spatial-memory.jpg",
    "04-association-memory.jpg",
    "05-memory-profile.jpg",
    "06-history.jpg",
]



def md5_checksum(path: Path) -> str:
    """Return Apple's required sourceFileChecksum for an upload commit."""
    # MD5 is mandated here by Apple's upload protocol; it isn't used for
    # authentication or any security decision in this client.
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_screenshot_set(directory: Path) -> tuple[list[Path], list[str]]:
    """Return the ordered gallery and the filenames it is missing.

    A partial local gallery must never trigger deletion of a complete live
    App Store set.
    """
    paths = [directory / name for name in SCREENSHOT_ORDER]
    missing = [path.name for path in paths if not path.is_file()]
    return ([path for path in paths if path.is_file()], missing)



def check_local_assets(locales: list[str]) -> bool:
    """Print and validate the exact six-image upload plan."""
    print("Local App Store screenshot check")
    found_any = False
    valid = True
    for store_locale, folder in LOCALES.items():
        if locales and store_locale not in locales:
            continue
        print(f"  [{store_locale}]")
        for _, size_folder in SCREENSHOT_DEVICE_CLASSES:
            directory = SCREENSHOTS / size_folder / folder
            shots, missing = local_screenshot_set(directory)
            if not directory.is_dir() and not shots:
                continue
            found_any = found_any or bool(shots)
            if missing:
                valid = False
                print(f"    ✗ {size_folder}: incomplete screenshots "
                      f"({len(shots)}/{len(SCREENSHOT_ORDER)}); "
                      f"missing {', '.join(missing)}")
            else:
                print(f"    ✓ {size_folder}: {len(shots)} screenshots "
                      f"({', '.join(path.name for path in shots)})")
    if not found_any:
        print(f"  ✗ no screenshots found below {SCREENSHOTS}")
        return False
    return valid

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
    """Thin App Store Connect REST wrapper with dry-run support."""

    def __init__(self, token: str, dry_run: bool):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["Accept"] = "application/json"
        self.dry_run = dry_run

    def get(self, path: str, **params) -> dict:
        url = path if path.startswith("http") else API_BASE + path
        r = self.session.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def _mutate(self, method: str, path: str, payload: dict | None = None,
                expect_json: bool = True) -> dict:
        url = path if path.startswith("http") else API_BASE + path
        if self.dry_run:
            print(f"    DRY {method:6s} {path}")
            if payload:
                print(f"      └─ {json.dumps(payload)[:160]}…")
            return {}
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        r = self.session.request(method, url, headers=headers,
                                 data=json.dumps(payload) if payload else None,
                                 timeout=60)
        if r.status_code == 204 or not r.content:
            return {}
        if not r.ok:
            # Print the FULL body — Apple's error messages can include
            # detail past the first 600 chars (e.g., a complete list of
            # valid enum values).
            sys.stderr.write(f"❌ {method} {path} → {r.status_code}\n{r.text}\n")
            r.raise_for_status()
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

def upload_screenshots(client: Client, version_id: str,
                       locales: list[str]) -> None:
    print("→ Uploading screenshots")

    # Build a map locale → set-id per device-class. Existing sets must be
    # rotated: get them first, then create+wipe per device class.
    version_locs = client.get(
        f"/appStoreVersions/{version_id}/appStoreVersionLocalizations"
    ).get("data", [])
    loc_id_by_locale = {l["attributes"]["locale"]: l["id"]
                        for l in version_locs}

    for store_locale, folder in LOCALES.items():
        if locales and store_locale not in locales:
            continue
        loc_id = resolve_locale_id(loc_id_by_locale, store_locale)
        if not loc_id:
            print(f"   [{store_locale}] no version-localization "
                  f"(neither '{store_locale}' nor aliases "
                  f"{LOCALE_ALIASES.get(store_locale, ())} found) — "
                  "skipping screenshots")
            continue
        alias_note = ("  (matched alias)"
                      if store_locale not in loc_id_by_locale else "")
        print(f"   [{store_locale}]{alias_note}")

        # Existing screenshot sets for this locale
        sets = client.get(
            f"/appStoreVersionLocalizations/{loc_id}/appScreenshotSets"
        ).get("data", [])
        set_by_class = {s["attributes"]["screenshotDisplayType"]: s["id"]
                        for s in sets}

        for class_candidates, size_folder in SCREENSHOT_DEVICE_CLASSES:
            src = SCREENSHOTS / size_folder / folder
            if not src.is_dir():
                continue
            shots, missing = local_screenshot_set(src)
            if not shots:
                continue
            if missing:
                sys.stderr.write(
                    f"   ⚠️  refusing to replace {size_folder}/{folder}: "
                    f"local gallery is incomplete ({len(shots)}/"
                    f"{len(SCREENSHOT_ORDER)}); missing "
                    f"{', '.join(missing)}\n"
                )
                continue

            # 1) Get or create the set — try each candidate display-type
            #    until one works. Apple's API rejects unknown values with
            #    409 ENTITY_ERROR.ATTRIBUTE.TYPE.
            set_id: str | None = None
            chosen_class: str | None = None
            for candidate in class_candidates:
                if candidate in set_by_class:
                    set_id = set_by_class[candidate]
                    chosen_class = candidate
                    break
                if client.dry_run:
                    chosen_class = candidate
                    set_id = "DRYRUN-SET"
                    break
                try:
                    resp = client.post("/appScreenshotSets", {
                        "data": {
                            "type": "appScreenshotSets",
                            "attributes": {
                                "screenshotDisplayType": candidate
                            },
                            "relationships": {
                                "appStoreVersionLocalization": {
                                    "data": {
                                        "id": loc_id,
                                        "type": "appStoreVersionLocalizations",
                                    }
                                }
                            },
                        }
                    })
                    set_id = resp["data"]["id"]
                    chosen_class = candidate
                    break
                except requests.HTTPError as e:
                    body = e.response.text if e.response is not None else ""
                    # Treat ANY error during set creation as a reason to
                    # try the next candidate. Apple's API sometimes
                    # rejects 409 with codes other than ATTRIBUTE.TYPE
                    # (e.g., already-exists, region restrictions, asset
                    # state). We don't want one bad candidate to stop us
                    # from trying APP_IPHONE_67 as a fallback.
                    print(f"      ↪ {candidate} rejected ({e}); "
                          "trying next candidate")
                    continue

            if set_id is None:
                sys.stderr.write(
                    f"   ⚠️  no valid screenshotDisplayType for "
                    f"{size_folder} — skipping\n"
                )
                continue

            print(f"      {chosen_class}  ({size_folder})  "
                  f"{len(shots)} shots")

            # 2) Wipe existing shots in this set so re-runs don't double up.
            if set_id != "DRYRUN-SET" and not client.dry_run:
                existing = client.get(
                    f"/appScreenshotSets/{set_id}/appScreenshots"
                ).get("data", [])
                for shot in existing:
                    try:
                        client.delete(f"/appScreenshots/{shot['id']}")
                    except requests.HTTPError as e:
                        sys.stderr.write(f"      ⚠️  delete failed: {e}\n")

            # 3) Upload each shot — keep going past per-file failures.
            uploaded_ids: list[str] = []
            for shot_path in shots:
                try:
                    uploaded_ids.append(upload_one(client, set_id, shot_path))
                except (requests.HTTPError, RuntimeError) as e:
                    body = (
                        e.response.text
                        if isinstance(e, requests.HTTPError)
                        and e.response is not None
                        else ""
                    )
                    sys.stderr.write(
                        f"      ⚠️  {shot_path.name} failed: {e}\n"
                        f"{body[:300]}\n"
                    )

            # Creation order is not a storefront ordering contract. Explicitly
            # replace the relationship in the same order as SCREENSHOT_ORDER.
            if len(uploaded_ids) == len(shots):
                try:
                    client.patch(
                        f"/appScreenshotSets/{set_id}/relationships/appScreenshots",
                        {"data": [
                            {"type": "appScreenshots", "id": screenshot_id}
                            for screenshot_id in uploaded_ids
                        ]},
                        expect_json=False,
                    )
                    print("        ✓ screenshot order committed")
                except requests.HTTPError as error:
                    sys.stderr.write(
                        f"      ⚠️  screenshots uploaded but explicit "
                        f"ordering failed: {error}\n"
                    )
            else:
                sys.stderr.write(
                    "      ⚠️  screenshot order not committed because one or "
                    "more uploads failed\n"
                )


def upload_one(client: Client, set_id: str, path: Path) -> str:
    size = path.stat().st_size

    if client.dry_run:
        print(f"        DRY  upload {path.name}  ({size} bytes)")
        return f"DRYRUN-{path.name}"

    # 1. reserve the upload — returns upload URLs + headers
    resp = client.post("/appScreenshots", {
        "data": {
            "type": "appScreenshots",
            "attributes": {
                "fileName": path.name,
                "fileSize": size,
            },
            "relationships": {
                "appScreenshotSet": {
                    "data": {"id": set_id, "type": "appScreenshotSets"}
                }
            },
        }
    })
    shot_id = resp["data"]["id"]
    ops = resp["data"]["attributes"]["uploadOperations"]
    if not ops:
        raise RuntimeError(f"No uploadOperations for {path.name}")

    # 2. PUT the file in chunks per the upload operation contract
    with path.open("rb") as fh:
        for op in ops:
            fh.seek(op["offset"])
            chunk = fh.read(op["length"])
            headers = {h["name"]: h["value"] for h in op["requestHeaders"]}
            r = requests.request(op["method"], op["url"],
                                 headers=headers, data=chunk, timeout=120)
            r.raise_for_status()

    # 3. commit the upload
    client.patch(f"/appScreenshots/{shot_id}", {
        "data": {
            "id": shot_id,
            "type": "appScreenshots",
            "attributes": {
                "uploaded": True,
                "sourceFileChecksum": md5_checksum(path),
            },
        }
    })
    print(f"        ✓ {path.name}")
    return shot_id


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

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
    args = parser.parse_args()

    locales = [l.strip() for l in args.locales.split(",") if l.strip()]
    unknown = set(locales) - set(LOCALES.keys())
    if unknown:
        sys.exit(f"❌ Unknown locale(s): {sorted(unknown)}. "
                 f"Valid: {sorted(LOCALES.keys())}")

    should_check_assets = not args.skip_screenshots
    if args.check_assets or (args.apply and should_check_assets):
        assets_valid = check_local_assets(locales)
        if args.check_assets or not assets_valid:
            return 0 if assets_valid else 1

    key_id, issuer_id, key_path = load_credentials()
    token = make_jwt(key_id, issuer_id, key_path)
    client = Client(token, dry_run=not args.apply)

    mode = "APPLY ✏️" if args.apply else "DRY-RUN 🟡 (use --apply to write)"
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
        upload_screenshots(client, version_id, locales)
        print()


    # Final state probe so you can see exactly what's now on App Store.
    print("→ Final state on App Store Connect:")
    probe_locales(client, app_id, version_id)

    print()
    print("✅ Done." if args.apply else "✅ Dry-run complete. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
