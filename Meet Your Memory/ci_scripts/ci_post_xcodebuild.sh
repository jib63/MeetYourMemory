#!/bin/sh
# Publish localized App Store text after a successful Xcode Cloud Archive of main.
set -eu

if [ "${CI_BRANCH:-}" != main ] || [ "${CI_GIT_REF:-}" != refs/heads/main ] || \
   [ -n "${CI_PULL_REQUEST_NUMBER:-}" ]; then
    echo "→ Skipping App Store metadata: this is not a direct build of main"
    exit 0
fi

if [ "${CI_XCODEBUILD_ACTION:-}" != archive ]; then
    echo "→ Skipping App Store metadata: this is not an Archive action"
    exit 0
fi

if [ "${CI_XCODEBUILD_EXIT_CODE:-}" != 0 ]; then
    echo "→ Skipping App Store metadata: Archive did not complete successfully"
    exit 0
fi

REPO=${CI_PRIMARY_REPOSITORY_PATH:-$(cd "$(dirname "$0")/../.." && pwd)}
ARCHIVE=${CI_ARCHIVE_PATH:-}
if [ -z "$ARCHIVE" ]; then
    echo "❌ CI_ARCHIVE_PATH is missing" >&2
    exit 2
fi

INFO_PLIST=
for APP in "$ARCHIVE"/Products/Applications/*.app; do
    if [ -f "$APP/Info.plist" ]; then
        INFO_PLIST=$APP/Info.plist
        break
    fi
done
if [ -z "$INFO_PLIST" ]; then
    echo "❌ Cannot find the archived app's Info.plist" >&2
    exit 2
fi

VERSION=$(python3 -c 'import plistlib, sys; p = plistlib.load(open(sys.argv[1], "rb")); assert p.get("CFBundleIdentifier") == "com.jibstudios.Meet-Your-Memory", "Wrong archived app"; print(p["CFBundleShortVersionString"])' "$INFO_PLIST")
if [ -z "$VERSION" ]; then
    echo "❌ Cannot read the archived app version" >&2
    exit 2
fi

# Validate every locale before installing packages or calling Apple.
python3 "$REPO/Tools/upload_appstore.py" --check-metadata --version "$VERSION"

MISSING=
[ -n "${ASC_KEY_ID:-}" ] || MISSING="$MISSING ASC_KEY_ID"
[ -n "${ASC_ISSUER_ID:-}" ] || MISSING="$MISSING ASC_ISSUER_ID"
[ -n "${ASC_PRIVATE_KEY_BASE64:-}" ] || MISSING="$MISSING ASC_PRIVATE_KEY_BASE64"
if [ -n "$MISSING" ]; then
    echo "❌ Missing Xcode Cloud variables:$MISSING" >&2
    exit 2
fi

VENV=$(mktemp -d "${TMPDIR:-/tmp}/meet-your-memory-storefront.XXXXXX")
trap 'rm -rf "$VENV"' EXIT HUP INT TERM
python3 -m venv "$VENV"
PYTHON=$VENV/bin/python3
"$PYTHON" -m pip install --disable-pip-version-check \
    --requirement "$REPO/Meet Your Memory/ci_scripts/requirements-appstore.txt"

echo "→ Publishing App Store metadata and release notes for version $VERSION on main"
"$PYTHON" "$REPO/Tools/upload_appstore.py" \
    --version "$VERSION" --strict --apply --skip-screenshots
