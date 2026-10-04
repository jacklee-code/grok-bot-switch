"""Entry-point checks using temporary scope files and mocked process actions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class AppTests(unittest.TestCase):
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
