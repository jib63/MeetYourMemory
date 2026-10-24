# Xcode Cloud App Store metadata

Xcode Cloud discovers `ci_post_xcodebuild.sh` here because this directory is
beside `Meet Your Memory.xcodeproj`. The executable script uploads all eight
localized metadata sets, including `release_notes.txt`, after a successful
Archive built directly from `main`. Pull requests, tags, other branches and
other build actions are skipped. Screenshots and other media are not uploaded.

Configure an Xcode Cloud Archive workflow for branch `main`. Add `ASC_KEY_ID`,
`ASC_ISSUER_ID` and `ASC_PRIVATE_KEY_BASE64` in the workflow environment, and
mark the private key as **Secret**. The App Store Connect API key needs permission
to edit app metadata (for example, the App Manager role).

The key is the downloaded App Store Connect `.p8` private key. To encode it as
one line and copy the value for `ASC_PRIVATE_KEY_BASE64` on macOS:

```sh
base64 < /path/to/AuthKey_XXXXXXXXXX.p8 | tr -d '\n' | pbcopy
```

The script takes the version from the archived app and refuses to upload if
the matching editable App Store version or any matching local release note is
missing. It reports failed updates and checks the saved metadata through the
App Store Connect API. To validate the files locally without credentials:

```sh
python3 Tools/upload_appstore.py --check-metadata --version 1.1.1
```
