#!/usr/bin/env python3
"""Prepare native localized stills and an API 4.5.1 delivery/review bundle.

Preserves capture sources. Does not make network calls or generate previews.
"""
from __future__ import annotations

import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path
import shutil
import subprocess

from appstore_media import atomic_json, digest, identity, validate
from appstore_asset_library import offline_mapping, validate_file
from compose_appstore_creatives import compose

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / 'AppStore/media/meet-your-memory.json'
ORDER = ['01-home', '02-visual-memory', '03-spatial-memory',
         '04-association-memory', '05-memory-profile', '06-history']
GALLERIES = {
    'iphone-medium': ('iphone-medium', 'iphone-medium'),
    'iphone-large': ('6.9-inch', 'iphone-large-screenshot'),
    'ipad': ('ipad-13-inch', 'ipad-screenshot'),
}


def add_asset(records, source, destination, *, locale, language, placement, profile, identifier):
    details = validate(source, profile)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    record = {**digest(destination), **details, 'app': 'meet-your-memory',
              'id': identifier, 'locale': locale, 'language': language,
              'placement': placement, 'profile': profile, 'fileName': destination.name,
              'source': digest(source), 'reviewState': 'LOCAL_VISUAL_REVIEW',
              'deliveryState': 'PREPARED_LOCALLY'}
    record['assetKey'] = identity(record['app'], record['sha256'], language, profile)
    record['api'] = offline_mapping(record)
    records.append(record)


