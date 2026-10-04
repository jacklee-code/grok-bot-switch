import os
import ctypes
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

    def short_path(self, path):
        function = ctypes.windll.kernel32.GetShortPathNameW
        function.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        function.restype = ctypes.c_uint
        buffer = ctypes.create_unicode_buffer(32768)
        size = function(str(path), buffer, len(buffer))
        self.assertGreater(size, 0, 'GetShortPathNameW must accept the existing fixture')
        self.assertLess(size, len(buffer))
        if buffer.value.casefold() == str(path).casefold():
            self.skipTest('This fixture volume has no 8.3 alias; the long-path tests still apply')
        return Path(buffer.value)

    @unittest.skipUnless(os.name == 'nt', 'Windows 8.3 alias regression')
    def test_windows_short_alias_identifies_existing_and_missing_descendants(self):
        long_root = self.root.resolve() / 'Long Path Identity Fixture'
        long_root.mkdir()
        short_root = self.short_path(long_root)
        executable = long_root / 'Grok Bot.exe'
        executable.write_bytes(b'not executable')
        self.assertEqual(discovery.path_key(short_root / 'Grok Bot.exe'), discovery.path_key(executable))
        self.assertEqual(discovery.path_key(short_root / 'not-created/install/Grok Bot.exe'),
                         discovery.path_key(long_root / 'not-created/install/Grok Bot.exe'))

    @unittest.skipUnless(os.name == 'nt', 'Windows 8.3 alias regression')
    def test_windows_short_alias_process_matches_only_same_installation(self):
        install = self.install(self.root.resolve() / 'Long Installation Directory')
        short_install = self.short_path(install)
        other = self.install(self.root / 'Other Long Installation')
        rows = [{'ExecutablePath': str(short_install / 'Grok Bot.exe'), 'ProcessId': 4},
                {'ExecutablePath': str(other / 'Grok Bot.exe'), 'ProcessId': 5}]
        with mock.patch.object(discovery, 'running_processes', side_effect=[rows, [rows[1]]]), \
             mock.patch.object(discovery.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(discovery.stop_installation(short_install), 1)
        import json
        request = json.loads(run.call_args.kwargs['input'])
        self.assertEqual(request['pids'], [4])
        self.assertEqual(request['exe'], str((install / 'Grok Bot.exe').resolve()))

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell executable identity regression')
    def test_windows_powershell_identity_recheck_accepts_short_alias(self):
        install = self.install(self.root.resolve() / 'Long PowerShell Identity Fixture')
        short_install = self.short_path(install)
        # Exercise the exact Windows PowerShell/.NET comparison used immediately
        # before Stop-Process, without querying or stopping any real process.
        import json
        command = r'''$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
if (![string]::Equals([IO.Path]::GetFullPath($request.observed), $request.exe,
                     [StringComparison]::OrdinalIgnoreCase)) { exit 7 }
'''
        result = discovery.subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            input=json.dumps({'observed': str(short_install / 'Grok Bot.exe'),
                              'exe': str(install / 'Grok Bot.exe')}),
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
            creationflags=getattr(discovery.subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)

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
        self.assertEqual(request['exe'], str((install / 'Grok Bot.exe').resolve()))

    def test_restarted_selected_process_blocks_replacement(self):
        install = self.root / 'selected'
        row = {'ExecutablePath': str(install / 'Grok Bot.exe'), 'ProcessId': 4}
        with mock.patch.object(discovery, 'running_processes', return_value=[row]), \
             mock.patch.object(discovery.subprocess, 'run', return_value=mock.Mock(returncode=0)), \
             self.assertRaises(OSError):
            discovery.stop_installation(install)


if __name__ == '__main__':
    unittest.main()
