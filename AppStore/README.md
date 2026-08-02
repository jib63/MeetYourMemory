# App Store assets

The UI test suite writes exactly six localized JPEG screenshots per run to:

```text
Screenshots/6.9-inch/<language>/
Screenshots/ipad-13-inch/<language>/
```

In Xcode, select **iPhone 17 Pro Max**, run `ScreenshotTests`, then repeat with
**iPad Pro 13-inch**. Each language has its own test method, so one locale can
be regenerated independently. The accepted pixel sizes are intentionally
restricted to Apple's required 6.9-inch iPhone and 13-inch iPad galleries.

Validate all local galleries without contacting Apple:

```bash
python3 Tools/upload_appstore.py --check-assets
```

The uploader is a dry run by default. After exporting `ASC_KEY_ID`,
`ASC_ISSUER_ID`, and `ASC_KEY_PATH` (or `ASC_PRIVATE_KEY_BASE64`), upload all
metadata and both screenshot families with:

```bash
python3 Tools/upload_appstore.py --apply
```

Use `--locales en-US,fr-FR` for a subset, `--skip-text` to upload only
screenshots, or `--skip-screenshots` to upload only metadata. App previews are
not generated or uploaded.
