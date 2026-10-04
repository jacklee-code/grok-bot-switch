"""Entry-point checks using temporary scope files and mocked process actions."""
import json
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class AppTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Requires a real NTFS junction')
    def test_cli_rejects_real_junction_without_resolving_it_away(self):
        with tempfile.TemporaryDirectory(prefix='grok-app-junction-') as directory:
            root = Path(directory)
            target, junction, profile = root / 'target install', root / 'linked install', root / 'profile'
            (target / 'resources').mkdir(parents=True)
            profile.mkdir()
            original = b'fixture must remain untouched'
            (target / 'Grok Bot.exe').write_bytes(original)
            (target / 'resources' / 'app.asar').write_bytes(original)
            scope = root / 'scope.json'
            scope.write_text(json.dumps({'version': 1, 'hostVersion': '1494ebd',
                                         'agentIds': ['11111111-1111-4111-8111-111111111111']}))
            script = "$request = [Console]::In.ReadToEnd() | ConvertFrom-Json; New-Item -ItemType Junction -Path $request.link -Target $request.target -ErrorAction Stop | Out-Null"
            created = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                     input=json.dumps({'link': str(junction), 'target': str(target)}),
                                     capture_output=True, text=True, timeout=15,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(created.returncode, 0, created.stderr)
            try:
                args = app.parser().parse_args([
                    '--patch', '--dry-run', '--no-restart', '--install-dir', str(junction),
                    '--profile-dir', str(profile), '--state-root', str(root / 'state'), '--scope', str(scope)])
                with mock.patch.object(app, 'write_result') as report:
                    self.assertEqual(app.cli(args), 1)
                self.assertEqual(report.call_args.args[0]['code'], 'unsafe_path')
                self.assertEqual((target / 'Grok Bot.exe').read_bytes(), original)
                self.assertEqual((target / 'resources' / 'app.asar').read_bytes(), original)
                self.assertFalse((root / 'state').exists())
                self.assertFalse((profile / app.SCOPE_NAME).exists())
            finally:
                # Remove only this verified junction inside our temporary root.
                # os.rmdir removes the junction entry, not its target directory.
                self.assertEqual(junction.parent, root)
                self.assertTrue(junction.lstat().st_file_attributes & 0x400)
                os.rmdir(junction)

    @unittest.skipUnless(os.name == 'nt', 'Requires real Windows 8.3 aliases')
    def test_cli_short_alias_matches_long_process_and_preserves_launch_paths(self):
        with tempfile.TemporaryDirectory(prefix='grok-app-short-alias-') as directory:
            root = Path(directory)
            install, profile = root / 'Grok Long Installation', root / 'Grok Long Profile'
            install.mkdir(); profile.mkdir()
            (install / 'Grok Bot.exe').write_bytes(b'not executable; launch is mocked')
            get_short = ctypes.windll.kernel32.GetShortPathNameW
            get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
            get_short.restype = ctypes.c_uint32
            def short_path(path):
                buffer = ctypes.create_unicode_buffer(32768)
                length = get_short(str(path), buffer, len(buffer))
                self.assertGreater(length, 0)
                self.assertLess(length, len(buffer))
                return buffer.value
            short_install, short_profile = short_path(install), short_path(profile)
            if os.path.normcase(short_install) == os.path.normcase(str(install)):
                self.skipTest('8.3 aliases are disabled on the temporary volume')
            scope = root / 'scope.json'
            scope.write_text(json.dumps({'version': 1, 'hostVersion': '1494ebd',
                                         'agentIds': ['11111111-1111-4111-8111-111111111111']}))
            args = app.parser().parse_args([
                '--patch', '--install-dir', short_install, '--profile-dir', short_profile,
                '--scope', str(scope), '--state-root', str(root / 'state')])
            result = {'ok': True, 'result': {'changed': True, 'stopped_processes': 0}}
            with mock.patch.object(app, 'running_processes', return_value=[{'ExecutablePath': str(install / 'Grok Bot.exe')}]), \
                    mock.patch.object(app, 'execute', return_value=result) as execute, \
                    mock.patch.object(app, '_is_admin', return_value=False), \
                    mock.patch.object(app.subprocess, 'Popen') as launch, \
                    mock.patch.object(app, 'write_result'):
                self.assertEqual(app.cli(args), 0)
            self.assertTrue(execute.call_args.args[0]['restart_if_changed'])
            self.assertEqual(execute.call_args.args[0]['install_dir'], short_install)
            self.assertEqual(launch.call_args.args[0], [str(Path(short_install) / 'Grok Bot.exe'), '--user-data-dir=' + short_profile])
            self.assertTrue(result['result']['relaunch_requested'])

    def test_elevation_retry_preserves_restart_and_profile(self):
        with tempfile.TemporaryDirectory(prefix='grok-app-test-') as directory:
            root = Path(directory)
            scope = root / 'scope.json'
            scope.write_text(json.dumps({'version': 1, 'hostVersion': '1494ebd',
                                         'agentIds': ['11111111-1111-4111-8111-111111111111']}))
            install, profile = root / 'custom install', root / 'custom profile'
            args = app.parser().parse_args([
                '--patch', '--install-dir', str(install), '--profile-dir', str(profile),
                '--scope', str(scope), '--allow-elevation', '--state-root', 'relative-state',
                '--node-path', 'relative-node.exe'])
            elevated_response = {'ok': True, 'result': {'changed': True, 'stopped_processes': 0}}
            with mock.patch.object(app, 'running_processes', return_value=[{'ExecutablePath': str(install / 'Grok Bot.exe')}]), \
                    mock.patch.object(app, 'execute', side_effect=PermissionError('protected directory')), \
                    mock.patch.object(app, 'elevate_once', return_value=elevated_response) as elevate, \
                    mock.patch.object(app, '_is_admin', return_value=False), \
                    mock.patch.object(app.subprocess, 'Popen') as launch, \
                    mock.patch.object(app, 'write_result'):
                self.assertEqual(app.cli(args), 0)
            request = elevate.call_args.args[0]
            self.assertTrue(request['restart_if_changed'])
            self.assertTrue(Path(request['state_root']).is_absolute())
            self.assertTrue(Path(request['node_path']).is_absolute())
            self.assertEqual(launch.call_args.args[0], [str(install / 'Grok Bot.exe'), '--user-data-dir=' + str(profile)])
            self.assertTrue(elevated_response['result']['relaunch_requested'])

    def test_scope_parser_rejects_duplicate_keys_before_model_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            scope = Path(directory) / 'scope.json'
            scope.write_text('{"version":1,"version":1,"hostVersion":"1494ebd","agentIds":["11111111-1111-4111-8111-111111111111"]}')
            with self.assertRaises(app.PatcherError):
                app.read_scope(scope)

    def test_typed_profile_change_invalidates_loaded_scope(self):
        ui = app.Application.__new__(app.Application)
        ui.scope = {'version': 1}
        ui.scope_profile = app.path_key('first-profile')
        ui.profile = mock.Mock()
        ui.profile.get.return_value = 'second-profile'
        ui.load_profile_scope = mock.Mock()
        ui.append = mock.Mock()
        ui.check_scope_profile()
        ui.load_profile_scope.assert_called_once()

    def test_admin_parent_does_not_start_elevated_grok(self):
        request = {'install_dir': 'app', 'profile_dir': 'profile'}
        result = {'ok': True, 'result': {'changed': True, 'stopped_processes': 1}}
        with mock.patch.object(app, '_is_admin', return_value=True), mock.patch.object(app.subprocess, 'Popen') as launch:
            app.relaunch_if_needed(request, result)
        launch.assert_not_called()
        self.assertFalse(result['result']['relaunch_requested'])
        self.assertIn('relaunch_error', result['result'])

    def test_gui_rejects_cli_only_dry_run_flag(self):
        with mock.patch.object(sys, 'argv', ['app.py', '--dry-run']), \
                mock.patch('argparse.ArgumentParser.error', side_effect=ValueError('expected explicit mode')):
            with self.assertRaisesRegex(ValueError, 'expected explicit mode'):
                app.main()


if __name__ == '__main__':
    unittest.main()
