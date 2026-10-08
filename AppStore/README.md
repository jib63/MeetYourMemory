# App Store media — API 4.5.1

Open `exports/delivery/index.html` to review the generated still images by
language. The delivery manifest records dimensions, sources and SHA-256
digests. The 192 generated screenshots have been uploaded to version **1.1.0**
using the API 4.5.1 Asset Library, across all eight languages and 32 galleries.
The 16 localized header/search assets are also uploaded and verified. No App
Previews or review submissions were performed. Server receipts are saved in
the delivery folder, separately for screenshots and creatives.

Eight locales: English, French, Italian, Spanish, Portuguese (Portugal),
Japanese, Simplified Chinese and Hindi.

| Gallery / creative | Per locale | Pixels |
| --- | ---: | --- |
| iPhone medium | 6 | 1206 × 2622 |
| iPhone large | 6 | 1320 × 2868 |
| iPad 13-inch | 6 | 2064 × 2752 |
| Duo outer | 4 | 1398 × 2034 |
| Duo inner | 2 | 2853 × 2007 |
| Product-page header | 1 | 3840 × 1646 |
| Search artwork | 1 | 3840 × 2560 |

Current bundle: **208 images** (192 screenshots, 16 creatives). The standalone
banner is `exports/banner/meet-your-memory-banner.png`. Header and banner use
the same artwork. Built-in ImageGen sources and exact prompts are preserved
in `media-artwork/`; localized typography uses native macOS font shaping.

The two native Duo inner screenshots show Panorama Pairs and Orbit Map in
landscape at 2853 × 2007. Each capture records the real SDK context as fully
unfolded (`flat`, `expanded`) and preserves native source hashes. The capture
fixture starts only after that context is reported, avoiding launch-time
recovery overlays.

To recapture, unfold simulator `96058282-9E19-4C38-9FFD-8B654E4D32D3` fully
flat in Device Hub, then run (`simctl` has no public fold/unfold command):

```bash
python3 Tools/capture_native_duo.py \
  --udid 96058282-9E19-4C38-9FFD-8B654E4D32D3 \
  --app '/private/tmp/memory-1.1.0-tests/Build/Products/Debug-iphonesimulator/Meet Your Memory.app' \
  --posture inner --scenes panoramaPairs,orbitMap
python3 Tools/prepare_appstore_media.py --include-duo
```

This produces a **208-image** bundle, with six Duo screenshots per language.
Duo outer and inner screenshots share
one ten-image limit and stay in the dedicated Duo group. Native captures
check real SDK posture, normalize orientation, reject black displays and
save provenance. Existing Debug marketing fixtures are used.

To regenerate ordinary screenshots, run `ScreenshotTests` on iPhone 17 Pro,
iPhone 17 Pro Max and iPad Pro 13-inch. Then export and validate:

```bash
python3 Tools/prepare_appstore_media.py --render --include-duo
python3 Tools/prepare_appstore_media.py --validate
python3 Tools/upload_appstore.py --check-assets
python3 Tools/test_appstore_media.py
```

Screenshot-only delivery and read-only verification:

```bash
python3 Tools/upload_appstore.py --apply --skip-text --screenshots-only
python3 Tools/upload_appstore.py --verify-assets --screenshots-only
python3 Tools/record_media_delivery.py
```

Reservations are persisted in `exports/.work/api/journal.json`. Re-running the
same selection reuses its saved identities. The uploader independently checks
processing, native dimensions, locales, display groups and gallery order.

The Apple OpenAPI download was verified as **4.5.1** on 2026-10-08. Its SHA-256
and inspected schemas are saved in `media/specs/api-4.5.1-contract.json`.
The uploader discovers actual spec/group IDs and limits through
`GET /v1/appAssetLibraryRefData`, reserves `appAssetLibraryImages`, transfers
the returned byte ranges without JWT headers, commits with `uploaded: true`,
waits for processing, creates placements and orders each placement type
separately. It honors Retry-After, refreshes JWTs and journals reservations.
It never falls back to legacy screenshot sets.

`python3 Tools/upload_appstore.py` defaults to a read-only live plan after
credentials are provided. `--apply` explicitly enables writes; `--skip-text`
limits delivery to prepared screenshots and creatives. `--skip-screenshots`
limits it to metadata. No review submission occurs. Live reference-data
discovery was performed for screenshot and creative delivery. Apple's actual
device crop previews remain unchecked; API placement and processing are verified. Local header
safe-area checks and crop samples are planning aids; verify Apple's actual
preview before a future submission.

Validation: all 24 localized screenshot test runs passed; Debug and Release
builds passed; prepared pixels, opacity and hashes checked. See
`exports/delivery/validation-report.json` for the saved checks.
