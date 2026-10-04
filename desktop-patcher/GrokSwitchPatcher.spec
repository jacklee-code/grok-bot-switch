# Build with: pyinstaller --clean --noconfirm GrokSwitchPatcher.spec
# GROK_SWITCH_NODE must identify the Node executable to embed.
import os
from pathlib import Path

patcher_root = Path(SPECPATH)
repo_root = patcher_root.parent
node = Path(os.environ.get('GROK_SWITCH_NODE', patcher_root / 'resources' / 'node.exe'))
if not node.is_file():
    raise SystemExit('Set GROK_SWITCH_NODE to a real Node.js 20+ node.exe before building.')
helper_root = repo_root / 'experimental' / 'client-066'
helper_names = ['asar.py', 'stage_client.py', 'verify_client.py', 'exercise_client.py',
                'patch_routing.py', 'local-routing.cjs', 'rollback_client.py',
                'LICENSE.upstream', 'ATTRIBUTION.md']
datas = [(str(helper_root / name), 'resources/client-066') for name in helper_names]
datas += [(str(patcher_root / 'README.md'), '.'), (str(repo_root / 'LICENSE'), '.'),
          (str(repo_root / 'THIRD_PARTY_NOTICES.md'), '.')]
node_license = patcher_root / 'resources' / 'NODE-LICENSE.txt'
if not node_license.is_file():
    raise SystemExit('Place the matching Node.js LICENSE at desktop-patcher/resources/NODE-LICENSE.txt.')
datas.append((str(node_license), 'resources'))
a = Analysis([str(patcher_root / 'app.py')], pathex=[str(patcher_root)],
             binaries=[(str(node), 'resources')], datas=datas,
             hiddenimports=['engine', 'discovery'], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=['asar', 'patch_routing', 'stage_client', 'verify_client'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name='GrokSwitchPatcher', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False,
          argv_emulation=False, target_arch=None, codesign_identity=None,
          entitlements_file=None, uac_admin=False)
