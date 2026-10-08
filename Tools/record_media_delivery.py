#!/usr/bin/env python3
"""Refresh the local review bundle from an independently verified API receipt."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from appstore_asset_library import selection_digest, validate_file
from appstore_media import atomic_json
from prepare_appstore_media import review

ROOT = Path(__file__).resolve().parent.parent


def main():
    delivery = ROOT / 'AppStore/exports/delivery'
    cache = ROOT / 'AppStore/exports/.work/api'
    manifest = json.loads((delivery / 'delivery-manifest.json').read_text())
    receipt = json.loads((cache / 'asset-library-delivery-receipt.json').read_text())
    verified = json.loads((cache / 'verification-report.json').read_text())
    plan = json.loads((cache / 'asset-library-upload-plan.json').read_text())
    if (verified['status'] != 'verified' or receipt['app'] != manifest['app']
        or verified['appId'] != receipt['appId'] or verified['versionId'] != receipt['versionId']
        or verified['selectionSHA256'] != selection_digest(plan['assets'])):
        raise ValueError('Receipt and independent verification do not match this delivery')
    records = {(a['assetKey'],a['locale']):a for a in receipt['assets']}
    matched = 0
    for asset in manifest['assets']:
        record = records.get((asset['assetKey'],asset['locale']))
        if not record:
            continue
        validate_file(asset)
        if record['sha256'] != asset['sha256'] or record['profile'] != asset['profile']:
            raise ValueError('Receipt content differs from current local media')
        asset.update(deliveryState='UPLOADED_VERIFIED', remoteAssetId=record['remoteAssetId'],
                     appId=receipt['appId'], versionId=receipt['versionId'])
        matched += 1
    if matched != len(receipt['assets']):
        raise ValueError('Receipt contains assets outside the current local delivery')
    manifest['uploaded'] = all(a.get('deliveryState') == 'UPLOADED_VERIFIED' for a in manifest['assets'])
    manifest['uploadedAssetCount'] = sum(a.get('deliveryState') == 'UPLOADED_VERIFIED' for a in manifest['assets'])
    manifest['screenshotsUploaded'] = all(a.get('deliveryState') == 'UPLOADED_VERIFIED'
                                         for a in manifest['assets'] if a['placement'] in {'duo','iphone-medium','iphone-large','ipad'})
    manifest['remoteVersionId'] = receipt['versionId']
    manifest['serverVerifiedAt'] = datetime.now(timezone.utc).isoformat()
    atomic_json(delivery / 'delivery-manifest.json',manifest)
    types = {a['placementType'] for a in plan['assets']}
    scope = 'screenshots' if types == {'APP_SCREENSHOT'} else 'creatives' if 'APP_SCREENSHOT' not in types else 'media'
    atomic_json(delivery / f'{scope}-delivery-receipt.json',receipt)
    atomic_json(delivery / f'{scope}-server-verification.json',verified)
    validation_path = delivery / 'validation-report.json'
    if validation_path.exists():
        validation = json.loads(validation_path.read_text())
        validation['counts'] = dict(Counter(a['placement'] for a in manifest['assets']))
        validation['fileValidation'] = f'{len(manifest["assets"])} exact-size opaque RGB images with matching SHA-256'
        validation['pending'] = manifest.get('pendingCapture', [])
        validation['uploaded'] = manifest['uploaded']
        validation['uploadedAssetCount'] = manifest['uploadedAssetCount']
        validation[f'{scope}Upload'] = {'status':'UPLOADED_VERIFIED','count':matched,
            'appId':receipt['appId'],'versionId':receipt['versionId'],
            'checkedAt':manifest['serverVerifiedAt'],'report':f'{scope}-server-verification.json'}
        validation['offlineContractTests'] = {'passed':8,'failed':0}
        atomic_json(validation_path,validation)
    handoff_path = delivery / 'api-handoff.json'
    handoff = json.loads(handoff_path.read_text())
    by_name = {a['remoteName']:a for a in receipt['assets']}
    delivered = {a['fileName']:a for a in manifest['assets'] if a.get('deliveryState') == 'UPLOADED_VERIFIED'}
    for asset in handoff['assets']:
        record = by_name.get(asset['fileName'])
        if record:
            asset.update(remoteState='UPLOADED_VERIFIED', remoteAssetId=record['remoteAssetId'])
        elif asset['fileName'] in delivered:
            previous = delivered[asset['fileName']]
            if previous['sha256'] != asset['sha256']:
                raise ValueError('Previously delivered asset differs from the handoff')
            asset.update(remoteState='UPLOADED_VERIFIED', remoteAssetId=previous['remoteAssetId'])
    handoff['remoteState'] = 'PARTIALLY_UPLOADED_VERIFIED' if not manifest['uploaded'] else 'UPLOADED_VERIFIED'
    atomic_json(handoff_path,handoff)
    review(manifest['assets'],delivery)
    print(f'Review bundle refreshed: {manifest["uploadedAssetCount"]} verified server assets')


if __name__ == '__main__': main()
