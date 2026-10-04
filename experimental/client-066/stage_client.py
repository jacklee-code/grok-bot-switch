"""Stage a fresh routing-only ASAR/EXE pair without changing an installation."""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path

from asar import (archive_problems, embedded_record, encode_archive, load_archive,
                  load_archive_bytes, payload_of, version_of, walk)
from patch_routing import patch_client_routing_profile, patch_coordinator, RESTART_MARK

SUPPORTED_VERSION = '0.66.0'
PATCHERS = {'dist/electron-main/main-app.cjs': patch_client_routing_profile,
            'dist/node-agent-coordinator/main.cjs': patch_coordinator}


def install_files(install_dir):
    install = Path(install_dir).resolve()
    return install / 'resources' / 'app.asar', install / 'Grok Bot.exe'


def syntax_check(payloads):
    """Parse the changed CJS text with Node; never evaluate application code."""
    for path in PATCHERS:
        result = subprocess.run(['node', '--check', '-'], input=payloads[path],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise ValueError(path + ': Node syntax check failed: ' + result.stderr.decode('utf8', errors='replace')[:1200])


def stage(install_dir, destination, *, check_syntax=True):
    archive, exe = install_files(install_dir)
    output = Path(destination).resolve()
    if output.is_relative_to(Path(install_dir).resolve()):
        raise ValueError('staging destination must be outside the installation')
    if output.exists():
        raise ValueError('staging destination already exists; use a fresh directory')
    raw, header, start, old_hash = load_archive(archive)
    problems = archive_problems(raw, header, start, require_integrity=True)
    if problems:
        raise ValueError('invalid source ASAR: ' + '; '.join(problems))
    version = version_of(raw, header, start)
    if version != SUPPORTED_VERSION:
        raise ValueError('unsupported client version: ' + str(version))
    entries = dict(walk(header))
    if not all(path in entries and 'offset' in entries[path] for path in PATCHERS):
        raise ValueError('missing packed routing target')
    payloads = {path: payload_of(raw, start, item) for path, item in entries.items() if 'offset' in item}
    changed = []
    for path, patcher in PATCHERS.items():
        replacement = patcher(payloads[path].decode('utf8')).encode('utf8')
        if replacement != payloads[path]:
            changed.append(path)
        payloads[path] = replacement
    if not changed:
        raise ValueError('routing patch is already current; nothing to stage')
    if check_syntax:
        syntax_check(payloads)
    staged_archive = encode_archive(copy.deepcopy(header), payloads)
    new_raw, new_header, new_start, new_hash = load_archive_bytes(staged_archive)
    problems = archive_problems(new_raw, new_header, new_start, require_integrity=True)
    if problems:
        raise ValueError('invalid staged ASAR: ' + '; '.join(problems))
    original_binary = exe.read_bytes()
    old_record, new_record = embedded_record(old_hash), embedded_record(new_hash)
    if original_binary.count(old_record) != 1:
        raise ValueError('source EXE must embed its ASAR header hash exactly once')
    binary = original_binary.replace(old_record, new_record, 1)
    if binary.count(new_record) != 1 or binary.count(old_record):
        raise ValueError('staged EXE integrity record is ambiguous')
    result = {'clientVersion': version, 'patchVersion': RESTART_MARK, 'changed': sorted(changed),
              'originalHeaderHash': old_hash, 'stagedHeaderHash': new_hash,
              'originalArchiveSha256': hashlib.sha256(raw).hexdigest(),
              'archiveSha256': hashlib.sha256(staged_archive).hexdigest(),
              'originalExeSha256': hashlib.sha256(original_binary).hexdigest(),
              'stagedExeSha256': hashlib.sha256(binary).hexdigest(),
              'embeddedIntegrityUpdated': True, 'electronFusesChanged': False}
    # Validate the entire pair before creating a directory. Exclusive creation
    # prevents concurrent stages from overwriting either candidate.
    output.mkdir(parents=True, exist_ok=False)
    written = []
    try:
        for name, content in [('app.asar', staged_archive), ('Grok Bot.exe', binary),
                              ('manifest.json', json.dumps(result, indent=2).encode()),
                              ('original/resources/app.asar', raw),
                              ('original/Grok Bot.exe', original_binary)]:
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                written.append(target)
                stream.write(content)
    except Exception:
        for target in reversed(written):
            target.unlink(missing_ok=True)
        for directory in [output / 'original' / 'resources', output / 'original']:
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            output.rmdir()
        except OSError:
            pass
        raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', required=True)
    parser.add_argument('--output', required=True, help='new directory outside the installation')
    args = parser.parse_args()
    try:
        print(json.dumps(stage(args.install_dir, args.output), indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, 'CLIENT-STAGE-FAILED: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
