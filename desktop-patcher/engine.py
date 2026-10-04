"""Transactional, profile-scoped desktop patching for an exact 0.66.0 source.

The API never downloads files, reads credentials, or launches the application.
Dry runs build and parse the candidate in memory and never create state files.
"""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import discovery

HELPERS = (Path(sys._MEIPASS) / 'resources/client-066' if getattr(sys, 'frozen', False)
           else Path(__file__).resolve().parent.parent / 'experimental/client-066')
if str(HELPERS) not in sys.path:
    sys.path.insert(0, str(HELPERS))
import asar
import patch_routing
import stage_client
import verify_client

SUPPORTED_VERSION = '0.66.0'
HOST_VERSION = '1494ebd'
SCOPE_NAME = 'grok-switch-local-agents.json'
UUID4 = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


class PatcherError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_scope(value):
    if not isinstance(value, dict):
        try:
            path = Path(value)
        except TypeError as error:
            raise PatcherError('invalid_scope', 'Supply a scope JSON object or file.') from error
        _regular(path)
        if path.stat().st_size > 32768:
            raise PatcherError('invalid_scope', 'Scope JSON exceeds 32 KiB.')
        try:
            value = _json_bytes(path.read_bytes())
        except (ValueError, UnicodeError) as error:
            raise PatcherError('invalid_scope', 'Scope JSON is invalid.') from error
    if (not isinstance(value, dict) or set(value) != {'version', 'hostVersion', 'agentIds'}
            or type(value.get('version')) is not int or value['version'] != 1
            or value.get('hostVersion') != HOST_VERSION or not isinstance(value.get('agentIds'), list)
            or not 1 <= len(value['agentIds']) <= 16
            or not all(isinstance(item, str) and UUID4.fullmatch(item) for item in value['agentIds'])
            or len(set(value['agentIds'])) != len(value['agentIds'])):
        raise PatcherError('invalid_scope', 'Scope must contain version 1, hostVersion 1494ebd and 1–16 unique lowercase UUIDv4 agent IDs, with no extra fields.')
    return copy.deepcopy(value)


def _json_bytes(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique)


def _regular(path, missing=False):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        if missing:
            return
        raise FileNotFoundError(str(path))
    info = path.lstat()
    if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise PatcherError('unsafe_path', 'Symbolic links and reparse points are not accepted: ' + str(path))
    if not path.is_file():
        raise PatcherError('unsafe_path', 'Expected a regular file: ' + str(path))


def _directory(path):
    if not path.is_dir():
        raise PatcherError('missing_directory', 'Directory does not exist: ' + str(path))
    # Check ancestors too: an elevated copy must not traverse a profile junction.
    for parent in [path, *path.parents]:
        if parent.is_symlink() or getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400:
            raise PatcherError('unsafe_path', 'Directory contains a reparse point: ' + str(parent))


