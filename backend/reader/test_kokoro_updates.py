import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import kokoro_updates as updates


class ModelUpdateTests(unittest.TestCase):
    def test_official_german_metadata_supplies_pinned_revision_and_checksums(self):
        names = ['kokoro-martin.onnx', 'voices-martin.npz']
        data = dict(sha='a'*40, siblings=[dict(rfilename=name, lfs=dict(sha256='b'*64)) for name in names])
        with patch('kokoro_updates.metadata', return_value=data):
            revision, assets = updates.upstream('de')
        self.assertEqual(revision, 'a'*40)
        self.assertTrue(all('/resolve/' + revision + '/' in a[1] for a in assets))

    def test_missing_checksum_does_not_enable_unverified_update(self):
        data = dict(sha='a'*40, siblings=[dict(rfilename='kokoro-martin.onnx')])
        with patch('kokoro_updates.metadata', return_value=data):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                updates.upstream('de')

    def test_standard_release_checksums_required_for_new_assets(self):
        data = dict(tag_name='model-files-v1.1', assets=[dict(name=a[0], digest=None) for a in updates.ASSETS['en']])
        with patch('kokoro_updates.metadata', return_value=[data]):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                updates.upstream('en')

    def test_default_models_report_up_to_date_by_content(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[Path(folder)/name for name in ('model', 'voice')]
            for path in paths: path.write_bytes(b'known')
            digest=hashlib.sha256(b'known').hexdigest()
            assets=[(p.name,'https://example.test/',digest) for p in paths]
            with patch('kokoro_updates.upstream', return_value=('revision',assets)), patch('kokoro_updates.model_paths', return_value=paths):
                self.assertFalse(updates.check('de')['available'])
                paths[0].write_bytes(b'old')
                self.assertTrue(updates.check('de')['available'])

    def test_failed_second_download_keeps_previous_active_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            active=Path(folder)/'active-models.json'
            original={'de': {'folder': 'versions/old', 'revision': 'old'}}
            active.write_text(json.dumps(original))
            assets=[(a[0],'https://example.test/','b'*64) for a in updates.ASSETS['de']]
            with patch.object(updates,'FOLDER',Path(folder)), patch.object(updates,'ACTIVE',active), patch('kokoro_updates.upstream',return_value=('new',assets)), patch('kokoro_updates.download_asset',side_effect=[None,OSError('offline')]):
                with self.assertRaises(OSError): updates.update('de')
            self.assertEqual(json.loads(active.read_text()), original)

    def test_update_activates_pair_only_after_voice_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            active=Path(folder)/'active-models.json';base=Path(folder)
            assets=[(a[0],'https://example.test/','b'*64) for a in updates.ASSETS['de']]
            model=Mock();model.get_voices.return_value=['martin'];model.create.return_value=([.1],24000)
            with patch.object(updates,'FOLDER',base), patch.object(updates,'ACTIVE',active), patch('kokoro_updates.upstream',return_value=('new',assets)), patch('kokoro_updates.download_asset'), patch('kokoro_compat.load',return_value=model), patch('kokoro_updates.write_launcher'):
                result=updates.update('de')
            self.assertFalse(result['available'])
            self.assertEqual(json.loads(active.read_text())['de']['revision'],'new')

    def test_active_paths_cannot_escape_private_model_folder(self):
        with patch('kokoro_updates.active_models', return_value={'de': {'folder':'../../outside'}}):
            self.assertEqual(updates.model_paths('de'),[updates.FOLDER/a[0] for a in updates.ASSETS['de']])
