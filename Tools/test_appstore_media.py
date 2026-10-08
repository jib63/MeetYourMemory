"""Offline regressions for the API 4.5.1 media handoff; no credentials required."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from appstore_asset_library import Catalog, Journal, upload_asset, transfer, validate_duo_route, validate_file, wait_ready
from upload_appstore import Client, media_selection

ROOT = Path(__file__).resolve().parent.parent


class MediaContractTests(unittest.TestCase):
    def test_screenshots_only_excludes_creatives(self):
        assets = media_selection(['en-US'], screenshots_only=True)
        self.assertEqual(len(media_selection(['en-US'])) - len(assets), 2)
        self.assertEqual({a['placement'] for a in assets}, {'iphone-medium','iphone-large','ipad','duo'})

    def test_processed_image_dimensions_must_match(self):
        expected={'kind':'image','fileName':'shot.png','bytes':3,'category':'APP_SCREENSHOTS_AND_PREVIEWS',
                  'expectedSpecIds':['native'],'width':1398,'height':2034}
        class FakeClient:
            def get(self,path):
                return {'data':{'attributes':{'state':'PREPARE_FOR_SUBMISSION','specId':'native',
                    'fileName':'shot.png','fileSize':3,'category':'APP_SCREENSHOTS_AND_PREVIEWS',
                    'imageAsset':{'width':1398,'height':2033}}}}
        with self.assertRaisesRegex(RuntimeError,'dimensions differ'):
            wait_ready(FakeClient(),'appAssetLibraryImages','reserved',expected,timeout=0)

    def test_commit_matches_apple_451_schema(self):
        contract = json.loads((ROOT / 'AppStore/media/specs/api-4.5.1-contract.json').read_text())
        schema = contract['schemas']['AppAssetLibraryImageUpdateRequest']['properties']['data']['properties']['attributes']['properties']
        self.assertIn('uploaded', schema)
        self.assertNotIn('sourceFileChecksum', schema)
        calls = []
        asset = {'path': 'fixture.png', 'fileName': 'fixture-en-US.png', 'sha256': 'abc', 'bytes': 3,
                 'locale': 'en-US', 'kind': 'image', 'resource': 'appAssetLibraryImages', 'category': 'CREATIVE_ASSETS'}
        class FakeClient:
            def get(self, *args, **kwargs): return {'data': []}
            def post(self, path, payload):
                return {'data': {'id': 'reserved', 'attributes': {'fileSize': 3, 'category': 'CREATIVE_ASSETS',
                         'state': 'AWAITING_UPLOAD', 'uploadOperations': []}}}
            def patch(self, path, payload): calls.append((path, payload))
        with tempfile.TemporaryDirectory() as work, patch('appstore_asset_library.transfer'):
            upload_asset(FakeClient(), 'library', asset, Journal(Path(work) / 'journal.json', 'app'), defer_processing=True)
        attrs = calls[0][1]['data']['attributes']
        self.assertEqual(attrs, {'uploaded': True})
        self.assertTrue(set(attrs).issubset(schema))

    def test_duo_stills_cannot_enter_ordinary_gallery(self):
        with self.assertRaises(ValueError):
            validate_duo_route({'kind': 'image', 'profile': 'duo-inner', 'placement': 'iphone-large'})

    def test_outer_and_inner_share_catalog_limit(self):
        refs = {'data': [{'attributes': {
            'placementProfileGroups': [{'placementProfileGroupId': 'duo', 'displayClassId': 'IPHONE_DUO', 'platform': 'IPHONE_APP_STORE'}],
            'placementTypes': [{'placementTypeId': 'APP_SCREENSHOT', 'specMappings': [{'placementGroupId': 'duo', 'specs': ['outer', 'inner']}]}],
            'imageSpecs': [{'specId': name, 'dimensions': {'minWidth': w, 'maxWidth': w, 'minHeight': h, 'maxHeight': h},
                            'fileExtensions': ['.png'], 'maxFileSize': 100} for name,w,h in [('outer',1398,2034),('inner',2007,2853)]],
            'features': [{'featureId': 'APP_STORE_VERSIONS', 'placementPolicies': [{'placementType': 'APP_SCREENSHOT', 'groupLimits': [{'groupIds': ['duo'], 'maxCount': 10}]}]}]
        }}]}
        def item(i):
            w,h=(1398,2034) if i<6 else (2007,2853)
            return {'kind':'image','placement':'duo','locale':'en-US','profile':'duo-outer' if i<6 else 'duo-inner',
                    'path':f'{i}.png','fileName':f'{i}.png','width':w,'height':h,'bytes':1}
        with self.assertRaisesRegex(ValueError, 'exceeds catalog limit'):
            Catalog(refs).plan([item(i) for i in range(11)])
        self.assertEqual(len(Catalog(refs).plan([item(i) for i in range(10)])),10)

    def test_upload_byte_ranges_are_exact_and_unauthenticated(self):
        with tempfile.TemporaryDirectory() as work:
            path=Path(work)/'fixture';path.write_bytes(b'abc')
            asset={'path':str(path),'bytes':3}
            operation={'offset':0,'length':3,'method':'PUT','url':'https://upload.example/part', 'requestHeaders':[{'name':'Content-Type','value':'image/png'}]}
            with patch('requests.request') as request:
                request.return_value.ok=True;request.return_value.status_code=200
                transfer(None,asset,[operation])
                self.assertEqual(request.call_args.kwargs['data'],b'abc')
                self.assertNotIn('Authorization',request.call_args.kwargs['headers'])
            with self.assertRaises(ValueError): transfer(None,asset,[{**operation,'offset':1}])

    def test_rate_limit_honors_entire_retry_after(self):
        class Response:
            status_code=429
            headers={'Retry-After':'95'}
        with patch('upload_appstore.time.sleep') as sleep:
            Client.wait_for_retry(Response(),0)
            self.assertEqual(sum(call.args[0] for call in sleep.call_args_list),95)
        with self.assertRaises(ValueError): Client.api_url('https://outside.example/v1/apps')

    def test_prepared_delivery_rejects_changed_bytes(self):
        assets=media_selection(['en-US'])
        self.assertTrue(all(a['kind']=='image' for a in assets))
        with tempfile.TemporaryDirectory() as work:
            source=Path(assets[0]['path']); target=Path(work)/source.name
            target.write_bytes(source.read_bytes()+b'changed')
            with self.assertRaises(ValueError): validate_file({**assets[0],'path':str(target)})


if __name__ == '__main__': unittest.main()
