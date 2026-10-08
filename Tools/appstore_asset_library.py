#!/usr/bin/env python3
"""Asset Library API 4.5.1 transport, shared by the App Store uploader.

The catalog supplies group IDs, specifications and limits at runtime. Uploads,
placements, cleanup and review are separate operations; this module never
submits anything for review. A journal makes interrupted runs resumable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import fcntl
import hashlib
import io
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageStat

from appstore_media import FFPROBE, atomic_json, digest, identity, validate

PLACEMENTS = {
    'header': ('PRODUCT_PAGE_HEADER_ASSET', 'DEFAULT', 'IPHONE_APP_STORE'),
    'search': ('APP_STORE_SEARCH_RESULTS_ASSET', 'DEFAULT', 'IPHONE_APP_STORE'),
    'duo': ('APP_SCREENSHOT', 'IPHONE_DUO', 'IPHONE_APP_STORE'),
    'iphone-medium': ('APP_SCREENSHOT', 'IPHONE_DYNAMIC_ISLAND_MEDIUM_DISPLAY', 'IPHONE_APP_STORE'),
    'iphone-large': ('APP_SCREENSHOT', 'IPHONE_DYNAMIC_ISLAND_LARGE_DISPLAY', 'IPHONE_APP_STORE'),
    'ipad': ('APP_SCREENSHOT', 'IPAD_13_DISPLAY', 'IPAD_APP_STORE'),
}
READY = {'COMPLETE', 'PREPARE_FOR_SUBMISSION', 'READY_FOR_REVIEW',
         'WAITING_FOR_REVIEW', 'IN_REVIEW', 'ACCEPTED', 'APPROVED'}
DELETABLE = {'AWAITING_UPLOAD', 'UPLOAD_COMPLETE', 'FAILED', 'COMPLETE',
             'PREPARE_FOR_SUBMISSION', 'REJECTED'}
INACTIVE = {'INACTIVE'}  # Observed on migrated historical placements.


def validate_duo_route(asset: dict) -> None:
    """Native Duo stills and previews stay in their dedicated display group."""
    is_duo = (asset.get('profile', '').startswith('duo-')
              or asset.get('sourcePlacement') == 'duo'
              or 'iphone-duo' in Path(asset.get('path', '')).parts
              or Path(asset.get('path', '')).stem == 'preview-duo'
              or asset.get('id', '').startswith('duo-'))
    if is_duo and asset['placement'] != 'duo':
        raise ValueError('Duo media must use the dedicated Duo placement')


def offline_mapping(asset: dict) -> dict:
    """Published type/display enums; actual group and spec IDs still require GET ref data."""
    kind = asset.get('kind', 'video' if 'video' in asset.get('profile', '') or asset.get('profile') == 'duo-preview' else 'image')
    validate_duo_route({**asset, 'kind': kind})
    wells = ['header', 'search'] if asset['placement'] == 'universal' else [asset['placement']]
    targets = []
    for well in wells:
        placement_type, display, platform = PLACEMENTS[well]
        if placement_type == 'APP_SCREENSHOT' and kind == 'video':
            placement_type = 'APP_PREVIEW'
        targets.append({'placementType': placement_type, 'displayClass': display, 'platform': platform})
    return {'apiVersion': '4.5.1', 'resource': 'appAssetLibraryVideos' if kind == 'video' else 'appAssetLibraryImages',
            'targets': targets, 'placementGroupDiscovery': 'GET /v1/appAssetLibraryRefData'}


def collection(client, path: str, **params) -> tuple[list[dict], list[dict]]:
    """Follow every page, including pagination on relationships."""
    data, included, seen = [], {}, set()
    while path:
        if path in seen:
            raise RuntimeError('API pagination contains a cycle')
        seen.add(path)
        response = client.get(path, **params)
        data.extend(response.get('data', []))
        for item in response.get('included', []):
            included[(item['type'], item['id'])] = item
        path, params = response.get('links', {}).get('next'), {}
    return data, list(included.values())


def seconds(value: str) -> float:
    match = re.fullmatch(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?', value)
    if not match:
        raise ValueError(f'Unsupported catalog duration: {value}')
    h, m, s = (float(n or 0) for n in match.groups())
    return h * 3600 + m * 60 + s


class Catalog:
    def __init__(self, response: dict):
        self.values = {key: [] for key in ['features', 'placementProfileGroups',
                      'imageSpecs', 'videoSpecs', 'placementTypes', 'displayClasses']}
        for record in response['data']:
            for key in self.values:
                self.values[key].extend(record['attributes'].get(key, []))

    def target(self, placement: str, kind: str) -> tuple[str, str, str]:
        placement_type, display, platform = PLACEMENTS[placement]
        if placement_type == 'APP_SCREENSHOT' and kind == 'video':
            placement_type = 'APP_PREVIEW'
        groups = [g['placementProfileGroupId'] for g in self.values['placementProfileGroups']
                  if g['displayClassId'] == display and g['platform'] == platform]
        # Creative groups may use Apple's GENERAL/default platform.
        if display == 'DEFAULT' and not groups:
            allowed = {m['placementGroupId'] for p in self.values['placementTypes']
                       if p['placementTypeId'] == placement_type for m in p['specMappings']}
            groups = [g['placementProfileGroupId'] for g in self.values['placementProfileGroups']
                      if g['displayClassId'] == 'DEFAULT' and g['placementProfileGroupId'] in allowed]
        if len(groups) != 1:
            raise ValueError(f'Ambiguous/unavailable device group: {placement}/{kind}: {groups}')
        category = 'CREATIVE_ASSETS' if placement in {'header', 'search'} else 'APP_SCREENSHOTS_AND_PREVIEWS'
        return placement_type, groups[0], category

    def compatible_specs(self, asset: dict, placement_type: str, group: str) -> list[str]:
        placement = next(p for p in self.values['placementTypes'] if p['placementTypeId'] == placement_type)
        allowed = {s for m in placement['specMappings'] if m['placementGroupId'] == group for s in m['specs']}
        matches = []
        for spec in self.values['videoSpecs' if asset['kind'] == 'video' else 'imageSpecs']:
            if spec['specId'] not in allowed:
                continue
            d = spec['dimensions']; w, h = asset['width'], asset['height']
            if not (d['minWidth'] <= w <= d['maxWidth'] and d['minHeight'] <= h <= d['maxHeight']):
                continue
            if d['minWidth'] != d['maxWidth'] or d['minHeight'] != d['maxHeight']:
                numerator, denominator = (int(x) for x in spec['aspectRatio'].split(':'))
                if abs(w / h - numerator / denominator) > 0.001:
                    continue
            if Path(asset['path']).suffix.lower() not in spec['fileExtensions'] or asset['bytes'] > spec['maxFileSize']:
                continue
            if asset['kind'] == 'video':
                if not any(f['minFps'] <= asset['fps'] <= f['maxFps'] for f in spec['frameRates']):
                    continue
                if not seconds(spec['duration']['min']) <= asset['duration'] <= seconds(spec['duration']['max']):
                    continue
                if spec.get('audioRequired') and not asset.get('audio'):
                    continue
            matches.append(spec['specId'])
        if not matches:
            raise ValueError(f"{asset['fileName']}: no catalog specification for {placement_type}/{group}")
        return matches

    def limit(self, placement_type: str, group: str) -> int:
        limits = [limit['maxCount'] for feature in self.values['features']
                  if feature['featureId'] == 'APP_STORE_VERSIONS'
                  for policy in feature['placementPolicies'] if policy['placementType'] == placement_type
                  for limit in policy['groupLimits'] if group in limit['groupIds']]
        if len(limits) != 1:
            raise ValueError(f'Missing/ambiguous placement limit: {placement_type}/{group}')
        return limits[0]

    def plan(self, assets: list[dict]) -> list[dict]:
        result = []
        for asset in assets:
            validate_duo_route(asset)
            kind, group, category = self.target(asset['placement'], asset['kind'])
            result.append({**asset, 'resource': 'appAssetLibraryVideos' if asset['kind'] == 'video' else 'appAssetLibraryImages',
                           'placementType': kind, 'placementGroup': group, 'category': category,
                           'expectedSpecIds': self.compatible_specs(asset, kind, group)})
        for (locale, kind, group), count in Counter((a['locale'], a['placementType'], a['placementGroup']) for a in result).items():
            if count > self.limit(kind, group):
                raise ValueError(f'{locale}/{kind}/{group}: {count} exceeds catalog limit')
        return result


def validate_file(asset: dict) -> dict:
    path = Path(asset['path'])
    actual = digest(path)
    if any(actual[k] != asset[k] for k in ['sha256', 'bytes']):
        raise ValueError(f'Changed delivery artifact: {path}')
    if asset.get('profile'):
        details = validate(path, asset['profile'], FFPROBE)
    elif path.suffix.lower() in {'.jpg', '.jpeg', '.png'}:
        with Image.open(path) as image:
            image.load()
            if image.mode != 'RGB' or 'transparency' in image.info or max(ImageStat.Stat(image.resize((64, 64))).mean) < 5:
                raise ValueError(f'Invalid opaque app screenshot: {path}')
            details = {'width': image.width, 'height': image.height, 'kind': 'image'}
    else:
        from validate_iphone_media import verify_video
        verify_video(path, (asset['width'], asset['height']))
        details = {k: asset[k] for k in ['width', 'height', 'kind', 'fps', 'duration', 'audio']}
    for source in asset.get('sources', []):
        if digest(Path(source['path']))['sha256'] != source['sha256']:
            raise ValueError(f"Changed source: {source['path']}")
    return {**asset, **details}


def selection(config: dict, root: Path, locales: list[str], *, devices='all',
              placements: set[str] | None = None, images=True, previews=True) -> list[dict]:
    """Select one creative per well and all prescribed device media; fully preflight."""
    manifest = json.loads((root / 'delivery/delivery-manifest.json').read_text())
    if manifest['app'] != config['app']:
        raise ValueError('Delivery bundle belongs to another app')
    candidates = [a for a in manifest['assets'] if a['locale'] in locales
                  and (images if a['kind'] == 'image' else previews)]
    preferred = config.get('uploadSelection', {'header': ['header-opening', 'header-still'], 'search': ['search-still']})
    chosen = []
    for locale in locales:
        for well in ['header', 'search']:
            if devices == 'ipad' or (placements and well not in placements):
                continue
            choices = [a for a in candidates if a['locale'] == locale and a['placement'] == well]
            match = next((a for identifier in preferred[well] for a in choices if a['id'] == identifier), None)
            if match is None and not choices:
                continue
            if match is None:
                raise ValueError(f'{locale}: missing selected {well} creative')
            chosen.append(match)
    chosen.extend(a for a in candidates if a['placement'] in {'duo', 'iphone-medium', 'iphone-large', 'ipad'}
                  and (devices != 'ipad' or a['placement'] == 'ipad')
                  and (devices != 'iphone' or a['placement'] != 'ipad')
                  and (not placements or a['placement'] in placements))
    # Preserve the existing large iPhone/iPad galleries with the new transport.
    # Filenames now carry app, device and locale even for these older source folders.
    for locale in locales:
        language = config['locales'][locale]['language']
        for well, gallery in config.get('ordinaryMedia', {}).items():
            if well not in {'iphone-large', 'ipad'}:
                raise ValueError(f'Unsupported ordinary gallery: {well}')
            if (devices == 'iphone' and well == 'ipad') or (devices == 'ipad' and well != 'ipad') or (placements and well not in placements):
                continue
            folder = gallery['folder']
            files = (gallery.get('screenshots', []) if images else []) + (gallery.get('previews', []) if previews else [])
            for name in files:
                path = root / folder / language / name
                details = digest(path)
                if path.suffix.lower() == '.mp4':
                    import subprocess
                    from fractions import Fraction
                    info = json.loads(subprocess.check_output([FFPROBE, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
                    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
                    audio = next((s for s in info['streams'] if s['codec_type'] == 'audio'), {})
                    media = {'kind': 'video', 'width': video['width'], 'height': video['height'],
                             'duration': float(info['format']['duration']), 'fps': float(Fraction(video['r_frame_rate'])), 'audio': audio.get('codec_name')}
                else:
                    with Image.open(path) as image:
                        media = {'kind': 'image', 'width': image.width, 'height': image.height}
                profile = f'{well}-preview' if media['kind'] == 'video' else f'{well}-screenshot'
                chosen.append({**details, **media, 'id': f'{well}-{path.stem}', 'app': config['app'], 'locale': locale,
                               'language': language, 'placement': well,
                               'profile': profile, 'assetKey': identity(config['app'], details['sha256'], language, profile),
                               **({'posterSeconds': gallery.get('posterSeconds', 5)} if media['kind'] == 'video' else {}),
                               'fileName': f'{config["app"]}-{well}-{path.stem}-{locale}{path.suffix.lower()}'})
    chosen = [a for a in chosen if (images if a['kind'] == 'image' else previews)]
    names = [a['fileName'] for a in chosen]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate upload filename in selection')
    for asset in chosen:
        if not asset['fileName'].endswith(f'-{asset["locale"]}{Path(asset["path"]).suffix.lower()}'):
            raise ValueError('Every upload filename must end with its locale')
    # A portrait preview can serve both ordinary display groups with one upload.
    if devices != 'ipad' and (not placements or 'iphone-medium' in placements) and previews:
        for asset in chosen.copy():
            if asset['placement'] == 'iphone-large' and asset['kind'] == 'video':
                chosen.append({**asset, 'placement': 'iphone-medium'})
    # Ordinary iPhone reuse never crosses the dedicated Duo boundary.
    if devices != 'ipad' and previews:
        for reuse in config.get('previewReuse', []):
            for target in reuse['placements']:
                if target not in {'duo', 'iphone-medium', 'iphone-large'}:
                    raise ValueError(f'Unsupported preview reuse target: {target}')
                if placements and target not in placements:
                    continue
                for asset in candidates:
                    if asset['id'] == reuse['assetId'] and asset['kind'] == 'video':
                        if (asset['placement'] == 'duo') != (target == 'duo'):
                            raise ValueError('Duo app previews cannot be reused in ordinary iPhone groups, or vice versa')
                        if not any(a['locale'] == asset['locale'] and a['id'] == asset['id']
                                   and a['placement'] == target for a in chosen):
                            clone = {**asset, 'placement': target, 'sourcePlacement': asset['placement']}
                            if reuse.get('order', 'last') == 'first':
                                index = next((i for i, a in enumerate(chosen) if a['locale'] == asset['locale']
                                              and a['placement'] == target and a['kind'] == 'video'), len(chosen))
                                chosen.insert(index, clone)
                            elif reuse.get('order', 'last') == 'last':
                                chosen.append(clone)
                            else:
                                raise ValueError('Preview reuse order must be first or last')
    if not chosen:
        raise ValueError('No assets selected')
    for asset in chosen:
        validate_duo_route(asset)
        if not asset['fileName'].endswith(f'-{asset["locale"]}{Path(asset["path"]).suffix.lower()}'):
            raise ValueError('Every upload filename must end with its locale')
    return [validate_file(a) for a in chosen]


class Journal:
    def __init__(self, path: Path, app_id: str):
        self.path, self.lock = path, threading.RLock()
        self.value = json.loads(path.read_text()) if path.exists() else {'schemaVersion': 1, 'appId': app_id, 'assets': {}, 'cleanup': {}}
        if self.value['appId'] != app_id:
            raise ValueError('Journal belongs to another app')

    def save(self):
        with self.lock:
            atomic_json(self.path, self.value)

    def record(self, key: str, **values):
        with self.lock:
            self.value['assets'].setdefault(key, {}).update(values)
            self.save()


@contextmanager
def run_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def asset_key(asset: dict) -> str:
    return f"{asset['category']}:{asset['sha256']}:{asset['locale']}"


def selection_digest(plan: list[dict]) -> str:
    return hashlib.sha256(json.dumps([(a['locale'], a['sha256'], a['placementType'], a['placementGroup'])
                                      for a in plan], separators=(',', ':')).encode()).hexdigest()


def delivery_receipt(plan: list[dict], remotes: dict, path: Path, app_id: str, version_id: str):
    """Export each verified delivery identity once, including ordinary galleries."""
    records, seen = [], set()
    for asset in plan:
        if not asset.get('assetKey'):
            continue
        delivery_key = asset['assetKey'], asset['locale']
        if delivery_key in seen:
            continue
        seen.add(delivery_key)
        remote = remotes[asset_key(asset)]
        records.append({'id': asset['id'], 'assetKey': asset['assetKey'], 'locale': asset['locale'],
            'profile': asset['profile'], 'sha256': asset['sha256'], 'remoteAssetId': remote['id'],
            'remoteName': remote['attributes']['fileName'],
            'posterSecondsVerified': asset.get('posterSeconds') if asset['kind'] == 'video' else None})
    atomic_json(path, {'schemaVersion': 1, 'app': plan[0]['app'], 'appId': app_id, 'versionId': version_id,
                       'transportUsed': 'App Store Connect API 4.5.1', 'reviewSubmitted': False,
                       'assets': records})


def reference_name(asset: dict) -> str:
    return f"{asset['fileName']} · {asset['sha256'][:12]}"


def wait_ready(client, resource: str, identifier: str, expected: dict, *, timeout=600) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        asset = client.get(f'/{resource}/{identifier}')['data']
        a = asset['attributes']; state = a.get('state')
        if state in {'FAILED', 'REJECTED', 'ARCHIVED'}:
            raise RuntimeError(f'{identifier}: {state}: {a.get("stateDetails")}')
        if state in READY and a.get('specId'):
            if a.get('fileName') != expected['fileName'] or a.get('fileSize') != expected['bytes'] or a.get('category') != expected['category']:
                raise RuntimeError(f'{identifier}: server asset identity differs from the selected file')
            if a['specId'] not in expected['expectedSpecIds']:
                raise RuntimeError(f"{expected['fileName']}: server matched unexpected spec {a['specId']}")
            media = a.get('imageAsset') if expected['kind'] == 'image' else a.get('videoAsset')
            if media:
                if expected['kind'] == 'image' and (media.get('width'), media.get('height')) != (expected['width'], expected['height']):
                    raise RuntimeError(f'{identifier}: processed image dimensions differ from the selected file')
                return asset
        if time.monotonic() >= deadline:
            raise TimeoutError(f'{identifier}: processing still {state}; reservation retained for resume')
        time.sleep(3)


def transfer(client, asset: dict, operations: list[dict]):
    """Use a separate unauthenticated request for each returned byte range."""
    import requests
    intervals = sorted((int(op['offset']), int(op['length'])) for op in operations)
    cursor = 0
    for offset, length in intervals:
        if offset != cursor or length <= 0:
            raise ValueError('Upload operations do not cover the file exactly')
        cursor += length
    if cursor != asset['bytes']:
        raise ValueError('Upload operations do not match file size')
    with Path(asset['path']).open('rb') as file:
        for op in operations:
            if urlsplit(op['url']).scheme != 'https' or op['method'] != 'PUT':
                raise ValueError('Unexpected upload operation')
            file.seek(op['offset']); data = file.read(op['length'])
            headers = {h['name']: h['value'] for h in op.get('requestHeaders', [])}
            if any(k.lower() == 'authorization' for k in headers):
                raise ValueError('Upload operation unexpectedly contains Authorization')
            for attempt in range(4):
                try:
                    response = requests.request('PUT', op['url'], headers=headers, data=data, timeout=300, allow_redirects=False)
                    if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                        client.wait_for_retry(response, attempt); continue
                    if not response.ok:
                        raise RuntimeError(f"Asset part upload failed: HTTP {response.status_code}; reservation retained")
                    break
                except (requests.ConnectionError, requests.Timeout):
                    if attempt == 3:
                        raise RuntimeError('Upload interrupted; reservation retained for resume') from None
                    time.sleep(2 ** attempt)


def upload_asset(client, library_id: str, asset: dict, journal: Journal, *, defer_processing=False) -> dict:
    key, resource = asset_key(asset), asset['resource']
    record = journal.value['assets'].get(key, {})
    remote = None
    if record.get('assetId'):
        try:
            remote = client.get(f'/{resource}/{record["assetId"]}')['data']
        except Exception as error:
            if getattr(getattr(error, 'response', None), 'status_code', None) != 404:
                raise
    if remote is None:
        # Reconcile an uncertain POST outcome before reserving another upload.
        matches, _ = collection(client, f'/appAssetLibraries/{library_id}/{"videos" if asset["kind"] == "video" else "images"}',
                                **{'filter[referenceName]': reference_name(asset), 'limit': 200})
        matches = [a for a in matches if a['attributes'].get('referenceName') == reference_name(asset)
                   and a['attributes'].get('fileSize') == asset['bytes'] and a['attributes'].get('state') != 'ARCHIVED']
        if len(matches) > 1:
            raise RuntimeError(f"{asset['fileName']}: multiple reservations require reconciliation")
        remote = matches[0] if matches else None
    if remote is None:
        journal.record(key, fileName=asset['fileName'], sha256=asset['sha256'], locale=asset['locale'], resource=resource,
                       referenceName=reference_name(asset), status='RESERVING')
        attributes = {'fileName': asset['fileName'], 'fileSize': asset['bytes'], 'category': asset['category'],
                      'referenceName': reference_name(asset)}
        if asset['kind'] == 'video' and asset.get('posterSeconds') is not None:
            attributes['previewFrameTimeCode'] = f"00:00:{int(asset['posterSeconds']):02d}:00"
        remote = client.post(f'/{resource}', {'data': {'type': resource, 'attributes': attributes,
                    'relationships': {'assetLibrary': {'data': {'type': 'appAssetLibraries', 'id': library_id}}}}})['data']
    identifier, a = remote['id'], remote['attributes']
    if a.get('fileSize') != asset['bytes'] or a.get('category') != asset['category']:
        raise RuntimeError('Reservation identity differs from local content')
    journal.record(key, assetId=identifier, status=a.get('state'))
    if a.get('state') == 'AWAITING_UPLOAD':
        transfer(client, asset, a.get('uploadOperations', []))
        client.patch(f'/{resource}/{identifier}', {'data': {'type': resource, 'id': identifier, 'attributes': {'uploaded': True}}})
        journal.record(key, status='UPLOAD_COMPLETE')
    if defer_processing:
        action = 'transferred; processing pending' if a.get('state') == 'AWAITING_UPLOAD' else f"reused reservation ({a.get('state')})"
        print(f"  ↑ {asset['locale']}: {asset['fileName']} {action}", flush=True)
        return remote
    return finalize_asset(client, remote, asset, journal)


def poster_matches(timecode: str | None, expected: dict) -> bool:
    """Apple may round a requested poster to the adjacent encoded frame."""
    if expected.get('posterSeconds') is None:
        return True
    try:
        hours, minutes, seconds, frame = map(int, timecode.split(':'))
        fps = float(expected.get('fps', 30))
        if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60 or not 0 <= frame < fps or fps <= 0:
            return False
        actual = hours * 3600 + minutes * 60 + seconds + frame / fps
        return abs(actual - float(expected['posterSeconds'])) <= 1 / fps + 1e-6
    except (AttributeError, TypeError, ValueError):
        return False


def finalize_asset(client, remote: dict, asset: dict, journal: Journal, *, timeout=600) -> dict:
    key, resource, identifier = asset_key(asset), asset['resource'], remote['id']
    remote = wait_ready(client, resource, identifier, asset, timeout=timeout)
    if asset['kind'] == 'video' and asset.get('posterSeconds') is not None:
        requested = f"00:00:{int(asset['posterSeconds']):02d}:00"
        if not poster_matches(remote['attributes'].get('previewFrameTimeCode'), asset):
            client.patch(f'/{resource}/{identifier}', {'data': {'type': resource, 'id': identifier,
                         'attributes': {'previewFrameTimeCode': requested}}})
            remote = wait_ready(client, resource, identifier, asset, timeout=timeout)
    journal.record(key, status=remote['attributes']['state'], specId=remote['attributes']['specId'])
    print(f"  ✓ {asset['locale']}: {asset['fileName']} → {identifier}", flush=True)
    return remote


def verify_poster(client, remote: dict, expected: dict, *, timeout=180) -> dict:
    """Wait for the requested frame, then verify its processed image is readable."""
    import requests
    deadline = time.monotonic() + timeout
    while True:
        a = remote['attributes']; frame = a.get('previewFrameImage') or {}
        image = frame.get('image') or {}
        if (frame.get('state', {}).get('state') == 'COMPLETE' and image.get('width', 0) > 0
                and image.get('height', 0) > 0 and image.get('templateUrl')
                and poster_matches(a.get('previewFrameTimeCode'), expected)):
            url = image['templateUrl'].replace('{w}', '320').replace('{h}', '320').replace('{f}', 'jpg')
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.mzstatic.com'):
                raise ValueError('Unexpected processed poster host')
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            with Image.open(io.BytesIO(response.content)) as rendered:
                rendered.load()
                if rendered.width <= 0 or rendered.height <= 0:
                    raise RuntimeError('Empty processed preview frame')
            return {'timeCode': a.get('previewFrameTimeCode'), 'width': image['width'], 'height': image['height'], 'httpStatus': response.status_code}
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{remote['id']}: preview frame is not ready")
        time.sleep(3)
        remote = client.get(f"/appAssetLibraryVideos/{remote['id']}")['data']


def localization_placements(client, identifier: str, *, group: str | None = None, placement_type: str | None = None) -> list[dict]:
    params = {'limit': 200, 'include': 'image,video', 'sort': 'placementGroupPosition'}
    if group:
        params['filter[placementGroup]'] = group
    if placement_type:
        params['filter[placementType]'] = placement_type
    records, _ = collection(client, f'/appStoreVersionLocalizations/{identifier}/placements', **params)
    return [p for p in records if p['attributes'].get('state') not in INACTIVE]


def linked_asset(placement: dict) -> str | None:
    for key in ['image', 'video']:
        item = placement.get('relationships', {}).get(key, {}).get('data')
        if item:
            return item['id']
    return None


def place_group(client, localization: str, group: str, assets: list[dict], remotes: dict) -> list[str]:
    current = localization_placements(client, localization, group=group)
    desired = [(a['placementType'], remotes[asset_key(a)]['id']) for a in assets]
    # Delete stale/duplicate placements only in the requested group/localization.
    keep, remaining = {}, set(desired)
    selected_types = {kind for kind, identifier in desired}
    for p in current:
        key = p['attributes']['placementType'], linked_asset(p)
        if key in remaining:
            keep[key] = p['id']; remaining.remove(key)
        elif p['attributes']['placementType'] in selected_types:
            client.delete(f'/appAssetLibraryPlacements/{p["id"]}')
    for asset in assets:
        remote = remotes[asset_key(asset)]; key = asset['placementType'], remote['id']
        if key in keep:
            continue
        relationship = 'video' if asset['kind'] == 'video' else 'image'
        result = client.post('/appAssetLibraryPlacements', {'data': {'type': 'appAssetLibraryPlacements',
            'attributes': {'placementType': asset['placementType'], 'placementGroup': group},
            'relationships': {relationship: {'data': {'type': asset['resource'], 'id': remote['id']}},
                              'appStoreVersionLocalization': {'data': {'type': 'appStoreVersionLocalizations', 'id': localization}}}}})
        keep[key] = result['data']['id']
    ordered = [keep[key] for key in desired]
    # The live API rejects a request mixing placement types, even in one group.
    for kind in dict.fromkeys(kind for kind, identifier in desired):
        type_order = [keep[key] for key in desired if key[0] == kind]
        def read_type():
            return [p for p in localization_placements(client, localization, group=group, placement_type=kind)
                    if p['attributes']['placementType'] == kind]
        latest = read_type()
        if [p['id'] for p in latest] != type_order:
            client.post('/appAssetLibraryPlacementOrderingRequests', {'data': {
                'type': 'appAssetLibraryPlacementOrderingRequests', 'attributes': {'placementGroup': group},
                'relationships': {'orderedPlacements': {'data': [{'type': 'appAssetLibraryPlacements', 'id': i} for i in type_order]},
                                  'appStoreVersionLocalization': {'data': {'type': 'appStoreVersionLocalizations', 'id': localization}}}}})
        for attempt in range(10):
            latest = read_type()
            if [p['id'] for p in latest] == type_order and all(p['attributes'].get('state') not in {'FAILED', 'ASSET_PROCESSING'} for p in latest):
                break
            time.sleep(3)
        else:
            raise RuntimeError(f'{localization}/{group}/{kind}: placement order/processing not verified')
    return ordered


def inventory(client, app_id: str) -> dict:
    library = client.get(f'/apps/{app_id}/assetLibrary')['data']
    result = {'appId': app_id, 'libraryId': library['id'], 'assets': []}
    for kind in ['images', 'videos']:
        records, _ = collection(client, f'/appAssetLibraries/{library["id"]}/{kind}', limit=200)
        for record in records:
            record.get('attributes', {}).pop('uploadOperations', None)
        result['assets'].extend(records)
    return result


def cleanup(client, snapshot: dict, localizations: dict, journal: Journal, *, workers=4) -> dict:
    """Clear editable-version placements; delete drafts and archive approved media.

    Existing archived/history assets and released-version placements are retained.
    The original ID list is persisted, so resuming cleanup cannot remove new uploads.
    """
    log = journal.value['cleanup']
    if not log:
        log.update({'sourceAssetIds': [a['id'] for a in snapshot['assets']], 'actions': {}, 'placements': {}})
        journal.save()
    source_ids = set(log['sourceAssetIds'])
    for locale, localization in localizations.items():
        for placement in localization_placements(client, localization):
            if linked_asset(placement) not in source_ids:
                continue
            client.delete(f'/appAssetLibraryPlacements/{placement["id"]}')
            log['placements'][placement['id']] = {'locale': locale, 'action': 'deleted'}
            journal.save()
    def retire(asset):
        identifier, state = asset['id'], asset['attributes']['state']
        if identifier not in source_ids or identifier in log['actions']:
            return
        resource = asset['type']
        if state == 'ARCHIVED':
            result = {'action': 'already-archived'}
        elif state == 'APPROVED':
            client.patch(f'/{resource}/{identifier}', {'data': {'type': resource, 'id': identifier, 'attributes': {'archived': True}}})
            verified = client.get(f'/{resource}/{identifier}')['data']['attributes']['state']
            if verified != 'ARCHIVED':
                raise RuntimeError(f'{identifier}: archive not verified ({verified})')
            result = {'action': 'archived'}
        elif state in DELETABLE:
            try:
                client.delete(f'/{resource}/{identifier}')
            except Exception as error:
                response = getattr(error, 'response', None)
                if response is None or response.status_code != 409:
                    raise
                result = {'action': 'retained-locked', 'reason': response.json().get('errors', [])}
            else:
                result = {'action': 'deleted'}
        else:
            result = {'action': 'retained-locked', 'reason': f'Asset state: {state}'}
        with journal.lock:
            log['actions'][identifier] = result
            journal.save()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(retire, a) for a in snapshot['assets']]
        for count, future in enumerate(as_completed(futures), 1):
            future.result()
            if count % 100 == 0:
                print(f'  cleanup {count}/{len(futures)}', flush=True)
    log['completed'] = True; journal.save()
    return {'assets': dict(Counter(a['action'] for a in log['actions'].values())), 'placementsRemoved': len(log['placements'])}


def execute(client, app_id: str, version_id: str, localizations: dict, assets: list[dict],
            journal: Journal, *, cleanup_library=False, report_path: Path, cache_root: Path,
            processing_timeout=600, fill_ready_galleries=False) -> dict:
    cache_root.mkdir(parents=True, exist_ok=True)
    refs = client.get('/appAssetLibraryRefData')
    atomic_json(cache_root / 'asset-library-reference-data.json', refs)
    plan = Catalog(refs).plan(assets)  # Before any remote mutation.
    snapshot = inventory(client, app_id)
    report = {'schemaVersion': 1, 'apiVersion': '4.5.1', 'appId': app_id, 'versionId': version_id,
              'locales': sorted({a['locale'] for a in plan}), 'reviewSubmitted': False,
              'status': 'planned', 'assets': [], 'placements': {}, 'cleanup': None}
    report['selectionSHA256'] = selection_digest(plan)
    atomic_json(cache_root / 'asset-library-upload-plan.json', {'versionId': version_id, 'assets': plan})
    if client.dry_run:
        report['candidateCount'] = len(plan)
        if cleanup_library:
            report['cleanup'] = {'scope': 'entire-library', 'states': dict(Counter(a['attributes']['state'] for a in snapshot['assets']))}
        atomic_json(report_path, report)
        print(f"Dry-run: {len(plan)} selected assets for {report['locales']}; no writes")
        return report
    if cleanup_library:
        if not journal.value['cleanup']:
            atomic_json(cache_root / 'asset-library-cleanup-before.json', snapshot)
        report['cleanup'] = cleanup(client, snapshot, localizations, journal)
        atomic_json(cache_root / 'asset-library-cleanup-after.json', inventory(client, app_id))
    remotes = {}
    # Submit the batch before polling: a slow video must not block image uploads.
    report['status'] = 'transferring'
    report['reservations'] = []
    atomic_json(report_path, report)
    for asset in sorted(plan, key=lambda a: a['kind'] != 'video'):
        key = asset_key(asset)
        if key not in remotes:
            remotes[key] = upload_asset(client, snapshot['libraryId'], asset, journal, defer_processing=True)
            report['reservations'].append({'assetId': remotes[key]['id'], 'fileName': asset['fileName'],
                                           'locale': asset['locale']})
            atomic_json(report_path, report)
    finalized, processed, placed_types = set(), set(), set()
    placed_sequences, placement_ids = {}, {}
    posters = {}
    groups = defaultdict(list)
    for asset in plan:
        groups[(asset['locale'], asset['placementGroup'])].append(asset)
    deadline = time.monotonic() + processing_timeout
    while True:
        pending = []
        attempted = set()
        for asset in plan:
            key = asset_key(asset)
            if key in finalized or key in attempted:
                continue
            attempted.add(key)
            try:
                if key not in processed:
                    remotes[key] = finalize_asset(client, remotes[key], asset, journal, timeout=0)
                    processed.add(key)
                elif asset['kind'] == 'video':
                    remotes[key] = client.get(f"/{asset['resource']}/{remotes[key]['id']}")['data']
                remote = remotes[key]
                posters[key] = verify_poster(client, remote, asset, timeout=0) if asset['kind'] == 'video' else None
            except TimeoutError as error:
                pending.append({'fileName': asset['fileName'], 'assetId': remotes[key]['id'], 'reason': str(error)})
                continue
            finalized.add(key)
        # A pending Duo screenshot or iPad video must not block a ready iPhone
        # gallery. Replace each placement type only once all its files are ready.
        for (locale, group), group_assets in groups.items():
            group_assets.sort(key=lambda a: a['kind'] != 'video')
            ready_types = {kind for kind in {a['placementType'] for a in group_assets}
                           if (locale, group, kind) not in placed_types and
                           all(asset_key(a) in finalized for a in group_assets if a['placementType'] == kind)}
            ready_assets = [a for a in group_assets if a['placementType'] in ready_types]
            if fill_ready_galleries:
                for kind in {a['placementType'] for a in group_assets} - ready_types:
                    if (locale, group, kind) in placed_types:
                        continue
                    subset = [a for a in group_assets if a['placementType'] == kind and asset_key(a) in finalized]
                    if not subset:
                        continue
                    ready_ids = {remotes[asset_key(a)]['id'] for a in subset}
                    current = localization_placements(client, localizations[locale], group=group, placement_type=kind)
                    # Fill an empty gallery, or extend its already-ready subset.
                    # Never remove any existing asset to publish a partial batch.
                    if all(linked_asset(p) in ready_ids for p in current if p['attributes']['placementType'] == kind):
                        ready_assets.extend(subset)
            ready_assets = [a for a in ready_assets if placed_sequences.get((locale, group, a['placementType'])) !=
                            tuple(remotes[asset_key(b)]['id'] for b in ready_assets if b['placementType'] == a['placementType'])]
            if not ready_assets:
                continue
            ready_assets.sort(key=lambda a: group_assets.index(a))
            ids = place_group(client, localizations[locale], group, ready_assets, remotes)
            for kind in {a['placementType'] for a in ready_assets}:
                placed_sequences[(locale, group, kind)] = tuple(remotes[asset_key(a)]['id'] for a in ready_assets if a['placementType'] == kind)
                placement_ids[(locale, group, kind)] = [identifier for a, identifier in zip(ready_assets, ids) if a['placementType'] == kind]
            report['placements'][f'{locale}/{group}'] = [identifier for (l, g, kind), values in placement_ids.items()
                                                       if (l, g) == (locale, group) for identifier in values]
            placed_types.update((locale, group, kind) for kind in ready_types)
            print(f'  ✓ {locale}/{group}: {len(ids)} ordered placements verified', flush=True)
        report['assets'] = []
        for asset in plan:
            key = asset_key(asset)
            if key not in finalized:
                continue
            remote = remotes[key]
            report['assets'].append({'id': asset['id'], 'locale': asset['locale'], 'fileName': asset['fileName'],
                'sha256': asset['sha256'], 'bytes': asset['bytes'], 'assetId': remote['id'], 'resource': asset['resource'],
                'specId': remote['attributes']['specId'], 'state': remote['attributes']['state'],
                'placementType': asset['placementType'], 'placementGroup': asset['placementGroup'],
                'posterTimeCode': remote['attributes'].get('previewFrameTimeCode'), 'posterVerification': posters[key]})
        report['pendingAssets'] = pending
        if pending:
            report['pending'] = pending[0]
        else:
            report.pop('pending', None)
        report['status'] = 'waiting-for-processing' if pending else 'verified'
        atomic_json(report_path, report)
        if not pending:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{len(pending)} assets still processing; ready placement types were verified")
        time.sleep(min(3, max(0, deadline - time.monotonic())))
    delivery_receipt(plan, remotes, cache_root/'asset-library-delivery-receipt.json', app_id, version_id)
    return report


def verify(client, version_id: str, localizations: dict, assets: list[dict], journal: Journal, report_path: Path) -> dict:
    """Read-only verification against the local selection and upload journal."""
    plan = Catalog(client.get('/appAssetLibraryRefData')).plan(assets)
    groups, remotes = defaultdict(list), {}
    for asset in plan:
        record = journal.value['assets'].get(asset_key(asset), {})
        if not record.get('assetId'):
            raise RuntimeError(f"{asset['fileName']}: no verified reservation in this app's journal")
        remote = wait_ready(client, asset['resource'], record['assetId'], asset, timeout=0)
        remotes[asset_key(asset)] = remote
        if asset['kind'] == 'video':
            verify_poster(client, remote, asset, timeout=0)
        groups[(asset['locale'], asset['placementGroup'])].append(asset)
    verified_groups = {}
    for (locale, group), group_assets in groups.items():
        group_assets.sort(key=lambda a: a['kind'] != 'video')
        selected_types = {a['placementType'] for a in group_assets}
        ids = []
        for kind in dict.fromkeys(a['placementType'] for a in group_assets):
            actual = [p for p in localization_placements(client, localizations[locale], group=group, placement_type=kind)
                      if p['attributes']['placementType'] == kind]
            expected = [remotes[asset_key(a)]['id'] for a in group_assets if a['placementType'] == kind]
            if [linked_asset(p) for p in actual] != expected:
                raise RuntimeError(f'{locale}/{group}/{kind}: remote placements differ from selection')
            if any(p['attributes'].get('state') in {'FAILED', 'ASSET_PROCESSING'} for p in actual):
                raise RuntimeError(f'{locale}/{group}/{kind}: placement processing not complete')
            ids.extend(p['id'] for p in actual)
        verified_groups[f'{locale}/{group}'] = ids
    report = {'status': 'verified', 'apiVersion': '4.5.1', 'selectionSHA256': selection_digest(plan),
              'appId': journal.value['appId'], 'versionId': version_id,
              'locales': sorted(localizations), 'placements': verified_groups, 'reviewSubmitted': False}
    atomic_json(report_path, report)
    delivery_receipt(plan, remotes, journal.path.parent/'asset-library-delivery-receipt.json',
                     journal.value['appId'], version_id)
    return report
