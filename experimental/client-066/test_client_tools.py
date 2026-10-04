"""Synthetic safety tests; never read an installed client or real profile.

Run with ``python -m unittest discover -s experimental/client-066 -p test_*.py``.
Fixture routing anchors are deliberately not a runnable vendor application.
The explicit check_syntax=False option is used only for those synthetic pairs.
"""
import copy
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import asar
import patch_routing as patch
import stage_client
import verify_client
import rollback_client

MAIN = 'dist/electron-main/main-app.cjs'
COORDINATOR = 'dist/node-agent-coordinator/main.cjs'
UNCHANGED = 'assets/untouched.txt'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def original_sources():
    return {
        MAIN: ('/* synthetic before */\n' + patch.MAIN_ANCHOR + '\n/* synthetic after */').encode(),
        COORDINATOR: ('\n'.join(before for before, _ in patch.COORDINATOR_REPLACEMENTS)).encode(),
    }


def fixture_bytes(version='0.66.0', payload_overrides=None):
    """Build the input independently of production encode_archive."""
    payloads = {
        'package.json': json.dumps({'name': 'synthetic-test-client', 'version': version}).encode(),
        **original_sources(),
        UNCHANGED: b'preserve this unrelated payload\n',
        'assets/empty.txt': b'',
    }
    payloads.update(payload_overrides or {})
    header = {'files': {}, 'syntheticMetadata': {'preserve': True}}
    body = bytearray()
    for name, data in payloads.items():
        tree = header
        pieces = name.split('/')
        for piece in pieces[:-1]:
            tree = tree['files'].setdefault(piece, {'files': {}, 'fixtureDirectoryMetadata': True})
        tree['files'][pieces[-1]] = {
            'offset': str(len(body)), 'size': len(data), 'executable': name == MAIN,
            'integrity': {'algorithm': 'SHA256', 'hash': digest(data), 'blockSize': 31,
                          'blocks': [digest(data[i:i + 31]) for i in range(0, len(data), 31)]},
        }
        body.extend(data)
    header['files']['native.node'] = {'size': 9, 'unpacked': True}
    header['files']['alias.txt'] = {'link': UNCHANGED}
    encoded = json.dumps(header, separators=(',', ':')).encode()
    string_pickle = struct.pack('<I', len(encoded)) + encoded
    string_pickle += b'\0' * (-len(string_pickle) % 4)
    header_pickle = struct.pack('<I', len(string_pickle)) + string_pickle
    return struct.pack('<II', 4, len(header_pickle)) + header_pickle + body


def rewrite_archive(file, payload_change=None, metadata_change=None):
    raw, header, start, _ = asar.load_archive(file)
    payloads = {name: asar.payload_of(raw, start, item) for name, item in asar.walk(header)
                if 'offset' in item}
    if payload_change:
        payload_change(payloads)
    if metadata_change:
        metadata_change(header)
    file.write_bytes(asar.encode_archive(header, payloads))


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gs066-client-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / 'synthetic-install'
        (self.install / 'resources').mkdir(parents=True)
        self.archive = self.install / 'resources' / 'app.asar'
        self.exe = self.install / 'Grok Bot.exe'
        self.output = self.root / 'candidate'
        self.make_source()

    def make_source(self, version='0.66.0', payload_overrides=None):
        self.archive.write_bytes(fixture_bytes(version, payload_overrides))
        _, _, _, header_hash = asar.load_archive(self.archive)
        self.exe.write_bytes(b'MZ\0synthetic-test-not-executable\0' + asar.embedded_record(header_hash)
                             + b'\0preserve-synthetic-fuse-bytes:00110100\0')

    def stage(self):
        return stage_client.stage(self.install, self.output, check_syntax=False)

    def verify(self):
        return verify_client.verify(self.install, self.output, check_syntax=False)