def review(records, destination):
    items = []
    for a in records:
        src = Path(a['path']).relative_to(destination).as_posix()
        label = f"{a['locale']} · {a['placement']} · {a['id']}"
        state = escape(a.get('deliveryState', 'PREPARED_LOCALLY'))
        items.append(f'<figure data-locale="{escape(a["locale"])}"><a href="{escape(src)}">'
                     f'<img loading="lazy" src="{escape(src)}" alt="{escape(label)}"></a>'
                     f'<figcaption>{escape(label)}<br>{a["width"]} × {a["height"]}<br>{state}</figcaption></figure>')
    locales = sorted({a['locale'] for a in records})
    options = ''.join(f'<option>{escape(l)}</option>' for l in locales)
    uploaded = sum(a.get('deliveryState') == 'UPLOADED_VERIFIED' for a in records)
    status = (f'{uploaded} uploaded and verified · {len(records)-uploaded} prepared locally'
              if uploaded else 'Prepared locally · No upload')
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Meet Your Memory · App Store media</title>
<style>body{background:#130e29;color:#eee9ff;font:16px system-ui;margin:32px}h1{font-weight:900}
select{padding:10px;border-radius:12px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px}
figure{margin:0;background:#211639;padding:16px;border-radius:20px}img{width:100%;height:360px;object-fit:contain}
figcaption{margin-top:12px;color:#a7eee3}p{color:#c7bfdb}</style>
<h1>Meet Your Memory</h1><p>Localized native screenshots, product-page headers and search artwork. Still images only.
'''+status+''' · API 4.5.1 · No review submission.</p><p><label>Language <select id="locale"><option>All</option>'''+options+'''</select></label></p><main>'''+''.join(items)+'''</main>
<script>document.querySelector('#locale').onchange=e=>document.querySelectorAll('figure').forEach(f=>f.hidden=e.target.value!=='All'&&f.dataset.locale!==e.target.value)</script></html>'''
    (destination / 'index.html').write_text(html)


def prepare(config, *, render=False, include_duo=False, include_duo_outer=False):
    output = ROOT / config['outputRoot']
    delivery = output / 'delivery'
    delivery.mkdir(parents=True, exist_ok=True)
    previous_path = delivery / 'delivery-manifest.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    previous_assets = {(a['assetKey'],a['locale']):a for a in previous.get('assets', [])}
    renderer = output / '.work/render-creative-text'
    if render:
        renderer.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['xcrun', 'swiftc', str(ROOT / config['rendererSource']), '-o', str(renderer)], check=True)
    assets = []
    for locale, entry in config['locales'].items():
        language = entry['language']
        for job in config['creatives']:
            target = output / 'creative' / job['placement'] / locale / f'meet-your-memory-{job["placement"]}-{locale}.png'
            if render:
                target.parent.mkdir(parents=True, exist_ok=True)
                layout = dict(job['layout'])
                layout['textLayers'] = [{**layer, 'text': entry[layer['textKey']]} for layer in layout['textLayers']]
                compose(ROOT / job['background'], ROOT / job['ui'].format(language=language) if job.get('ui') else None,
                        [], tuple(job['size']), config['style'], layout, renderer, target)
            add_asset(assets, target, delivery / 'creative' / locale / target.name,
                      locale=locale, language=language, placement=job['placement'], profile=job['profile'], identifier=job['id'])
        for placement, (folder, profile) in GALLERIES.items():
            for name in ORDER:
                source = ROOT / 'Screenshots' / folder / language / f'{name}.jpg'
                dest = delivery / 'screenshots' / placement / locale / f'meet-your-memory-{placement}-{name}-{locale}.jpg'
                add_asset(assets, source, dest, locale=locale, language=language, placement=placement,
                          profile=profile, identifier=f'{placement}-{name}')
        if include_duo or include_duo_outer:
            for job in config['duoScreenshots']:
                if not include_duo and job['profile'] != 'duo-outer':
                    continue
                source = ROOT / job['source'].format(language=language)
                capture = json.loads((source.parent / 'capture-manifest.json').read_text())
                evidence = next((item for item in capture['captures'] if item['scene'] == source.stem), None)
                expected_mode = 'compact' if job['profile'] == 'duo-outer' else 'expanded'
                if (not capture['complete'] or capture['locale'] != locale or not evidence
                    or evidence['sha256'] != digest(source)['sha256']
                    or evidence['sdkContext']['mode'] != expected_mode):
                    raise ValueError(f'Native Duo capture provenance failed: {source}')
                dest = delivery / 'screenshots/duo' / locale / f'meet-your-memory-{job["id"]}-{locale}.png'
                add_asset(assets, source, dest, locale=locale, language=language, placement='duo',
                          profile=job['profile'], identifier=job['id'])
    for a in assets:
        validate_file(a)
        prior = previous_assets.get((a['assetKey'],a['locale']))
        if (previous.get('app') == config['app'] and prior and prior['sha256'] == a['sha256']
            and prior.get('deliveryState') == 'UPLOADED_VERIFIED'):
            for key in ['deliveryState','remoteAssetId','appId','versionId']:
                if key in prior: a[key] = prior[key]
    for (locale, placement), count in Counter((a['locale'], a['placement']) for a in assets).items():
        if placement not in {'header','search'} and count > 10:
            raise ValueError(f'{locale}/{placement}: exceeds ten screenshots')
    manifest = {'schemaVersion': 1, 'app': config['app'], 'bundleId': config['bundleId'],
                'apiVersion': '4.5.1', 'apiContract': config['apiCoverage'], 'assets': assets,
                'previewsGenerated': False, 'uploaded': all(a['deliveryState']=='UPLOADED_VERIFIED' for a in assets),
                'uploadedAssetCount': sum(a['deliveryState']=='UPLOADED_VERIFIED' for a in assets), 'reviewSubmitted': False,
                'duoIncluded': include_duo or include_duo_outer,
                'duoCoverage': 'outer-and-inner' if include_duo else 'outer-only' if include_duo_outer else 'none',
                'pendingCapture': [] if include_duo else ['Duo inner: requires physical fully unfolded portrait simulator']}
    atomic_json(delivery / 'delivery-manifest.json', manifest)
    atomic_json(delivery / 'api-handoff.json', {'apiVersion':'4.5.1','assets':[
        {'fileName':a['fileName'],'locale':a['locale'],'sha256':a['sha256'],**a['api']} for a in assets],
        'remoteState':'NOT_UPLOADED','requiredDiscovery':'GET /v1/appAssetLibraryRefData',
        'commit':{'uploaded':True},'reviewSubmission':False})
    review(assets, delivery)
    banner = output / 'banner/meet-your-memory-banner.png'
    banner.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output / 'creative/header/en-US/meet-your-memory-header-en-US.png', banner)
    print(f'Prepared {len(assets)} localized images; {delivery / "index.html"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--include-duo', action='store_true')
    parser.add_argument('--include-duo-outer', action='store_true')
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    if args.validate:
        path = ROOT / config['outputRoot'] / 'delivery/delivery-manifest.json'
        manifest = json.loads(path.read_text())
        for a in manifest['assets']: validate_file(a)
        print(f'Validated {len(manifest["assets"])} opaque images, hashes and exact native/creative sizes')
    else:
        prepare(config, render=args.render, include_duo=args.include_duo, include_duo_outer=args.include_duo_outer)


if __name__ == '__main__': main()
