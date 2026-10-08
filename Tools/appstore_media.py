#!/usr/bin/env python3
"""Reusable App Store media formats, provenance, and library reconciliation.

No credentials or network writes belong in this module. Profiles describe file
compatibility; they deliberately do not guess unpublished placement API enums.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

from PIL import Image, ImageStat

FFMPEG = next((str(p) for p in (Path('/opt/homebrew/bin/ffmpeg'), Path('/usr/local/bin/ffmpeg'),
                               Path(shutil.which('ffmpeg') or '/nonexistent')) if p.is_file()), '')
FFPROBE = str(Path(FFMPEG).with_name('ffprobe')) if FFMPEG else (shutil.which('ffprobe') or '')


FORMAT_SOURCES = {
    "checkedOn": "2026-10-08",
    "creative": "https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications",
    "preview": "https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications",
    "screenshots": "https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications",
}


@dataclass(frozen=True)
class Profile:
    kind: str
    sizes: tuple[tuple[int, int], ...]
    min_seconds: float = 0
    max_seconds: float = 0
    fps: tuple[int, ...] = ()


PROFILES = {
    "header-image": Profile("image", ((3840, 1646),)),
    "search-image": Profile("image", ((1920, 1280), (3840, 2560))),
    "universal-image": Profile("image", ((5244, 2950),)),
    "header-video": Profile("video", ((3840, 1646),), 5, 30, (30, 60)),
    "search-video": Profile("video", ((1920, 1280), (3840, 2560)), 5, 30, (30, 60)),
    "duo-preview": Profile("video", ((1920, 886), (886, 1920)), 15, 30, (30,)),
    "duo-inner": Profile("image", ((2007, 2853), (2853, 2007))),
    "duo-outer": Profile("image", ((1398, 2034), (2034, 1398))),
    "iphone-medium": Profile("image", ((1206, 2622), (2622, 1206), (1179, 2556), (2556, 1179))),
    "iphone-large-screenshot": Profile("image", ((1320, 2868), (2868, 1320), (1290, 2796), (2796, 1290))),
    "ipad-screenshot": Profile("image", ((2064, 2752), (2752, 2064), (2048, 2732), (2732, 2048))),
    "iphone-large-preview": Profile("video", ((886, 1920), (1920, 886)), 15, 30, (30,)),
    "ipad-preview": Profile("video", ((1200, 1600), (1600, 1200)), 15, 30, (30,)),
}


def digest(path: Path) -> dict:
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(block)
            md5.update(block)
    return {"path": str(path.resolve()), "sha256": sha.hexdigest(),
            "md5": md5.hexdigest(), "bytes": path.stat().st_size}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".json", delete=False) as file:
        pending = Path(file.name)
        try:
            json.dump(value, file, indent=2, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            pending.unlink(missing_ok=True)
            raise
    os.replace(pending, path)


def validate(path: Path, profile_name: str, ffprobe: str = "ffprobe") -> dict:
    """Check destination-specific rules; creative video permits 60 fps/5 s."""
    profile = PROFILES[profile_name]
    if not path.is_file():
        raise ValueError(f"Missing media: {path}")
    if profile.kind == "image":
        with Image.open(path) as image:
            image.load()
            size = image.size
            if image.mode != "RGB" or "transparency" in image.info:
                raise ValueError(f"Opaque RGB required: {path}")
            if max(ImageStat.Stat(image.resize((64, 64))).mean) < 5:
                raise ValueError(f"Black/inactive capture: {path}")
            if profile_name in {"header-image", "universal-image"} and image.format != "PNG":
                raise ValueError(f"PNG required: {path}")
            if image.format not in {"PNG", "JPEG"}:
                raise ValueError(f"PNG/JPEG required: {path}")
        details = {"width": size[0], "height": size[1], "kind": "image"}
    else:
        if path.suffix.lower() not in {'.mp4', '.mov', '.m4v'}:
            raise ValueError(f"Unsupported video container extension: {path}")
        result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format",
                                 "-of", "json", str(path)], check=True, capture_output=True, text=True)
        info = json.loads(result.stdout)
        streams = info.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        size = video.get("width"), video.get("height")
        rate = Fraction(video.get("r_frame_rate", "0/1"))
        average = Fraction(video.get("avg_frame_rate", "0/1"))
        duration = float(info.get("format", {}).get("duration", 0))
        # These codec/pixel choices are this pipeline's export convention, not
        # an undocumented claim that creative assets have preview codec limits.
        if (rate not in profile.fps or average != rate or
                not profile.min_seconds <= duration <= profile.max_seconds or
                video.get("sample_aspect_ratio") != "1:1" or
                video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p" or
                video.get("field_order") != "progressive"):
            raise ValueError(f"Invalid {profile_name} timing/video streams: {path}")
        if profile_name in {"duo-preview", "iphone-large-preview", "ipad-preview"}:
            if (path.stat().st_size > 500_000_000 or video.get("profile") != "High" or
                    int(video.get("level", 99)) > 40 or audio.get("codec_name") != "aac" or
                    audio.get("profile") != "LC" or audio.get("channels") != 2 or audio.get("sample_rate") not in {"44100", "48000"}):
                raise ValueError(f"Invalid App Preview codec/audio/size: {path}")
        details = {"kind": "video", "width": size[0], "height": size[1],
                   "fps": int(rate), "duration": duration, "audio": audio.get("codec_name")}
    # Search accepts any exact 3:2 resolution inside the documented range.
    search = profile_name in {"search-image", "search-video"}
    valid_search = (isinstance(size[0], int) and isinstance(size[1], int) and
                    1920 <= size[0] <= 3840 and 1280 <= size[1] <= 2560 and size[0] * 2 == size[1] * 3)
    if size not in profile.sizes and not (search and valid_search):
        raise ValueError(f"Unsupported {profile_name} pixels: {size}: {path}")
    return details


def identity(app: str, sha256: str, language: str, profile: str) -> str:
    return hashlib.sha256(json.dumps([app, sha256, language, profile]).encode()).hexdigest()


def reconcile(asset: dict, ledger: dict) -> dict:
    """Reuse/resume only an exact identity; filenames never establish identity."""
    ordered = sorted(ledger.get("assets", []), key=lambda r: (r.get("deliveryState") == "COMPLETE" and r.get("reviewState") == "APPROVED"), reverse=True)
    for remote in ordered:
        if any(remote.get(key) != asset.get(key) for key in ("app", "sha256", "language")):
            continue
        if asset["profile"] not in remote.get("compatibleProfiles", []):
            continue
        if asset["kind"] == "video" and remote.get("posterSeconds") != asset.get("posterSeconds"):
            continue
        identifier = remote.get("assetId") or remote.get("reservationId")
        if not identifier or remote.get("archived") or remote.get("deliveryState") == "FAILED":
            continue
        if remote.get("deliveryState") not in {"COMPLETE", "PROCESSING", "AWAITING_UPLOAD"}:
            action = "inspect-delivery-status"
        elif remote.get("deliveryState") != "COMPLETE":
            action = "resume-known-upload" if remote.get("deliveryState") == "AWAITING_UPLOAD" else "wait-for-processing"
        elif remote.get("reviewState") == "APPROVED":
            action = "reuse-approved-asset"
        elif remote.get("reviewState") == "REJECTED":
            action = "resolve-review-rejection"
        else:
            action = "review-required"
        return {"action": action, "remoteId": identifier,
                "deliveryState": remote.get("deliveryState"), "reviewState": remote.get("reviewState")}
    return {"action": "reconcile-library-before-upload", "remoteId": None}


def load_config(path: Path) -> tuple[dict, Path]:
    config = json.loads(path.read_text())
    if config.get("schemaVersion") != 1 or not config.get("app") or not config.get("locales"):
        raise ValueError("Media config requires schemaVersion 1, app, and locales")
    for locale, entry in config["locales"].items():
        if not entry.get("language"):
            raise ValueError(f"Missing language for {locale}")
    root = (path.parent / config.get("projectRoot", "../..")).resolve()
    return config, root