class PatchTests(unittest.TestCase):
    def test_main_transform_and_repatch_refusal(self):
        source = original_sources()[MAIN].decode()
        result = patch.patch_client_routing_profile(source)
        self.assertEqual(result, source.replace(patch.MAIN_ANCHOR, patch.MAIN_PATCHED))
        with self.assertRaises(ValueError):
            patch.patch_client_routing_profile(result)

    def test_main_missing_and_duplicate_anchors_fail_closed(self):
        for source in ('no matching client shape', patch.MAIN_ANCHOR * 2):
            with self.subTest(source=source[:40]), self.assertRaises(ValueError):
                patch.patch_client_routing_profile(source)

    def test_every_coordinator_anchor_is_required_and_unique(self):
        original = original_sources()[COORDINATOR].decode()
        for anchor, _ in patch.COORDINATOR_REPLACEMENTS:
            for broken in (original.replace(anchor, ''), original + '\n' + anchor):
                with self.subTest(anchor=anchor[:50]), self.assertRaises(ValueError):
                    patch.patch_coordinator(broken)

    def test_coordinator_replacements_and_repatch_refusal(self):
        source = original_sources()[COORDINATOR].decode()
        result = patch.patch_coordinator(source)
        self.assertEqual(result.count(patch.RESTART_MARK), 1)
        self.assertEqual(result.count('function __gs066ReadAllowlist('), 1)
        for _, replacement in patch.COORDINATOR_REPLACEMENTS:
            self.assertIn(replacement, result)
        with self.assertRaises(ValueError):
            patch.patch_coordinator(result)

    def test_existing_patch_markers_are_rejected_even_with_valid_anchors(self):
        for marker in (patch.PROFILE_FIELD, patch.RESTART_MARK, '__gs066'):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                patch.patch_coordinator(original_sources()[COORDINATOR].decode() + marker)


