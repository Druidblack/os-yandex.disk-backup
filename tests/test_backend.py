"""Offline unit tests. Do not contact Yandex, and do not read a real OPNsense config."""
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SCRIPT = (Path(__file__).resolve().parents[1]
          / 'src/opnsense/scripts/OPNsense/YandexBackup/yandexbackup.py')
spec = importlib.util.spec_from_file_location('yd_backup', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class BackupTests(unittest.TestCase):
    def test_encryption_interface_removed(self):
        self.assertFalse(hasattr(mod, 'encrypt_blob'))
        self.assertFalse(hasattr(mod, 'decrypt_blob'))
        self.assertFalse(hasattr(mod, 'restore_local'))
        self.assertNotIn('decrypt-local', Path(mod.__file__).read_text())

    def test_config_and_only_our_files(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'config.xml'
            file.write_text('''<opnsense><system><hostname>fw-1</hostname></system>
                <OPNsense><yandexbackup><general>
                <enabled>1</enabled><oauth_token>topsecret</oauth_token>
                <remote_folder>OPNsense-Backups/Home</remote_folder><retention>2</retention>
                <encrypt>1</encrypt><encrypt_password>another-long-password</encrypt_password>
                </general></yandexbackup></OPNsense></opnsense>''')
            with patch.object(mod, 'CONFIG_FILE', file):
                cfg = mod.read_config()
            self.assertEqual(cfg['hostname'], 'fw-1')
            self.assertEqual(cfg['retention'], 2)
            self.assertNotIn('encrypt', cfg)
            self.assertNotIn('password', cfg)
            files = [
                {'name': 'OPNsense-fw-1-20261001T123456Z-1234abcd.xml.ydenc'},
                {'name': 'OPNsense-fw-2-20261001T123456Z-1234abcd.xml.ydenc'},
                {'name': 'notes.txt'},
                {'name': 'OPNsense-fw-1-20261002T123456Z-1111abcd.xml'},
                {'name': 'OPNsense-fw-1-20261003T123456Z-2222abcd.xml'},
            ]
            chosen = mod.only_our_files(files, 'fw-1')
            self.assertEqual(len(chosen), 2)
            self.assertIn('20261003', chosen[0]['name'])
            self.assertTrue(all(x['name'].endswith('.xml') for x in chosen))

    def test_ui_and_model_do_not_offer_encryption(self):
        root = Path(__file__).resolve().parents[1] / 'src/opnsense'
        paths = [
            'mvc/app/library/OPNsense/Backup/YandexDisk.php',
            'mvc/app/controllers/OPNsense/YandexBackup/forms/general.xml',
            'mvc/app/models/OPNsense/YandexBackup/General.xml',
            'mvc/app/views/OPNsense/YandexBackup/index.volt',
        ]
        for rel in paths:
            content = (root / rel).read_text()
            self.assertNotIn('REST API', content, rel)
            self.assertNotIn('encrypt_password', content, rel)
            self.assertNotIn('AES-256-GCM', content, rel)
        self.assertNotIn("'name' => 'encrypt'", (root / paths[0]).read_text())

    def test_upload_rejects_untrusted_url(self):
        with patch.object(mod, 'api_call', return_value={'href': 'https://evil.example/steal'}):
            with self.assertRaisesRegex(mod.BackupError, 'Unexpected'):
                mod.upload('fake', 'disk:/backup/test.xml', b'data')
        with patch.object(mod, 'api_call', return_value={'href': 'http://uploader.yandex.net/no-tls'}):
            with self.assertRaisesRegex(mod.BackupError, 'Unexpected'):
                mod.upload('fake', 'disk:/backup/test.xml', b'data')

    def test_only_regular_disk_is_checked(self):
        requested = []
        def fake_api(token, method, endpoint, params):
            requested.append(params["path"])
            return {"type": "dir"}
        with patch.object(mod, 'api_call', side_effect=fake_api):
            self.assertIsNone(mod.check_disk_access('fake'))
            self.assertEqual(mod.do_test({'token': 'fake', 'folder': 'Backups'})['storage_root'], 'disk:/')
        self.assertEqual(requested, ['disk:/', 'disk:/'])
        self.assertEqual(mod.disk_path('OPNsense-Backups', 'backup.xml'),
                         'disk:/OPNsense-Backups/backup.xml')

    def test_access_denied_never_falls_back_to_application_folder(self):
        paths = []
        def fake_api(token, method, endpoint, params):
            paths.append(params['path'])
            raise mod.ApiHTTPError(403, 'ForbiddenError')
        with patch.object(mod, 'api_call', side_effect=fake_api):
            with self.assertRaisesRegex(mod.BackupError, 'ForbiddenError') as ctx:
                mod.check_disk_access('secret-token')
        self.assertEqual(paths, ['disk:/'])
        self.assertNotIn('secret-token', str(ctx.exception))
        self.assertIn('cloud_api:disk.write', str(ctx.exception))

    def test_invalid_token_is_rejected_without_retry(self):
        with patch.object(mod, 'api_call', side_effect=mod.ApiHTTPError(401)) as api:
            with self.assertRaisesRegex(mod.BackupError, 'HTTP 401'):
                mod.check_disk_access('bad-token')
        self.assertEqual(api.call_count, 1)

    def test_no_private_storage_support_in_source_or_ui(self):
        root = Path(__file__).resolve().parents[1] / 'src/opnsense'
        for path in root.rglob('*'):
            if path.is_file() and path.suffix in ('.py', '.php', '.xml', '.volt', '.conf'):
                source = path.read_text()
                self.assertNotIn('app:/', source, path)
                self.assertNotIn('cloud_api:disk.app_folder', source, path)
        self.assertFalse(hasattr(mod, 'storage_root'))

    def test_diagnostics_reports_statuses_without_leaking_token(self):
        def fake_api(token, method, endpoint, params=None):
            if endpoint == '/':
                return {'total_space': 1000, 'user': {'login': 'private'}}
            raise mod.ApiHTTPError(403, 'ForbiddenError')
        with patch.object(mod, 'api_call', side_effect=fake_api):
            result = mod.do_diagnose({'token': 'extremely-secret'})
        self.assertEqual(result['disk_info'], 'OK')
        self.assertEqual(result['disk_root'], 'HTTP 403 (ForbiddenError)')
        self.assertNotIn('app_root', result)
        self.assertNotIn('private', repr(result))
        self.assertNotIn('secret', repr(result))

    def test_api_http_error_code_allowlist(self):
        self.assertIn('ForbiddenError', str(mod.ApiHTTPError(403, 'ForbiddenError')))
        self.assertNotIn('secret', str(mod.ApiHTTPError(403, 'https://secret')))
        self.assertNotIn('secret', str(mod.ApiHTTPError(403, 'secret')))

    def test_403_error_only_contains_sanitized_code(self):
        with patch.object(mod, 'api_call', side_effect=mod.ApiHTTPError(403, 'ForbiddenError')):
            with self.assertRaisesRegex(mod.BackupError, 'ForbiddenError') as ctx:
                mod.check_disk_access('secret')
        self.assertNotIn('secret', str(ctx.exception))

    def test_verify_upload_retries_on_404(self):
        tries = []
        def fake_api(token, method, endpoint, params):
            tries.append(1)
            if len(tries) == 1:
                raise mod.ApiHTTPError(404)
            return {'type': 'file', 'size': 4}
        with patch.object(mod, 'api_call', side_effect=fake_api), \
             patch.object(mod.time, 'sleep', return_value=None):
            mod.verify_upload('token', 'disk:/test', b'abcd')
        self.assertEqual(len(tries), 2)

    def test_disk_is_used_for_creation_and_retention(self):
        cfg = dict(enabled=True, token='fake', folder='Backups/Firewall', retention=1,
                   hostname='fw-1')
        paths = []
        with tempfile.TemporaryDirectory() as temp:
            original_config = Path(temp) / 'config.xml'
            original_config.write_text('<opnsense/>')
            def fake_api(token, method, endpoint, params=None):
                paths.append((method, params['path']))
                if method == 'PUT' and endpoint == '/resources':
                    raise mod.ApiHTTPError(409)
                return {}
            with patch.object(mod, 'CONFIG_FILE', original_config), \
                 patch.object(mod, 'LOCK_FILE', Path(temp) / 'lock'), \
                 patch.object(mod, 'check_disk_access', return_value=None), \
                 patch.object(mod, 'api_call', side_effect=fake_api), \
                 patch.object(mod, 'upload', lambda token, path, blob: paths.append(('upload', path))), \
                 patch.object(mod, 'verify_upload', lambda token, path, blob: paths.append(('verify', path))), \
                 patch.object(mod, 'list_files', return_value=[
                     {'name': 'OPNsense-fw-1-20261001T010203Z-11111111.xml.ydenc'},
                     {'name': 'OPNsense-fw-1-20261002T010203Z-11111111.xml'},
                     {'name': 'OPNsense-fw-1-20261003T010203Z-11111111.xml'}
                 ]) as listing:
                result = mod.do_backup(cfg)
                listing.assert_called_once_with('fake', 'Backups/Firewall')
        self.assertEqual(result['storage_root'], 'disk:/')
        self.assertIn(('PUT', 'disk:/Backups'), paths)
        self.assertIn(('PUT', 'disk:/Backups/Firewall'), paths)
        self.assertTrue(any(method == 'upload' and path.startswith('disk:/Backups/Firewall/')
                            for method, path in paths))
        self.assertIn(('DELETE', 'disk:/Backups/Firewall/OPNsense-fw-1-20261002T010203Z-11111111.xml'), paths)
        self.assertFalse(any(method == 'DELETE' and path.endswith('.ydenc') for method, path in paths))

    def test_backup_flow_retention_runs_after_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            original_config = Path(temp) / 'config.xml'
            original_config.write_text('<opnsense/>')
            previous = [
                {'name': f'OPNsense-fw-1-2026100{x}T010203Z-1234abcd.xml'}
                for x in range(1, 4)
            ]
            previous.append({'name': 'OPNsense-fw-2-20261002T010203Z-1234abcd.xml'})
            previous.append({'name': 'OPNsense-fw-1-20260930T010203Z-1234abcd.xml.ydenc'})
            cfg = dict(enabled=True, token='fake', folder='Backups', retention=2,
                       hostname='fw-1')
            calls = []
            uploaded = []
            def fake_api(token, method, endpoint, params=None):
                if method == 'DELETE':
                    calls.append(('delete', params['path']))
                return {}
            with patch.object(mod, 'CONFIG_FILE', original_config), \
                 patch.object(mod, 'LOCK_FILE', Path(temp) / 'lock'), \
                 patch.object(mod, 'check_disk_access', return_value=None), \
                 patch.object(mod, 'ensure_folder', lambda *a: None), \
                 patch.object(mod, 'upload', lambda *a: (calls.append(('upload', a[1])), uploaded.append(a[2]))), \
                 patch.object(mod, 'verify_upload', lambda *a: calls.append(('verified', a[1]))), \
                 patch.object(mod, 'list_files', lambda *a: previous), \
                 patch.object(mod, 'api_call', side_effect=fake_api):
                result = mod.do_backup(cfg)
            self.assertTrue(result['file'].endswith('.xml'))
            self.assertEqual(uploaded, [b'<opnsense/>'])
            self.assertEqual(calls[0][0], 'upload')
            self.assertEqual(calls[1][0], 'verified')
            self.assertTrue(all('fw-2' not in str(x) for x in calls))
            self.assertEqual(len([x for x in calls if x[0] == 'delete']), 1)
            self.assertFalse(any('.ydenc' in str(x) for x in calls))

if __name__ == '__main__':
    unittest.main()
