"""Bounded Windows discovery. No drive scan, network access, or account reads."""
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess


def path_key(value):
    return os.path.normcase(os.path.abspath(os.fspath(value))).rstrip("\\/")


def running_processes():
    """Return Grok processes internally; never log their full command lines."""
    if os.name != 'nt':
        return []
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
               "@(Get-CimInstance Win32_Process -Filter \"Name='Grok Bot.exe'\" | "
               "Select-Object ProcessId,ExecutablePath,CommandLine) | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=25, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise OSError('Unable to inspect running Grok Bot processes; no processes were stopped.')
    if not result.stdout.strip():
        return []
    value = json.loads(result.stdout.lstrip('\ufeff'))
    return value if isinstance(value, list) else [value]


def _user_data_dir(command):
    if not isinstance(command, str):
        return None
    # The forms Electron accepts are --user-data-dir=value or --user-data-dir value.
    if os.name == 'nt':
        argc = ctypes.c_int()
        api = ctypes.windll.shell32.CommandLineToArgvW
        api.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        api.restype = ctypes.POINTER(ctypes.c_wchar_p)
        argv = api(command, ctypes.byref(argc))
        if not argv:
            return None
        try:
            values = [argv[index] for index in range(argc.value)]
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))
        for index, value in enumerate(values):
            if value.startswith('--user-data-dir='):
                return value.split('=', 1)[1]
            if value == '--user-data-dir' and index + 1 < len(values):
                return values[index + 1]
        return None
    match = re.search(r'(?:^|\s)--user-data-dir(?:=|\s+)(?:"([^"]+)"|([^\s"]+))', command)
    return (match.group(1) or match.group(2)) if match else None


def _registry_candidates():
    if os.name != 'nt':
        return []
    import winreg
    result = []
    for root, label in ((winreg.HKEY_CURRENT_USER, 'HKCU'), (winreg.HKEY_LOCAL_MACHINE, 'HKLM')):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, r'Software\Microsoft\Windows\CurrentVersion\App Paths\Grok Bot.exe',
                                    0, winreg.KEY_READ | view) as key:
                    path, _ = winreg.QueryValueEx(key, '')
                    result.append((Path(os.path.expandvars(path.strip('"'))).parent, label + ' App Paths'))
            except OSError:
                pass
            try:
                with winreg.OpenKey(root, r'Software\Microsoft\Windows\CurrentVersion\Uninstall',
                                    0, winreg.KEY_READ | view) as uninstall:
                    for index in range(winreg.QueryInfoKey(uninstall)[0]):
                        try:
                            with winreg.OpenKey(uninstall, winreg.EnumKey(uninstall, index)) as key:
                                name, _ = winreg.QueryValueEx(key, 'DisplayName')
                                if name != 'Grok Bot':
                                    continue
                                try:
                                    path, _ = winreg.QueryValueEx(key, 'InstallLocation')
                                    if path:
                                        result.append((Path(os.path.expandvars(path.strip('"'))), label + ' Uninstall'))
                                except OSError:
                                    pass
                                try:
                                    icon, _ = winreg.QueryValueEx(key, 'DisplayIcon')
                                    icon = re.sub(r',\s*-?\d+$', '', icon).strip('"')
                                    if Path(icon).name.lower() == 'grok bot.exe':
                                        result.append((Path(os.path.expandvars(icon)).parent, label + ' DisplayIcon'))
                                except OSError:
                                    pass
                        except OSError:
                            continue
            except OSError:
                pass
    return result


def discover_installations():
    candidates = []
    for process in running_processes():
        if process.get('ExecutablePath'):
            candidates.append((Path(process['ExecutablePath']).parent, 'running process'))
    candidates.extend(_registry_candidates())
    for variable in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432'):
        if os.environ.get(variable):
            candidates.append((Path(os.environ[variable]) / 'Grok Bot', variable))
    if os.environ.get('LOCALAPPDATA'):
        base = Path(os.environ['LOCALAPPDATA'])
        candidates.extend((base / suffix, 'LOCALAPPDATA') for suffix in ('Programs/Grok Bot', 'Grok Bot'))
    unique = {}
    for candidate, source in candidates:
        if not (candidate / 'Grok Bot.exe').is_file() or not (candidate / 'resources/app.asar').is_file():
            continue
        key = path_key(candidate)
        row = unique.setdefault(key, {'install_dir': str(candidate.absolute()),
                                      'exe_path': str((candidate / 'Grok Bot.exe').absolute()), 'sources': []})
        if source not in row['sources']:
            row['sources'].append(source)
    return list(unique.values())


def discover_profiles(install_dir=None):
    candidates = []
    expected = path_key(Path(install_dir) / 'Grok Bot.exe') if install_dir else None
    for process in running_processes():
        if expected and (not process.get('ExecutablePath') or path_key(process['ExecutablePath']) != expected):
            continue
        directory = _user_data_dir(process.get('CommandLine'))
        if directory:
            candidates.append((Path(directory), 'running --user-data-dir'))
    if os.environ.get('APPDATA'):
        candidates.append((Path(os.environ['APPDATA']) / 'Grok Bot', 'APPDATA'))
    unique = {}
    for candidate, source in candidates:
        if not candidate.is_absolute() or not candidate.is_dir():
            continue
        row = unique.setdefault(path_key(candidate), {'profile_dir': str(candidate.absolute()), 'sources': []})
        if source not in row['sources']:
            row['sources'].append(source)
    return list(unique.values())


def stop_installation(install_dir):
    """Stop only processes whose *current* executable path matches the selected install."""
    expected = path_key(Path(install_dir) / 'Grok Bot.exe')
    matched = [int(row['ProcessId']) for row in running_processes()
               if row.get('ExecutablePath') and path_key(row['ExecutablePath']) == expected]
    if not matched:
        return 0
    command = r'''$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
foreach ($processId in $request.pids) {
  $item = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$processId)
  if ($null -eq $item) { continue }
  if ([string]::IsNullOrEmpty($item.ExecutablePath) -or
      ![string]::Equals([IO.Path]::GetFullPath($item.ExecutablePath), $request.exe,
                      [StringComparison]::OrdinalIgnoreCase)) { throw 'Process identity changed' }
  Stop-Process -Id ([int]$processId) -Force -ErrorAction Stop
}
'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            input=json.dumps({'pids': matched, 'exe': str((Path(install_dir) / 'Grok Bot.exe').absolute())}),
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise OSError('Could not stop the selected Grok Bot installation safely. Close it and retry.')
    remaining = [row for row in running_processes()
                 if row.get('ExecutablePath') and path_key(row['ExecutablePath']) == expected]
    if remaining:
        raise OSError('The selected Grok Bot installation restarted; close it and retry.')
    return len(matched)