def _atomic_replace(path, content):
    """Same-directory replacement; no partially-written destination is exposed."""
    _directory(path.parent)
    _regular(path, missing=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    _directory(path.parent)
    _regular(path, missing=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise PatcherError('busy', 'Another patch or restore is in progress for this installation.') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Patcher:
    def __init__(self, install_dir, profile_dir, node_path, state_root=None, progress=None):
        self.install = Path(install_dir).absolute()
        self.profile = Path(profile_dir).absolute()
        self.node = Path(node_path).absolute() if node_path else None
        if state_root is None:
            if not os.environ.get('LOCALAPPDATA'):
                raise PatcherError('state_root_required', 'LOCALAPPDATA is unavailable; specify a local state directory.')
            state_root = Path(os.environ['LOCALAPPDATA']) / 'GrokSwitchPatcher'
        self.state_root = Path(state_root).absolute()
        key = _digest(discovery.path_key(self.install).encode())[:24]
        self.base = self.state_root / 'backups' / key
        self.state_file = self.base / 'state.json'
        self.archive = self.install / 'resources/app.asar'
        self.exe = self.install / 'Grok Bot.exe'
        self.scope_path = self.profile / SCOPE_NAME
        self.progress = progress or (lambda stage, message: None)

    def _say(self, stage, message):
        self.progress(stage, message)

    def _pair(self, root=None):
        root = Path(root) if root else self.install
        _directory(root)
        _directory(root / 'resources')
        archive, exe = root / 'resources/app.asar', root / 'Grok Bot.exe'
        _regular(archive)
        _regular(exe)
        raw = archive.read_bytes()
        _, header, start, header_hash = asar.load_archive_bytes(raw)
        problems = asar.archive_problems(raw, header, start, require_integrity=True)
        if problems:
            raise PatcherError('invalid_archive', 'ASAR integrity failed: ' + '; '.join(problems[:5]))
        binary = exe.read_bytes()
        if binary.count(asar.embedded_record(header_hash)) != 1:
            raise PatcherError('invalid_pair', 'The EXE must contain its ASAR header hash exactly once.')
        return {'raw': raw, 'binary': binary, 'header': header, 'start': start,
                'header_hash': header_hash, 'version': asar.version_of(raw, header, start),
                'hashes': {'asar': _digest(raw), 'exe': _digest(binary)}}

    def _state(self):
        if not self.state_file.exists():
            return None
        _directory(self.base)
        _regular(self.state_file)
        try:
            state = _json_bytes(self.state_file.read_bytes())
            if (not isinstance(state, dict) or type(state.get('version')) is not int or state.get('version') != 1
                    or state.get('install_key') != discovery.path_key(self.install)
                    or not isinstance(state.get('backup_id'), str)
                    or not re.fullmatch(r'[0-9a-f]{32}', state['backup_id'])
                    or state.get('phase') not in ('prepared', 'applying', 'active', 'restoring', 'restored', 'rolled_back', 'rollback_failed')
                    or not isinstance(state.get('profile_key'), str)
                    or type(state.get('scope_original_exists')) is not bool):
                raise ValueError('Invalid state identity')
            for name in ('original_hashes', 'patched_hashes'):
                value = state.get(name)
                if (not isinstance(value, dict) or set(value) != {'asar', 'exe'}
                        or not all(isinstance(item, str) and re.fullmatch(r'[0-9a-f]{64}', item) for item in value.values())):
                    raise ValueError('Invalid state hashes')
            for name in ('scope_original_sha256', 'scope_patched_sha256'):
                value = state.get(name)
                if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)):
                    raise ValueError('Invalid scope hashes')
            if state['scope_original_exists'] != (state.get('scope_original_sha256') is not None):
                raise ValueError('Invalid scope presence')
            return state
        except (ValueError, TypeError, AttributeError) as error:
            raise PatcherError('invalid_state', 'Managed backup state is invalid; no installation files were changed.') from error

    def _write_state(self, state):
        _atomic_replace(self.state_file, json.dumps(state, ensure_ascii=False, indent=2).encode('utf8'))

    def _scope_bytes(self):
        _directory(self.profile)
        _regular(self.scope_path, missing=True)
        return self.scope_path.read_bytes() if self.scope_path.exists() else None

    def _assert_profile(self, state):
        if state['profile_key'] != discovery.path_key(self.profile):
            raise PatcherError('profile_mismatch', 'This managed snapshot belongs to another Grok profile. Select the original profile before changing or restoring it.')

    def _syntax(self, payloads):
        if self.node is None or not self.node.is_file():
            raise PatcherError('node_missing', 'A bundled or explicitly selected Node.js executable is required.')
        for path in stage_client.PATCHERS:
            environment = dict(os.environ)
            environment.pop('NODE_OPTIONS', None)
            environment.pop('NODE_PATH', None)
            result = subprocess.run([str(self.node), '--check', '-'], input=payloads[path],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                                    env=environment,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                # Do not echo vendor payloads or Node source excerpts into GUI logs.
                raise PatcherError('syntax_failed', 'Node.js syntax validation failed for ' + path)

    def _candidate(self, source):
        if source['version'] != SUPPORTED_VERSION:
            raise PatcherError('unsupported_version', 'Only Grok Bot 0.66.0 is supported by this patch.')
        entries = dict(asar.walk(source['header']))
        payloads = {path: asar.payload_of(source['raw'], source['start'], item)
                    for path, item in entries.items() if 'offset' in item}
        for path, transform in stage_client.PATCHERS.items():
            try:
                payloads[path] = transform(payloads[path].decode('utf8')).encode('utf8')
            except (KeyError, ValueError, UnicodeError) as error:
                raise PatcherError('unknown_shape', 'The 0.66.0 routing source is changed or already patched; exact original shapes are required.') from error
        self._syntax(payloads)
        raw = asar.encode_archive(copy.deepcopy(source['header']), payloads)
        _, header, start, new_hash = asar.load_archive_bytes(raw)
        if asar.archive_problems(raw, header, start, require_integrity=True):
            raise PatcherError('candidate_invalid', 'Generated ASAR failed full integrity validation.')
        entries_new = dict(asar.walk(header))
        changed = [name for name in payloads if asar.payload_of(source['raw'], source['start'], entries[name]) != payloads[name]]
        if set(changed) != set(stage_client.PATCHERS):
            raise PatcherError('candidate_invalid', 'Generated ASAR changed unexpected payloads.')
        for name, payload in payloads.items():
            if asar.payload_of(raw, start, entries_new[name]) != payload:
                raise PatcherError('candidate_invalid', 'Generated ASAR payload mismatch.')
        old_record, new_record = asar.embedded_record(source['header_hash']), asar.embedded_record(new_hash)
        binary = source['binary'].replace(old_record, new_record, 1)
        if binary.count(new_record) != 1 or binary.count(old_record):
            raise PatcherError('candidate_invalid', 'Generated EXE integrity record is ambiguous.')
        manifest = {'clientVersion': SUPPORTED_VERSION, 'patchVersion': patch_routing.RESTART_MARK,
                    'changed': sorted(changed), 'originalHeaderHash': source['header_hash'],
                    'stagedHeaderHash': new_hash, 'originalArchiveSha256': source['hashes']['asar'],
                    'archiveSha256': _digest(raw), 'originalExeSha256': source['hashes']['exe'],
                    'stagedExeSha256': _digest(binary), 'embeddedIntegrityUpdated': True, 'electronFusesChanged': False}
        return {'raw': raw, 'binary': binary, 'manifest': manifest,
                'hashes': {'asar': _digest(raw), 'exe': _digest(binary)}}

    def inspect(self):
        result = {'status': 'unknown', 'client_version': None, 'install_dir': str(self.install),
                  'profile_dir': str(self.profile), 'reason': ''}
        try:
            source = self._pair()
            result['client_version'] = source['version']
            if source['version'] != SUPPORTED_VERSION:
                return dict(result, status='unsupported', code='unsupported_version', reason='Only client 0.66.0 is supported; do not restore a backup over a vendor update.')
            state = self._state()
            if state:
                result['backup_id'] = state['backup_id']
                result['backup_dir'] = str(self.base / state['backup_id'])
                if (state['phase'] in ('applying', 'restoring', 'rollback_failed')
                        or (state['phase'] == 'prepared' and source['hashes'] == state['patched_hashes'])):
                    return dict(result, code='interrupted', reason='An interrupted operation is recorded. Restore can recover only recorded original/patched file hashes.')
                if source['hashes'] == state['patched_hashes'] and state['phase'] == 'active':
                    self._assert_profile(state)
                    return dict(result, status='ours', code='managed_patch', scope=state.get('scope'),
                                reason='This exact installed pair matches the managed patch and snapshot.')
            entries = dict(asar.walk(source['header']))
            for name, transform in stage_client.PATCHERS.items():
                transform(asar.payload_of(source['raw'], source['start'], entries[name]).decode('utf8'))
            return dict(result, status='original', code='supported_original', reason='The ASAR/EXE pair is consistent and has the exact supported original routing shapes.')
        except FileNotFoundError:
            return dict(result, status='missing', code='missing_files', reason='The selected installation is incomplete or missing.')
        except (ValueError, KeyError, UnicodeError):
            return dict(result, code='unmanaged_patch', reason='This client is modified or contains a routing patch without a matching managed snapshot. Import a verified original staging snapshot if available.')
        except PatcherError as error:
            return dict(result, code=error.code, reason=str(error))

    def _snapshot(self, source, candidate, old_scope, scope, imported=False):
        backup_id = uuid.uuid4().hex
        folder = self.base / backup_id
        (folder / 'original/resources').mkdir(parents=True, exist_ok=False)
        files = {'original/resources/app.asar': source['raw'], 'original/Grok Bot.exe': source['binary'],
                 'app.asar': candidate['raw'], 'Grok Bot.exe': candidate['binary'],
                 'manifest.json': json.dumps(candidate['manifest'], indent=2).encode('utf8')}
        if old_scope is not None:
            files['scope-original.bin'] = old_scope
        for name, data in files.items():
            with (folder / name).open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        verification = verify_client.verify(folder / 'original', folder, check_syntax=False)
        if not verification['healthy']:
            raise PatcherError('backup_invalid', 'Snapshot verification failed; the application has not been changed.')
        state = {'version': 1, 'backup_id': backup_id, 'install_key': discovery.path_key(self.install),
                 'profile_key': discovery.path_key(self.profile), 'profile_dir': str(self.profile),
                 'created_utc': datetime.now(timezone.utc).isoformat(), 'phase': 'prepared',
                 'original_hashes': source['hashes'], 'patched_hashes': candidate['hashes'],
                 'scope_original_exists': old_scope is not None,
                 'scope_original_sha256': _digest(old_scope) if old_scope is not None else None,
                 'scope': scope, 'imported': imported}
        self._write_state(state)
        return state

    def _ensure_current(self, expected_hashes, expected_scope):
        if self._pair()['hashes'] != expected_hashes or self._scope_bytes() != expected_scope:
            raise PatcherError('source_changed', 'Installation or scope changed after validation. No replacement was attempted.')

    def _preflight_write_access(self):
        """Catch ordinary UAC failures before closing Grok; not a promise against ACL races."""
        self._say('permissions', 'Checking directory write access before closing Grok Bot.')
        for target in (self.archive, self.exe, self.scope_path):
            _regular(target, missing=True)
            if target.exists() and getattr(target.stat(), 'st_file_attributes', 0) & 1:
                raise PermissionError('A selected target file is read-only: ' + str(target))
        parents = {target.parent for target in (self.archive, self.exe, self.scope_path)}
        for parent in sorted(parents):
            _directory(parent)
            probe = parent / ('.GrokSwitchPatcher.' + uuid.uuid4().hex + '.write-probe')
            try:
                with probe.open('xb'):
                    pass
            finally:
                probe.unlink(missing_ok=True)

    def _transaction(self, state, replacements, before, phase, success_phase):
        changed = []
        previous_phase = state['phase']
        state['phase'] = phase
        self._write_state(state)
        try:
            for path, content in replacements:
                if content is None:
                    _directory(path.parent)
                    _regular(path, missing=True)
                    path.unlink(missing_ok=True)
                else:
                    _atomic_replace(path, content)
                changed.append(path)
            for path, content in replacements:
                if (content is None and path.exists()) or (content is not None and path.read_bytes() != content):
                    raise PatcherError('write_verification_failed', 'A replaced file failed verification before transaction commit.')
            state['phase'] = success_phase
            self._write_state(state)
        except BaseException as error:
            failures = []
            for path in reversed(changed):
                try:
                    if before[path] is None:
                        path.unlink(missing_ok=True)
                    else:
                        _atomic_replace(path, before[path])
                except BaseException:
                    failures.append(str(path))
            state['phase'] = 'rollback_failed' if failures else (previous_phase if phase == 'restoring' else 'rolled_back')
            try:
                self._write_state(state)
            except BaseException:
                failures.append('state journal')
            if failures:
                raise PatcherError('rollback_failed', 'Replacement failed and automatic rollback needs recovery. Preserve the backup; use Restore before launching Grok Bot.') from error
            if isinstance(error, PermissionError):
                raise
            raise PatcherError('transaction_failed', 'Replacement failed; all completed file replacements were rolled back.') from error

    def patch(self, scope, dry_run=False):
        scope = validate_scope(scope)
        if dry_run:
            return self._patch(scope, True)
        with _lock(self.base / 'operation.lock'):
            return self._patch(scope, False)

    def _patch(self, scope, dry_run):
        self._say('preflight', 'Checking the selected installation, source integrity, and profile scope.')
        old_scope = self._scope_bytes()
        report = self.inspect()
        if report['status'] == 'ours':
            state = self._state()
            desired = json.dumps(scope, indent=2).encode('utf8') + b'\n'
            if old_scope == desired:
                return dict(report, changed=False, dry_run=dry_run, stopped_processes=0)
            raise PatcherError('already_patched', 'This installation is already patched. Restore before applying a different scope so the original profile snapshot remains unambiguous.')
        if report['status'] != 'original':
            raise PatcherError(report.get('code', 'unsupported_source'), report['reason'])
        source = self._pair()
        self._say('candidate', 'Building and parsing the exact routing-only candidate in memory.')
        candidate = self._candidate(source)
        if dry_run:
            return dict(report, would_patch=True, dry_run=True, changed=False, scope=scope, stopped_processes=0)
        self._preflight_write_access()
        self._say('backup', 'Writing and verifying the original pair and exact profile configuration backup.')
        state = self._snapshot(source, candidate, old_scope, scope)
        self._ensure_current(source['hashes'], old_scope)
        self._say('stop', 'Closing only Grok Bot processes from the selected installation.')
        stopped = discovery.stop_installation(self.install)
        self._ensure_current(source['hashes'], old_scope)
        content = json.dumps(scope, indent=2).encode('utf8') + b'\n'
        state['scope_patched_sha256'] = _digest(content)
        self._say('replace', 'Replacing the verified ASAR, EXE hash record, and explicit profile scope.')
        self._transaction(state, [(self.archive, candidate['raw']), (self.exe, candidate['binary']), (self.scope_path, content)],
                          {self.archive: source['raw'], self.exe: source['binary'], self.scope_path: old_scope}, 'applying', 'active')
        self._say('complete', 'Patch completed. Restart Grok Bot to load the explicit local scope.')
        return dict(self.inspect(), changed=True, dry_run=False, stopped_processes=stopped)

    def _restore_material(self, state):
        self._assert_profile(state)
        folder = self.base / state['backup_id']
        _directory(folder)
        for filename in ('app.asar', 'Grok Bot.exe', 'manifest.json'):
            _regular(folder / filename)
        source = self._pair(folder / 'original')
        verified = verify_client.verify(folder / 'original', folder, check_syntax=False)
        if not verified['healthy'] or source['hashes'] != state['original_hashes']:
            raise PatcherError('backup_invalid', 'The original snapshot or candidate was modified; restoration is refused.')
        if {'asar': _digest((folder / 'app.asar').read_bytes()), 'exe': _digest((folder / 'Grok Bot.exe').read_bytes())} != state['patched_hashes']:
            raise PatcherError('backup_invalid', 'The recorded patched hashes do not match the snapshot.')
        old_scope = None
        if state['scope_original_exists']:
            _regular(folder / 'scope-original.bin')
            old_scope = (folder / 'scope-original.bin').read_bytes()
            if _digest(old_scope) != state['scope_original_sha256']:
                raise PatcherError('backup_invalid', 'The saved original profile scope is modified.')
        return source, old_scope

    def restore(self, dry_run=False):
        if dry_run:
            return self._restore(True)
        with _lock(self.base / 'operation.lock'):
            return self._restore(False)

    def _restore(self, dry_run):
        self._say('preflight', 'Verifying the managed snapshot and current file hashes before restore.')
        state = self._state()
        if not state:
            raise PatcherError('no_backup', 'No managed snapshot exists for this installation. Import a verified staging snapshot first.')
        source, original_scope = self._restore_material(state)
        current_scope = self._scope_bytes()
        _directory(self.install)
        _directory(self.install / 'resources')
        _regular(self.archive)
        _regular(self.exe)
        current_raw, current_binary = self.archive.read_bytes(), self.exe.read_bytes()
        hashes = {'asar': _digest(current_raw), 'exe': _digest(current_binary)}
        interrupted = state['phase'] in ('prepared', 'applying', 'restoring', 'rollback_failed')
        if interrupted:
            if not all(hashes[name] in (state['original_hashes'][name], state['patched_hashes'][name]) for name in hashes):
                raise PatcherError('stale_backup', 'Current files are outside the recorded transaction; restoration could overwrite an update and is refused.')
        elif hashes != state['patched_hashes'] or state['phase'] != 'active':
            raise PatcherError('stale_backup', 'Current files no longer match this managed patch. A vendor update or external change must not be overwritten by an old backup.')
        allowed_scopes = {state.get('scope_patched_sha256'), state['scope_original_sha256']}
        if (_digest(current_scope) if current_scope is not None else None) not in allowed_scopes:
            raise PatcherError('scope_changed', 'The profile scope was modified after patching. Preserve that file and resolve the change before restoring.')
        if dry_run:
            return {'status': 'ours' if not interrupted else 'unknown', 'would_restore': True, 'dry_run': True,
                    'changed': False, 'backup_id': state['backup_id'], 'stopped_processes': 0}
        self._preflight_write_access()
        self._say('stop', 'Closing only Grok Bot processes from the selected installation.')
        stopped = discovery.stop_installation(self.install)
        if (_digest(self.archive.read_bytes()) != hashes['asar'] or _digest(self.exe.read_bytes()) != hashes['exe']
                or self._scope_bytes() != current_scope):
            raise PatcherError('source_changed', 'Installation or scope changed while closing Grok Bot; restore was not attempted.')
        self._say('restore', 'Restoring the exact original files and original profile configuration.')
        self._transaction(state, [(self.archive, source['raw']), (self.exe, source['binary']), (self.scope_path, original_scope)],
                          {self.archive: current_raw, self.exe: current_binary, self.scope_path: current_scope}, 'restoring', 'restored')
        self._say('complete', 'Original client and profile configuration restored. Restart Grok Bot when ready.')
        return dict(self.inspect(), changed=True, dry_run=False, stopped_processes=stopped)

    def import_snapshot(self, snapshot_dir, dry_run=False):
        if dry_run:
            return self._import_snapshot(snapshot_dir, True)
        with _lock(self.base / 'operation.lock'):
            return self._import_snapshot(snapshot_dir, False)

    def _import_snapshot(self, snapshot_dir, dry_run):
        existing = self._state()
        if existing and existing['phase'] not in ('restored', 'rolled_back'):
            raise PatcherError('existing_snapshot', 'This installation already has a managed or interrupted snapshot.')
        snapshot = Path(snapshot_dir).absolute()
        _directory(snapshot)
        for filename in ('app.asar', 'Grok Bot.exe', 'manifest.json'):
            _regular(snapshot / filename)
        source = self._pair(snapshot / 'original')
        candidate = self._candidate(source)
        if ((snapshot / 'app.asar').read_bytes() != candidate['raw']
                or (snapshot / 'Grok Bot.exe').read_bytes() != candidate['binary']
                or _json_bytes((snapshot / 'manifest.json').read_bytes()) != candidate['manifest']):
            raise PatcherError('backup_invalid', 'Legacy snapshot is not the exact supported transform of its original pair.')
        if self._pair()['hashes'] != candidate['hashes']:
            raise PatcherError('stale_backup', 'Installed files do not match this legacy snapshot.')
        current_scope = self._scope_bytes()
        scope = validate_scope(_json_bytes(current_scope)) if current_scope is not None else None
        warning = 'Imported snapshot: historical pre-patch scope is unavailable; Restore will preserve the scope present at import.'
        if dry_run:
            return {'status': 'unknown', 'would_import': True, 'dry_run': True, 'changed': False, 'warning': warning}
        state = self._snapshot(source, candidate, current_scope, scope, imported=True)
        state['scope_patched_sha256'] = _digest(current_scope) if current_scope is not None else None
        state['phase'] = 'active'
        self._write_state(state)
        return dict(self.inspect(), changed=True, dry_run=False, warning=warning)
