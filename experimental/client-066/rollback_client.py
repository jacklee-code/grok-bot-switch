"""Prepare an exact rollback pair; never write to or restart the installation."""
import argparse
import hashlib
import json
from pathlib import Path

from stage_client import install_files
from verify_client import verify


def rollback_candidate(install_dir, staged_dir, output_dir, *, check_syntax=True):
    install, staged, output = (Path(p).resolve() for p in (install_dir, staged_dir, output_dir))
    if output.is_relative_to(install) or output.is_relative_to(staged) or output.exists():
        raise ValueError('rollback output must be a new directory outside installation and candidate')
    result = verify(staged / 'original', staged, check_syntax=check_syntax)
    if not result['healthy']:
        raise ValueError('candidate or original snapshot failed verification: ' + '; '.join(result['integrityProblems']))
    archive, exe = install_files(install)
    current = {'app.asar': archive.read_bytes(), 'Grok Bot.exe': exe.read_bytes()}
    expected = {name: (staged / name).read_bytes() for name in current}
    original_paths = install_files(staged / 'original')
    originals = dict(zip(current, (p.read_bytes() for p in original_paths)))
    if current == originals:
        raise ValueError('installation already matches the original snapshot; rollback is not required')
    if current != expected:
        raise ValueError('installation does not match this candidate; refusing stale rollback')
    manifest = {'kind': 'client-066-rollback', 'sourceCandidate': str(staged),
                'files': {name: {'currentSha256': hashlib.sha256(current[name]).hexdigest(),
                                 'restoreSha256': hashlib.sha256(data).hexdigest()}
                          for name, data in originals.items()},
                'installationModified': False}
    output.mkdir(parents=True, exist_ok=False)
    written = []
    try:
        for name, data in [*originals.items(), ('rollback-manifest.json', json.dumps(manifest, indent=2).encode())]:
            path = output / name
            with path.open('xb') as stream:
                written.append(path)
                stream.write(data)
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        try:
            output.rmdir()
        except OSError:
            pass
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', required=True)
    parser.add_argument('--staged-dir', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(rollback_candidate(args.install_dir, args.staged_dir, args.output), indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, 'CLIENT-ROLLBACK-STAGE-FAILED: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