class ArchiveTests(FixtureTest):
    def test_roundtrip_preserves_entries_metadata_and_integrity(self):
        raw, header, start, _ = asar.load_archive(self.archive)
        self.assertEqual(asar.archive_problems(raw, header, start, require_integrity=True), [])
        staged = self.root / 'roundtrip.asar'
        staged.write_bytes(raw)
        rewrite_archive(staged)
        report = asar.compare_archives(self.archive, staged)
        self.assertEqual(report['integrityProblems'], [])
        self.assertEqual(report['changed'], [])
        self.assertEqual(report['entries'], 5)

    def test_raw_payload_tamper_is_detected_by_hash_and_blocks(self):
        raw, header, start, _ = asar.load_archive(self.archive)
        entries = dict(asar.walk(header))
        offset = start + int(entries[UNCHANGED]['offset'])
        tampered = bytearray(raw)
        tampered[offset] ^= 1
        problems = asar.archive_problems(bytes(tampered), header, start, require_integrity=True)
        self.assertTrue(any('integrity hash mismatch' in issue for issue in problems))
        self.assertTrue(any('integrity block mismatch' in issue for issue in problems))

    def test_rehashed_unexpected_payload_change_is_rejected(self):
        staged = self.root / 'unexpected.asar'
        staged.write_bytes(self.archive.read_bytes())
        rewrite_archive(staged, payload_change=lambda data: data.update({UNCHANGED: b'changed'}))
        problems = asar.compare_archives(self.archive, staged)['integrityProblems']
        self.assertIn(UNCHANGED + ': unexpected payload change', problems)

    def test_allowed_target_cannot_change_unrelated_metadata(self):
        staged = self.root / 'metadata.asar'
        staged.write_bytes(self.archive.read_bytes())
        rewrite_archive(staged, metadata_change=lambda tree:
                        dict(asar.walk(tree))[MAIN].update({'executable': False}))
        problems = asar.compare_archives(self.archive, staged)['integrityProblems']
        self.assertIn(MAIN + ': unexpected entry metadata change', problems)

    def test_block_size_changes_rejected_even_with_recomputed_hashes(self):
        staged = self.root / 'block-size.asar'
        staged.write_bytes(self.archive.read_bytes())
        rewrite_archive(staged, metadata_change=lambda tree:
                        dict(asar.walk(tree))[COORDINATOR]['integrity'].update({'blockSize': 17}))
        self.assertIn(COORDINATOR + ': changed integrity blockSize',
                      asar.compare_archives(self.archive, staged)['integrityProblems'])

    def test_top_level_and_directory_metadata_changes_are_rejected(self):
        for target in ('top', 'directory'):
            with self.subTest(target=target):
                staged = self.root / (target + '.asar')
                staged.write_bytes(self.archive.read_bytes())
                def mutate(tree):
                    if target == 'top':
                        tree['syntheticMetadata']['preserve'] = False
                    else:
                        tree['files']['assets']['fixtureDirectoryMetadata'] = False
                rewrite_archive(staged, metadata_change=mutate)
                self.assertIn('unexpected archive tree metadata change',
                              asar.compare_archives(self.archive, staged)['integrityProblems'])

    def test_out_of_bounds_overlapping_and_missing_integrity_are_rejected(self):
        raw, header, start, _ = asar.load_archive(self.archive)
        for case in ('bounds', 'overlap', 'integrity'):
            tree = copy.deepcopy(header)
            entries = dict(asar.walk(tree))
            if case == 'bounds':
                entries[UNCHANGED]['size'] = len(raw)
            elif case == 'overlap':
                entries[UNCHANGED]['offset'] = '0'
            else:
                entries[UNCHANGED].pop('integrity')
            with self.subTest(case=case):
                problems = asar.archive_problems(raw, tree, start, require_integrity=True)
                self.assertTrue(problems)
                expected = {'bounds': 'outside archive bounds', 'overlap': 'overlapping packed payload',
                            'integrity': 'missing integrity metadata'}[case]
                self.assertTrue(any(expected in issue for issue in problems), problems)

    def test_malformed_header_and_duplicate_metadata_fail_closed(self):
        for raw in (b'', b'\0' * 15, struct.pack('<4I', 5, 8, 4, 0),
                    struct.pack('<4I', 4, 9, 5, 1) + b'{}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                asar.load_archive_bytes(raw)
        duplicate = b'{"files":{},"files":{}}'
        payload = struct.pack('<I', len(duplicate)) + duplicate
        payload += b'\0' * (-len(payload) % 4)
        hp = struct.pack('<I', len(payload)) + payload
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            asar.load_archive_bytes(struct.pack('<II', 4, len(hp)) + hp)


class StagingTests(FixtureTest):
    def test_supported_version_is_066(self):
        self.assertEqual(stage_client.SUPPORTED_VERSION, '0.66.0')

    def test_valid_pair_snapshot_and_exact_exe_replacement(self):
        original_archive = self.archive.read_bytes()
        original_exe = self.exe.read_bytes()
        manifest = self.stage()
        report = self.verify()
        self.assertTrue(report['healthy'], report)
        self.assertTrue(report['exeRecordOk'])
        self.assertEqual(manifest['changed'], sorted([MAIN, COORDINATOR]))
        self.assertEqual(self.archive.read_bytes(), original_archive)
        self.assertEqual(self.exe.read_bytes(), original_exe)
        self.assertEqual((self.output / 'original/resources/app.asar').read_bytes(), original_archive)
        self.assertEqual((self.output / 'original/Grok Bot.exe').read_bytes(), original_exe)
        self.assertEqual((self.output / 'Grok Bot.exe').read_bytes(), original_exe.replace(
            asar.embedded_record(manifest['originalHeaderHash']),
            asar.embedded_record(manifest['stagedHeaderHash']), 1))

    def test_unsupported_version_rejected_without_output(self):
        for version in ('0.57.1', '0.66.1', '0.67.0', None):
            with self.subTest(version=version):
                self.make_source(version=version)
                with self.assertRaises(ValueError):
                    self.stage()
                self.assertFalse(self.output.exists())

    def test_inside_installation_and_existing_output_refused(self):
        for output in (self.install, self.install / 'candidate'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                stage_client.stage(self.install, output, check_syntax=False)
        self.output.mkdir()
        marker = self.output / 'keep.txt'
        marker.write_text('existing content')
        with self.assertRaises(ValueError):
            self.stage()
        self.assertEqual(marker.read_text(), 'existing content')

    def test_source_hash_record_missing_or_duplicate_rejected(self):
        _, _, _, header_hash = asar.load_archive(self.archive)
        record = asar.embedded_record(header_hash)
        for binary in (b'MZ missing hash', b'MZ' + record + record):
            with self.subTest(binary_length=len(binary)):
                self.exe.write_bytes(binary)
                with self.assertRaises(ValueError):
                    self.stage()
                self.assertFalse(self.output.exists())

    def test_corrupt_source_payload_rejected_before_creating_candidate(self):
        raw = bytearray(self.archive.read_bytes())
        raw[-1] ^= 1
        self.archive.write_bytes(raw)
        with self.assertRaises(ValueError):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_bad_anchor_rejected_before_creating_candidate(self):
        self.make_source(payload_overrides={MAIN: b'unknown future main shape'})
        with self.assertRaises(ValueError):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_stage_default_and_cli_require_syntax_check(self):
        with self.assertRaises((ValueError, RuntimeError, subprocess.CalledProcessError)):
            stage_client.stage(self.install, self.output)
        self.assertFalse(self.output.exists())
        result = subprocess.run([sys.executable, str(HERE / 'stage_client.py'),
                                 '--install-dir', str(self.install), '--output', str(self.output)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_verify_rejects_candidate_exe_extra_mutation(self):
        self.stage()
        exe = self.output / 'Grok Bot.exe'
        exe.write_bytes(exe.read_bytes() + b'UNEXPECTED')
        report = self.verify()
        self.assertFalse(report['healthy'])
        self.assertTrue(any('EXE' in issue for issue in report['integrityProblems']))

    def test_verify_rejects_manifest_change(self):
        self.stage()
        manifest_path = self.output / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['electronFusesChanged'] = True
        manifest_path.write_text(json.dumps(manifest))
        report = self.verify()
        self.assertFalse(report['healthy'])
        self.assertTrue(any('manifest' in issue for issue in report['integrityProblems']))

    def test_verify_rejects_payload_even_when_rehashed_and_exe_repaired(self):
        manifest = self.stage()
        staged = self.output / 'app.asar'
        rewrite_archive(staged, payload_change=lambda data: data.update({MAIN: data[MAIN] + b'/* unrelated */'}))
        _, _, _, new_hash = asar.load_archive(staged)
        exe = self.output / 'Grok Bot.exe'
        exe.write_bytes(exe.read_bytes().replace(asar.embedded_record(manifest['stagedHeaderHash']),
                                                asar.embedded_record(new_hash)))
        report = self.verify()
        self.assertFalse(report['healthy'])
        self.assertIn(MAIN + ': does not match the routing transform', report['integrityProblems'])

    def test_verify_detects_original_snapshot_tamper(self):
        self.stage()
        for relative in ('original/resources/app.asar', 'original/Grok Bot.exe'):
            snapshot = self.output / relative
            before = snapshot.read_bytes()
            try:
                snapshot.write_bytes(before + b'UNEXPECTED')
                with self.subTest(relative=relative):
                    report = self.verify()
                    self.assertFalse(report['healthy'], report)
                    self.assertTrue(any('stored rollback' in issue.lower()
                                        for issue in report['integrityProblems']))
            finally:
                snapshot.write_bytes(before)

    def test_verify_requires_both_original_snapshots(self):
        self.stage()
        for relative in ('original/resources/app.asar', 'original/Grok Bot.exe'):
            snapshot = self.output / relative
            before = snapshot.read_bytes()
            try:
                snapshot.unlink()
                with self.subTest(relative=relative):
                    try:
                        report = self.verify()
                    except (ValueError, FileNotFoundError):
                        pass
                    else:
                        self.assertFalse(report['healthy'], report)
            finally:
                snapshot.write_bytes(before)


class RollbackTests(FixtureTest):
    def setUp(self):
        super().setUp()
        self.restore = self.root / 'rollback-candidate'

    def install_synthetic_candidate(self):
        self.stage()
        self.archive.write_bytes((self.output / 'app.asar').read_bytes())
        self.exe.write_bytes((self.output / 'Grok Bot.exe').read_bytes())

    def rollback(self):
        return rollback_client.rollback_candidate(self.install, self.output, self.restore,
                                                  check_syntax=False)

    def test_exact_candidate_produces_original_pair_without_modifying_install(self):
        archive_before, exe_before = self.archive.read_bytes(), self.exe.read_bytes()
        self.install_synthetic_candidate()
        installed_archive, installed_exe = self.archive.read_bytes(), self.exe.read_bytes()
        report = self.rollback()
        self.assertFalse(report['installationModified'])
        self.assertEqual((self.restore / 'app.asar').read_bytes(), archive_before)
        self.assertEqual((self.restore / 'Grok Bot.exe').read_bytes(), exe_before)
        self.assertEqual(self.archive.read_bytes(), installed_archive)
        self.assertEqual(self.exe.read_bytes(), installed_exe)
        self.assertEqual(report['files']['app.asar']['restoreSha256'], digest(archive_before))
        self.assertEqual(report['files']['Grok Bot.exe']['restoreSha256'], digest(exe_before))

    def test_already_original_install_is_rejected_without_output(self):
        self.stage()
        with self.assertRaisesRegex(ValueError, 'already matches the original'):
            self.rollback()
        self.assertFalse(self.restore.exists())

    def test_current_install_drift_is_rejected_without_output(self):
        self.install_synthetic_candidate()
        for file in (self.archive, self.exe):
            before = file.read_bytes()
            try:
                file.write_bytes(before + b'synthetic drift')
                with self.subTest(file=file.name), self.assertRaisesRegex(ValueError, 'stale rollback'):
                    self.rollback()
                self.assertFalse(self.restore.exists())
            finally:
                file.write_bytes(before)

    def test_tampered_snapshot_cannot_produce_rollback(self):
        self.install_synthetic_candidate()
        original_exe = self.output / 'original/Grok Bot.exe'
        original_exe.write_bytes(original_exe.read_bytes() + b'synthetic drift')
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            self.rollback()
        self.assertFalse(self.restore.exists())

    def test_rollback_output_must_be_fresh_and_outside_both_inputs(self):
        self.install_synthetic_candidate()
        self.restore.mkdir()
        marker = self.restore / 'preserve.txt'
        marker.write_text('preserve')
        for destination in (self.install / 'rollback', self.output / 'rollback', self.restore):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                rollback_client.rollback_candidate(self.install, self.output, destination,
                                                   check_syntax=False)
        self.assertEqual(marker.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
