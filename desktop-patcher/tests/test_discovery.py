import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import discovery


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='grok-discovery-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def install(self, path):
        (path / 'resources').mkdir(parents=True)
        (path / 'Grok Bot.exe').write_bytes(b'fixture')
        (path / 'resources/app.asar').write_bytes(b'fixture')
        return path

    def test_running_install_custom_drive_and_registry_deduplicate(self):
        install = self.install(self.root / 'custom-app')
        rows = [{'ExecutablePath': str(install / 'Grok Bot.exe'), 'ProcessId': 123, 'CommandLine': ''}]
        with mock.patch.object(discovery, 'running_processes', return_value=rows), \
             mock.patch.object(discovery, '_registry_candidates', return_value=[(install, 'registry')]), \
             mock.patch.dict(os.environ, {}, clear=True):
            result = discovery.discover_installations()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['sources'], ['running process', 'registry'])
        self.assertEqual(result[0]['install_dir'], str(install))

    def test_only_bounded_common_folders_are_considered(self):
        install = self.install(self.root / 'Programs/Grok Bot')
        self.install(self.root / 'nested/random/Grok Bot')
        with mock.patch.object(discovery, 'running_processes', return_value=[]), \
             mock.patch.object(discovery, '_registry_candidates', return_value=[]), \
             mock.patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)}, clear=True):
            result = discovery.discover_installations()
        self.assertEqual([row['install_dir'] for row in result], [str(install)])

    def test_profile_respects_selected_install_and_custom_user_data_dir(self):
        install = self.root / 'app-one'
        profile = self.root / 'Profile With Spaces'
        profile.mkdir()
        other = self.root / 'Other Profile'
        other.mkdir()
        rows = [{'ExecutablePath': str(install / 'Grok Bot.exe'), 'ProcessId': 1,
                 'CommandLine': '"Grok Bot.exe" --user-data-dir="' + str(profile) + '"'},
                {'ExecutablePath': str(self.root / 'app-two/Grok Bot.exe'), 'ProcessId': 2,
                 'CommandLine': '"Grok Bot.exe" --user-data-dir "' + str(other) + '"'}]
        with mock.patch.object(discovery, 'running_processes', return_value=rows), \
             mock.patch.dict(os.environ, {}, clear=True):
            result = discovery.discover_profiles(install)
        self.assertEqual([row['profile_dir'] for row in result], [str(profile)])

    def test_userdata_argument_parsing(self):
        for command in ('"C:\\Apps\\Grok Bot.exe" --user-data-dir="C:\\User Space\\Profile"',
                        '"C:\\Apps\\Grok Bot.exe" --user-data-dir "C:\\User Space\\Profile"'):
            self.assertEqual(discovery._user_data_dir(command), r'C:\User Space\Profile')
        self.assertIsNone(discovery._user_data_dir('Grok.exe --other=foo'))

    def test_incomplete_install_is_ignored(self):
        install = self.root / 'incomplete'
        install.mkdir()
        (install / 'Grok Bot.exe').touch()
        with mock.patch.object(discovery, 'running_processes', return_value=[]), \
             mock.patch.object(discovery, '_registry_candidates', return_value=[(install, 'registry')]), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(discovery.discover_installations(), [])

    def test_no_matching_processes_never_calls_stop(self):
        rows = [{'ExecutablePath': str(self.root / 'different/Grok Bot.exe'), 'ProcessId': 3}]
        with mock.patch.object(discovery, 'running_processes', return_value=rows), \
             mock.patch.object(discovery.subprocess, 'run') as run:
            self.assertEqual(discovery.stop_installation(self.root / 'selected'), 0)
        run.assert_not_called()

    def test_stop_request_only_includes_matching_installation_pids(self):
        install = self.root / 'selected'
        rows = [{'ExecutablePath': str(install / 'Grok Bot.exe'), 'ProcessId': 4},
                {'ExecutablePath': str(self.root / 'different/Grok Bot.exe'), 'ProcessId': 5}]
        with mock.patch.object(discovery, 'running_processes', side_effect=[rows, [rows[1]]]), \
             mock.patch.object(discovery.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(discovery.stop_installation(install), 1)
        import json
        request = json.loads(run.call_args.kwargs['input'])
        self.assertEqual(request['pids'], [4])
        self.assertEqual(request['exe'], str(install / 'Grok Bot.exe'))

    def test_restarted_selected_process_blocks_replacement(self):
        install = self.root / 'selected'
        row = {'ExecutablePath': str(install / 'Grok Bot.exe'), 'ProcessId': 4}
        with mock.patch.object(discovery, 'running_processes', return_value=[row]), \
             mock.patch.object(discovery.subprocess, 'run', return_value=mock.Mock(returncode=0)), \
             self.assertRaises(OSError):
            discovery.stop_installation(install)


if __name__ == '__main__':
    unittest.main()
