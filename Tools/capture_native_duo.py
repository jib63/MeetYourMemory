#!/usr/bin/env python3
"""Capture actual Duo framebuffers with the app's existing marketing fixtures.

No posture or layout overrides: Device Hub must expose the physical display.
The app records its real SDK context; inactive ports and mismatched modes fail.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from PIL import Image, ImageOps
from appstore_media import atomic_json, digest, validate

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = 'com.jibstudios.Meet-Your-Memory'
SCENES = {
    'outer': [('01-home','home'), ('02-visual-memory','visual'),
              ('04-association-memory','association'), ('06-history','history')],
    'inner': [('01-home','home'), ('05-memory-profile','result'),
              ('07-panorama-pairs','panoramaPairs'), ('08-orbit-map','orbitMap'),
              ('09-sound-board','soundBoard'), ('10-comet-field','cometField')],
}

def sim(*args):
    return subprocess.check_output(['xcrun','simctl',*map(str,args)],text=True,stderr=subprocess.PIPE,timeout=40).strip()

def capture(udid, app, posture, locales, scene_names=None):
    config=json.loads((ROOT/'AppStore/media/meet-your-memory.json').read_text())
    inventory=sim('io',udid,'enumerate')
    pixels='1398, 2034' if posture=='outer' else '2007, 2853'
    sections=re.split(r'\n    \(\d+\) ',inventory)
    display=next((re.search(r'Name: (.+)',s).group(1).strip() for s in sections if f'Pixel Size: {{{pixels}}}' in s),None)
    if not display: raise ValueError('Required native Duo display is unavailable')
    sim('install',udid,app)
    sim('status_bar',udid,'override','--time','9:41','--dataNetwork','wifi','--wifiMode','active','--wifiBars','3','--batteryState','charged','--batteryLevel','100')
    container=Path(sim('get_app_container',udid,BUNDLE,'data'))
    build=[digest(path) for path in [app/'Meet Your Memory', app/'Meet Your Memory.debug.dylib'] if path.exists()]
    scenes = [(name,scene) for name,scene in SCENES[posture] if not scene_names or scene in scene_names]
    if scene_names and set(scene_names) - {scene for name,scene in scenes}:
        raise ValueError('Unknown capture scene for this posture')
    for locale in locales:
        language=config['locales'][locale]['language']
        region=config['locales'][locale]['region']
        folder=ROOT/'Screenshots'/f'iphone-duo-{posture}'/language
        work=ROOT/'Screenshots/.native-work'/posture/language
        folder.mkdir(parents=True,exist_ok=True);work.mkdir(parents=True,exist_ok=True)
        captures=[]
        for name,scene in scenes:
            args=['-AppleLanguages',f'({language})','-AppleLocale',region,'--marketing-native-capture','UI_TESTING']
            if scene in {'panoramaPairs','orbitMap','soundBoard','cometField'}:
                args+=['--duo-ui-testing','--duo-test-game',scene]
            else:args+=['--marketing-screen',scene]
            report=container/'Documents/marketing-display-context.json'
            report.unlink(missing_ok=True)
            sim('launch','--terminate-running-process',udid,BUNDLE,*args)
            deadline=time.monotonic()+15
            expected='compact' if posture=='outer' else 'expanded'
            while time.monotonic()<deadline:
                if report.exists() and json.loads(report.read_text())['mode']==expected:break
                time.sleep(.2)
            if not report.exists():raise RuntimeError('No native SDK posture report; install the current capture build')
            context=json.loads(report.read_text())
            if context['mode']!=expected:raise RuntimeError(f'{posture} capture needs {expected} physical posture; SDK reports {context}')
            time.sleep(1.5 if scene=='history' else 1)
            original=work/f'{name}-native.png'
            sim('io',udid,'screenshot',f'--display={display}',original)
            destination=folder/f'{name}.png'
            with Image.open(original) as image:
                normalized=ImageOps.exif_transpose(image).convert('RGB')
                normalized.save(destination)
            validate(destination,f'duo-{posture}')
            captures.append({**digest(destination),'scene':name,'locale':locale,'language':language,
                             'original':digest(original),'display':display,'deviceUDID':udid,'sdkContext':context,'launchArguments':args,
                             'orientation':'landscape' if normalized.width>normalized.height else 'portrait'})
            atomic_json(work/'checkpoint.json',{'captures':captures,'complete':False})
            print(f'{locale}/{posture}/{name}: native pixels and SDK posture verified',flush=True)
        atomic_json(folder/'capture-manifest.json',{'language':language,'locale':locale,'display':display,
                    'posture':'physical fully folded' if posture=='outer' else 'physical fully unfolded',
                    'appBuild':build,'captures':captures,'complete':True})
        atomic_json(work/'checkpoint.json',{'captures':captures,'complete':True})

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--udid',required=True)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--posture',choices=SCENES,required=True)
    parser.add_argument('--locales',default='en-US,fr-FR,it,es-ES,pt-PT,ja,zh-Hans,hi')
    parser.add_argument('--scenes',default='',help='Optional comma-separated marketing scene names')
    args=parser.parse_args();capture(args.udid,args.app,args.posture,args.locales.split(','),args.scenes.split(',') if args.scenes else None)

if __name__=='__main__':main()
