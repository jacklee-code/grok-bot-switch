"""Synthetic transaction tests. No installed client or actual profile is read."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'experimental/client-066'))
import asar
import engine
import stage_client
from test_client_tools import fixture_bytes
REAL_SYNTAX = engine.Patcher._syntax

SCOPE = {'version': 1, 'hostVersion': '1494ebd',
         'agentIds': ['11111111-1111-4111-8111-111111111111']}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='grok-patcher-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / 'custom drive' / 'Synthetic App'
        (self.install / 'resources').mkdir(parents=True)
        self.profile = self.root / 'another user' / 'custom profile'
        self.profile.mkdir(parents=True)
        self.archive = self.install / 'resources/app.asar'
        self.exe = self.install / 'Grok Bot.exe'
        self.archive.write_bytes(fixture_bytes())
        _, _, _, header_hash = asar.load_archive(self.archive)
        self.exe.write_bytes(b'MZ synthetic not runnable\0' + asar.embedded_record(header_hash))
        self.original = (self.archive.read_bytes(), self.exe.read_bytes())
        self.state_root = self.root / 'state'
        self.patcher = engine.Patcher(self.install, self.profile, self.root / 'node.exe', self.state_root)
        syntax = mock.patch.object(engine.Patcher, '_syntax')
        self.syntax = syntax.start()
        self.addCleanup(syntax.stop)
        stop = mock.patch.object(engine.discovery, 'stop_installation', return_value=0)
        self.stop = stop.start()
        self.addCleanup(stop.stop)

    def assert_original(self):
        self.assertEqual(self.archive.read_bytes(), self.original[0])
        self.assertEqual(self.exe.read_bytes(), self.original[1])

    def test_patch_and_restore_exact_existing_configuration(self):
        before = b'{"unrelatedOriginalData": true}\r\n'
        self.patcher.scope_path.write_bytes(before)
        self.assertEqual(self.patcher.inspect()['status'], 'original')
        result = self.patcher.patch(SCOPE)
        self.assertEqual(result['status'], 'ours')
        self.assertEqual(json.loads(self.patcher.scope_path.read_bytes()), SCOPE)
        self.assertNotEqual(self.archive.read_bytes(), self.original[0])
        self.assertEqual(self.patcher.restore()['status'], 'original')
        self.assert_original()
        self.assertEqual(self.patcher.scope_path.read_bytes(), before)
        self.assertEqual(self.stop.call_count, 2)

    def test_restore_removes_previously_absent_scope(self):
        self.patcher.patch(SCOPE)
        self.patcher.restore()
        self.assertFalse(self.patcher.scope_path.exists())

    def test_dry_run_performs_no_writes_and_does_not_stop_application(self):
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*'))
        result = self.patcher.patch(SCOPE, dry_run=True)
        self.assertTrue(result['would_patch'])
        self.assertFalse(self.state_root.exists())
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*')))
        self.assert_original()
        self.stop.assert_not_called()
        self.syntax.assert_called_once()

    def test_write_probe_permission_failure_occurs_before_stop_or_snapshot(self):
        with mock.patch.object(self.patcher, '_preflight_write_access', side_effect=PermissionError('synthetic directory access')):
            with self.assertRaises(PermissionError):
                self.patcher.patch(SCOPE)
        self.stop.assert_not_called()
        self.assertFalse(self.patcher.state_file.exists())
        self.assert_original()

    def test_write_probes_leave_no_temporary_files(self):
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*'))
        self.patcher._preflight_write_access()
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*')))

    def test_dry_run_never_attempts_write_probes(self):
        with mock.patch.object(self.patcher, '_preflight_write_access', side_effect=AssertionError('should not write')):
            self.patcher.patch(SCOPE, dry_run=True)
        self.patcher.patch(SCOPE)
        with mock.patch.object(self.patcher, '_preflight_write_access', side_effect=AssertionError('should not write')):
            self.patcher.restore(dry_run=True)

    def test_bad_scope_refused_before_state_or_process_changes(self):
        variants = [dict(SCOPE, agentIds=[]), dict(SCOPE, extra=True), dict(SCOPE, version=True),
                    dict(SCOPE, hostVersion='new'), dict(SCOPE, agentIds=SCOPE['agentIds'] * 2),
                    dict(SCOPE, agentIds=['11111111-1111-1111-1111-111111111111']),
                    dict(SCOPE, agentIds=['11111111-1111-4111-8111-11111111111A'])]
        for value in variants:
            with self.subTest(value=value), self.assertRaises(engine.PatcherError) as raised:
                self.patcher.patch(value)
            self.assertEqual(raised.exception.code, 'invalid_scope')
        self.assertFalse(self.state_root.exists())
        self.stop.assert_not_called()

    def test_scope_duplicate_json_keys_refused(self):
        file = self.root / 'scope.json'
        file.write_text('{"version":1,"version":1,"hostVersion":"1494ebd","agentIds":[]}', encoding='utf8')
        with self.assertRaises(engine.PatcherError):
            engine.validate_scope(file)

    def test_version_update_is_refused_and_old_backup_not_restored(self):
        self.patcher.patch(SCOPE)
        self.archive.write_bytes(fixture_bytes(version='0.67.0'))
        _, _, _, header_hash = asar.load_archive(self.archive)
        self.exe.write_bytes(b'MZ new vendor\0' + asar.embedded_record(header_hash))
        updated = (self.archive.read_bytes(), self.exe.read_bytes())
        self.assertEqual(self.patcher.inspect()['status'], 'unsupported')
        with self.assertRaises(engine.PatcherError) as raised:
            self.patcher.restore()
        self.assertEqual(raised.exception.code, 'stale_backup')
        self.assertEqual((self.archive.read_bytes(), self.exe.read_bytes()), updated)

    def test_mixed_pair_refused_before_patch(self):
        self.exe.write_bytes(b'MZ wrong exe')
        with self.assertRaises(engine.PatcherError) as raised:
            self.patcher.patch(SCOPE)
        self.assertEqual(raised.exception.code, 'invalid_pair')
        self.stop.assert_not_called()

    def test_payload_tamper_refused(self):
        raw = bytearray(self.archive.read_bytes())
        raw[-1] ^= 1
        self.archive.write_bytes(raw)
        with self.assertRaises(engine.PatcherError) as raised:
            self.patcher.patch(SCOPE)
        self.assertEqual(raised.exception.code, 'invalid_archive')

    def test_any_replacement_failure_rolls_back_completed_files(self):
        real_replace = engine._atomic_replace
        original_scope = b'original scope bytes'
        self.patcher.scope_path.write_bytes(original_scope)
        for target in (self.archive, self.exe, self.patcher.scope_path):
            failed = []
            def fail_once(path, content):
                if path == target and not failed:
                    failed.append(True)
                    raise OSError('synthetic replacement failure')
                return real_replace(path, content)
            with self.subTest(target=target), mock.patch.object(engine, '_atomic_replace', side_effect=fail_once):
                with self.assertRaises(engine.PatcherError) as raised:
                    self.patcher.patch(SCOPE)
                self.assertEqual(raised.exception.code, 'transaction_failed')
            self.assert_original()
            self.assertEqual(self.patcher.scope_path.read_bytes(), original_scope)

    def test_permission_failure_survives_for_single_ui_elevation(self):
        real_replace = engine._atomic_replace
        def deny_exe(path, content):
            if path == self.exe:
                raise PermissionError('synthetic access denied')
            return real_replace(path, content)
        with mock.patch.object(engine, '_atomic_replace', side_effect=deny_exe), self.assertRaises(PermissionError):
            self.patcher.patch(SCOPE)
        self.assert_original()

    def test_restore_replacement_failure_keeps_working_patched_pair(self):
        self.patcher.patch(SCOPE)
        patched = (self.archive.read_bytes(), self.exe.read_bytes())
        real_replace = engine._atomic_replace
        failed = []
        def fail_once(path, content):
            if path == self.exe and not failed:
                failed.append(True)
                raise OSError('synthetic restore failure')
            return real_replace(path, content)
        with mock.patch.object(engine, '_atomic_replace', side_effect=fail_once), self.assertRaises(engine.PatcherError):
            self.patcher.restore()
        self.assertEqual((self.archive.read_bytes(), self.exe.read_bytes()), patched)
        self.assertEqual(self.patcher.inspect()['status'], 'ours')

    def test_state_commit_failure_also_rolls_back(self):
        real_write = self.patcher._write_state
        failed = []
        def fail_once(state):
            if state['phase'] == 'active' and not failed:
                failed.append(True)
                raise OSError('synthetic state failure')
            return real_write(state)
        with mock.patch.object(self.patcher, '_write_state', side_effect=fail_once), self.assertRaises(engine.PatcherError):
            self.patcher.patch(SCOPE)
        self.assert_original()
        self.assertFalse(self.patcher.scope_path.exists())

    def test_post_validation_source_change_is_refused(self):
        def mutate(_):
            self.exe.write_bytes(b'changed by another program')
            return 0
        self.stop.side_effect = mutate
        with self.assertRaises(engine.PatcherError):
            self.patcher.patch(SCOPE)
        self.assertEqual(self.archive.read_bytes(), self.original[0])
        self.assertEqual(self.exe.read_bytes(), b'changed by another program')

    def test_profile_mismatch_cannot_restore(self):
        self.patcher.patch(SCOPE)
        other = self.root / 'different-profile'
        other.mkdir()
        other_patcher = engine.Patcher(self.install, other, self.root / 'node.exe', self.state_root)
        with self.assertRaises(engine.PatcherError) as raised:
            other_patcher.restore()
        self.assertEqual(raised.exception.code, 'profile_mismatch')

    def test_changed_scope_is_not_overwritten_on_restore(self):
        self.patcher.patch(SCOPE)
        self.patcher.scope_path.write_text('manual edit', encoding='utf8')
        with self.assertRaises(engine.PatcherError) as raised:
            self.patcher.restore()
        self.assertEqual(raised.exception.code, 'scope_changed')
        self.assertEqual(self.patcher.scope_path.read_text(), 'manual edit')

    def test_legacy_snapshot_import_is_exact_and_reversible(self):
        candidate = self.root / 'legacy-candidate'
        stage_client.stage(self.install, candidate, check_syntax=False)
        self.archive.write_bytes((candidate / 'app.asar').read_bytes())
        self.exe.write_bytes((candidate / 'Grok Bot.exe').read_bytes())
        original_scope = json.dumps(SCOPE).encode()
        self.patcher.scope_path.write_bytes(original_scope)
        self.assertEqual(self.patcher.inspect()['status'], 'unknown')
        result = self.patcher.import_snapshot(candidate, dry_run=True)
        self.assertTrue(result['would_import'])
        self.assertFalse(self.state_root.exists())
        result = self.patcher.import_snapshot(candidate)
        self.assertEqual(result['status'], 'ours')
        self.assertIn('historical', result['warning'])
        self.patcher.restore()
        self.assert_original()
        self.assertEqual(self.patcher.scope_path.read_bytes(), original_scope)

    def test_corrupted_snapshot_cannot_restore(self):
        result = self.patcher.patch(SCOPE)
        file = Path(result['backup_dir']) / 'original/Grok Bot.exe'
        file.write_bytes(file.read_bytes() + b'changed')
        with self.assertRaises(engine.PatcherError):
            self.patcher.restore()

    def test_interrupted_mixed_pair_can_recover_but_unknown_bytes_cannot(self):
        self.patcher.patch(SCOPE)
        state = self.patcher._state()
        state['phase'] = 'applying'
        self.patcher._write_state(state)
        self.archive.write_bytes(self.original[0])
        self.assertEqual(self.patcher.inspect()['status'], 'unknown')
        self.patcher.restore()
        self.assert_original()
        self.patcher.patch(SCOPE)
        state = self.patcher._state()
        state['phase'] = 'applying'
        self.patcher._write_state(state)
        self.exe.write_bytes(b'unknown binary')
        with self.assertRaises(engine.PatcherError) as raised:
            self.patcher.restore()
        self.assertEqual(raised.exception.code, 'stale_backup')

    def test_operation_lock_excludes_second_writer(self):
        with engine._lock(self.patcher.base / 'operation.lock'):
            with self.assertRaises(engine.PatcherError) as raised:
                self.patcher.patch(SCOPE)
        self.assertEqual(raised.exception.code, 'busy')
        self.assert_original()

    def test_node_missing_or_parse_failure_refuses_candidate(self):
        with self.assertRaises(engine.PatcherError) as raised:
            REAL_SYNTAX(self.patcher, {})
        self.assertEqual(raised.exception.code, 'node_missing')
        self.patcher.node.write_bytes(b'not run')
        payloads = {path: b'const x = ;' for path in stage_client.PATCHERS}
        result = mock.Mock(returncode=1)
        with mock.patch.object(engine.subprocess, 'run', return_value=result) as run, \
             mock.patch.dict(engine.os.environ, {'NODE_OPTIONS': '--require sensitive.js', 'NODE_PATH': 'x'}), \
             self.assertRaises(engine.PatcherError) as raised:
            REAL_SYNTAX(self.patcher, payloads)
        self.assertEqual(raised.exception.code, 'syntax_failed')
        self.assertNotIn('NODE_OPTIONS', run.call_args.kwargs['env'])
        self.assertNotIn('NODE_PATH', run.call_args.kwargs['env'])

    def test_interrupted_restore_failure_keeps_recovery_journal(self):
        self.patcher.patch(SCOPE)
        state = self.patcher._state()
        state['phase'] = 'applying'
        self.patcher._write_state(state)
        self.archive.write_bytes(self.original[0])
        replace = engine._atomic_replace
        failed = []
        def fail_once(path, content):
            if path == self.exe and not failed:
                failed.append(True)
                raise OSError('synthetic restore interruption')
            return replace(path, content)
        with mock.patch.object(engine, '_atomic_replace', side_effect=fail_once), self.assertRaises(engine.PatcherError):
            self.patcher.restore()
        self.assertEqual(self.patcher._state()['phase'], 'applying')
        self.patcher.restore()
        self.assert_original()

    def test_invalid_state_fails_closed(self):
        self.patcher.patch(SCOPE)
        state = self.patcher._state()
        state['backup_id'] = '../../unrelated'
        self.patcher._write_state(state)
        with self.assertRaises(engine.PatcherError) as raised:
            self.patcher.restore()
        self.assertEqual(raised.exception.code, 'invalid_state')

    def test_import_activation_failure_can_restore_from_prepared_snapshot(self):
        candidate = self.root / 'legacy-candidate'
        stage_client.stage(self.install, candidate, check_syntax=False)
        self.archive.write_bytes((candidate / 'app.asar').read_bytes())
        self.exe.write_bytes((candidate / 'Grok Bot.exe').read_bytes())
        real_write = self.patcher._write_state
        def fail_active(state):
            if state['phase'] == 'active':
                raise OSError('synthetic activation failure')
            return real_write(state)
        with mock.patch.object(self.patcher, '_write_state', side_effect=fail_active), self.assertRaises(OSError):
            self.patcher.import_snapshot(candidate)
        self.assertEqual(self.patcher.inspect()['code'], 'interrupted')
        self.patcher.restore()
        self.assert_original()


if __name__ == '__main__':
    unittest.main()
