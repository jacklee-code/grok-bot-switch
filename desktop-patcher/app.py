"""Portable Windows UI and scriptable entry point for the scoped Grok adapter.

No account credentials or API keys are read. Mutations are delegated to engine.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

from discovery import discover_installations, discover_profiles, running_processes, path_key
from engine import Patcher, PatcherError, validate_scope

TITLE = "Grok Switch 桌面修補工具"
SCOPE_NAME = "grok-switch-local-agents.json"
STATUS_LABELS = {
    "original": "官方原版；優先直接使用雲端接入",
    "ours": "已套用修補",
    "unknown": "無法確認／需匯入原始備份",
    "unsupported": "版本或檔案不受支援",
    "missing": "找不到完整安裝",
}


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def find_node() -> str:
    for candidate in (resource_root() / "resources" / "node.exe",
                      Path(__file__).resolve().parent / "resources" / "node.exe"):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("node") or ""


def default_state_root() -> str:
    # Resolve this before elevation: another administrator's profile must never
    # become the target or the owner of the operation's restore snapshots.
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "GrokSwitchPatcher")


def read_scope(path: str | Path) -> dict:
    # Pass the original path to the authoritative parser so duplicate JSON keys,
    # reparse points and noncanonical IDs cannot be normalised away by this UI.
    return validate_scope(path)


def error_result(exc: BaseException) -> dict:
    return {"ok": False, "error": str(exc),
            "code": "permission_denied" if isinstance(exc, PermissionError) else getattr(exc, "code", "error")}


def execute(request: dict, progress=None) -> dict:
    patcher = Patcher(request["install_dir"], request["profile_dir"],
                      request.get("node_path") or find_node(),
                      state_root=request.get("state_root") or default_state_root(), progress=progress)
    action = request["action"]
    if action == "inspect":
        value = patcher.inspect()
    elif action == "patch":
        scope = request.get("scope")
        if not scope:
            raise ValueError("套用前請先匯入雲端已啟用 Bot 的 scope.json。")
        value = patcher.patch(scope, dry_run=request.get("dry_run", False))
    elif action == "restore":
        value = patcher.restore(dry_run=request.get("dry_run", False))
    elif action == "import_snapshot":
        value = patcher.import_snapshot(request["snapshot_dir"], dry_run=request.get("dry_run", False))
    else:
        raise ValueError("未知操作。")
    return {"ok": True, "action": action, "result": value}


def prepare_request(request: dict) -> None:
    """Resolve paths in the original caller's cwd and remember restart intent."""
    for key in ("install_dir", "profile_dir", "node_path", "state_root", "snapshot_dir"):
        if request.get(key):
            request[key] = str(Path(request[key]).resolve())
    if request["action"] in ("patch", "restore") and not request.get("dry_run") and not request.get("no_restart"):
        expected = path_key(Path(request["install_dir"]) / "Grok Bot.exe")
        request["restart_if_changed"] = any(
            row.get("ExecutablePath") and path_key(row["ExecutablePath"]) == expected
            for row in running_processes())


def _is_admin() -> bool:
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def elevate_once(request: dict) -> dict:
    """One UAC request, one operation, explicit original profile and state root.

    The elevated child does not launch Grok Bot. The original process does that
    after reading the result so the app keeps the user's unelevated identity.
    """
    if os.name != "nt" or _is_admin():
        raise PermissionError("沒有寫入權限，且無法再提升權限。")
    from ctypes import wintypes

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    with tempfile.TemporaryDirectory(prefix="grok-switch-elevate-") as temporary:
        request_file = Path(temporary) / "request.json"
        response_file = Path(temporary) / "response.json"
        request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        args = ["--elevated-request", str(request_file), "--json-output", str(response_file)]
        if not getattr(sys, "frozen", False):
            args.insert(0, str(Path(__file__).resolve()))
        info = SHELLEXECUTEINFO()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"
        info.lpFile = sys.executable
        info.lpParameters = subprocess.list2cmdline(args)
        info.lpDirectory = str(Path(__file__).resolve().parent)
        info.nShow = 0
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            raise PermissionError("管理員權限未獲批准，操作沒有繼續。")
        kernel = ctypes.windll.kernel32
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        kernel.CloseHandle(info.hProcess)
        if not response_file.is_file():
            raise RuntimeError("管理員程序沒有傳回結果。請按「檢查」確認目前狀態。")
        return json.loads(response_file.read_text(encoding="utf-8"))


def relaunch_if_needed(request: dict, response: dict) -> None:
    if not response.get("ok") or request.get("dry_run") or request.get("no_restart"):
        return
    result = response.get("result") or {}
    if result.get("stopped_processes", 0) or (result.get("changed") and request.get("restart_if_changed")):
        if _is_admin():
            result["relaunch_requested"] = False
            result["relaunch_error"] = "修補工具正以管理員身分執行；請用一般捷徑手動啟動 Grok Bot，以免它繼承管理員權限。"
            return
        executable = Path(request["install_dir"]) / "Grok Bot.exe"
        try:
            subprocess.Popen([str(executable), "--user-data-dir=" + request["profile_dir"]], cwd=str(executable.parent),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
            result["relaunch_requested"] = True
        except OSError as exc:
            # The committed patch/restore is still successful. Do not call it a
            # failed transaction solely because the optional launch failed.
            result["relaunch_requested"] = False
            result["relaunch_error"] = str(exc)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=TITLE)
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--inspect", action="store_true")
    modes.add_argument("--patch", action="store_true")
    modes.add_argument("--restore", action="store_true")
    modes.add_argument("--import-snapshot", metavar="DIRECTORY")
    modes.add_argument("--elevated-request", help=argparse.SUPPRESS)
    result.add_argument("--install-dir")
    result.add_argument("--profile-dir")
    result.add_argument("--scope", help="已在雲端啟用 Bot 的 scope.json")
    result.add_argument("--node-path")
    result.add_argument("--state-root")
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--json-output", help="將機器可讀結果寫入此路徑（portable EXE 建議使用）")
    result.add_argument("--no-restart", action="store_true")
    result.add_argument("--allow-elevation", action="store_true", help="CLI 遇權限不足時允許一次 UAC")
    return result


def write_result(value: dict, output: str | None) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2)
    if output:
        destination = Path(output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content + "\n", encoding="utf-8")
    if sys.stdout is not None:
        try:
            print(content)
        except (OSError, UnicodeError):
            pass


def cli(args: argparse.Namespace) -> int:
    request = None
    try:
        if args.elevated_request:
            request = json.loads(Path(args.elevated_request).read_text(encoding="utf-8"))
            response = execute(request)
        else:
            installs = discover_installations() if not args.install_dir else []
            install = args.install_dir or (installs[0]["install_dir"] if len(installs) == 1 else "")
            profiles = discover_profiles(install) if not args.profile_dir else []
            profile = args.profile_dir or (profiles[0]["profile_dir"] if len(profiles) == 1 else "")
            if not install or not profile:
                raise ValueError("無法唯一識別安裝／使用者設定目錄；請指定 --install-dir 與 --profile-dir。")
            request = {"action": "inspect" if args.inspect else "patch" if args.patch else "restore" if args.restore else "import_snapshot",
                       "install_dir": str(Path(install).resolve()), "profile_dir": str(Path(profile).resolve()),
                       "node_path": args.node_path or find_node(), "state_root": args.state_root or default_state_root(),
                       "scope": read_scope(args.scope) if args.scope else None, "snapshot_dir": args.import_snapshot,
                       "dry_run": args.dry_run, "no_restart": args.no_restart}
            prepare_request(request)
            try:
                response = execute(request)
            except PermissionError:
                if not args.allow_elevation:
                    raise
                response = elevate_once(request)
            relaunch_if_needed(request, response)
    except Exception as exc:
        response = error_result(exc)
    write_result(response, args.json_output)
    return 0 if response.get("ok") else 1


class Application:
    def __init__(self, root, args):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root = tk, ttk, root
        self.args, self.busy = args, False
        self.events = queue.Queue()
        self.scope = None
        self.scope_profile = None
        self.last_result = ""
        self.state_root = args.state_root or default_state_root()
        self.install = tk.StringVar(value=args.install_dir or "")
        self.profile = tk.StringVar(value=args.profile_dir or "")
        self.scope_summary = tk.StringVar(value="雲端接入正常時毋須匯入；套用備用 Patch 才需要 scope.json。")
        self.status = tk.StringVar(value="可檢查安裝；官方原版不代表需要修補")
        self.details = tk.StringVar(value="優先測試官方客戶端的雲端接入；工具只在按下套用或還原後更改檔案。")
        self.operation = tk.StringVar(value="準備就緒")
        root.title(TITLE)
        root.geometry("940x780")
        root.minsize(800, 690)
        root.configure(bg="#f2f5f9")
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f2f5f9")
        style.configure("TLabel", background="#f2f5f9", font=("Microsoft JhengHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft JhengHei UI", 20, "bold"), foreground="#153558")
        style.configure("Subtitle.TLabel", foreground="#506078")
        style.configure("Status.TLabel", font=("Microsoft JhengHei UI", 12, "bold"), foreground="#153558")
        style.configure("TButton", font=("Microsoft JhengHei UI", 10), padding=(12, 7))
        style.configure("Accent.TButton", background="#087bf0", foreground="white")
        style.map("Accent.TButton", background=[("active", "#0068d9"), ("disabled", "#9caec4")])
        style.configure("TLabelframe", background="#f2f5f9", bordercolor="#d3dbe6")
        style.configure("TLabelframe.Label", background="#f2f5f9", font=("Microsoft JhengHei UI", 10, "bold"))
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Grok Switch", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="桌面還原與備用修補  ·  Windows Grok Bot 0.66.0 / 雲端 1494ebd", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 16))
        notice = tk.Label(outer, text="優先保留官方客戶端：雲端相容層可讓已啟用的本地 Bot 直接使用自訂模型。\n此修補僅作相容性備用；原有 Temporal Bot、聊天及排程不會自動遷移。",
                          bg="#e7effb", fg="#163b68", font=("Microsoft JhengHei UI", 10), justify="left", padx=14, pady=11)
        notice.pack(fill="x", pady=(0, 12))
        locations = ttk.LabelFrame(outer, text="1  確認本機位置", padding=12)
        locations.pack(fill="x")
        locations.columnconfigure(1, weight=1)
        self.install_box = ttk.Combobox(locations, textvariable=self.install)
        self.profile_box = ttk.Combobox(locations, textvariable=self.profile)
        ttk.Label(locations, text="Grok Bot 安裝").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.install_box.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(locations, text="選擇…", command=lambda: self.choose_directory(self.install)).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(locations, text="使用者設定").grid(row=1, column=0, sticky="w", padx=(0, 12))
        self.profile_box.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Button(locations, text="選擇…", command=lambda: self.choose_directory(self.profile)).grid(row=1, column=2, padx=(8, 0))
        self.install_box.bind("<<ComboboxSelected>>", lambda _: self.refresh_profiles())
        self.profile_box.bind("<<ComboboxSelected>>", lambda _: self.load_profile_scope())
        self.profile_box.bind("<FocusOut>", lambda _: self.check_scope_profile())
        ttk.Label(locations, text="偵測此電腦的位置；不假定與家中電腦的磁碟或帳戶相同。", style="Subtitle.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(7, 0))
        scope_frame = ttk.LabelFrame(outer, text="2  備用 Patch：選擇已在雲端啟用的 Bot", padding=12)
        scope_frame.pack(fill="x", pady=12)
        ttk.Label(scope_frame, textvariable=self.scope_summary, wraplength=780).pack(anchor="w")
        scope_actions = ttk.Frame(scope_frame)
        scope_actions.pack(fill="x", pady=(9, 0))
        ttk.Button(scope_actions, text="匯入 scope.json…", command=self.import_scope).pack(side="left")
        ttk.Button(scope_actions, text="匯出至另一台電腦…", command=self.export_scope).pack(side="left", padx=8)
        ttk.Label(scope_actions, text="只包含 Bot ID，沒有 API 金鑰。", style="Subtitle.TLabel").pack(side="left", padx=3)
        status_frame = ttk.LabelFrame(outer, text="3  檢查、還原或套用備用修補", padding=12)
        status_frame.pack(fill="x")
        ttk.Label(status_frame, textvariable=self.status, style="Status.TLabel").pack(anchor="w")
        ttk.Label(status_frame, textvariable=self.details, wraplength=800).pack(anchor="w", pady=(5, 8))
        actions = ttk.Frame(status_frame)
        actions.pack(fill="x")
        self.action_buttons = []
        for label, action, style_name in [("檢查", "inspect", "TButton"), ("套用備用 Patch", "patch", "Accent.TButton"), ("還原原版", "restore", "TButton"), ("匯入舊版備份…", "import_snapshot", "TButton")]:
            button = ttk.Button(actions, text=label, command=lambda a=action: self.start(a), style=style_name)
            button.pack(side="left", padx=(0, 8))
            self.action_buttons.append(button)
        ttk.Label(status_frame, text="套用／還原會關閉此安裝的 Grok Bot，完成後重新開啟（原先有開啟時）。\n請先結束正在執行的工作。若安裝目錄需要管理員權限，整次操作只會要求一次。", style="Subtitle.TLabel").pack(anchor="w", pady=(10, 0))
        progress_line = ttk.Frame(outer)
        progress_line.pack(fill="x", pady=(12, 5))
        ttk.Label(progress_line, textvariable=self.operation).pack(side="left")
        self.progress = ttk.Progressbar(progress_line, mode="indeterminate", length=190)
        self.progress.pack(side="right")
        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=5, wrap="word", bg="#fff", fg="#334155", relief="flat", font=("Consolas", 9), padx=10, pady=8)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(state="disabled")
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Button(bottom, text="複製診斷記錄", command=self.copy_log).pack(side="left")
        ttk.Button(bottom, text="開啟備份資料夾", command=self.open_state).pack(side="right")
        self.load_discovery()
        if args.scope:
            self.set_scope(args.scope)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        if self.install.get() and self.profile.get():
            root.after(200, lambda: self.start("inspect"))

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def load_discovery(self):
        try:
            installs = discover_installations()
            values = [x["install_dir"] for x in installs]
            self.install_box["values"] = values
            if not self.install.get() and len(values) == 1:
                self.install.set(values[0])
            self.refresh_profiles()
        except Exception as exc:
            self.append("自動偵測未完成：" + str(exc))

    def refresh_profiles(self):
        values = [x["profile_dir"] for x in discover_profiles(self.install.get() or None)]
        self.profile_box["values"] = values
        if not self.profile.get() and len(values) == 1:
            self.profile.set(values[0])
        if self.profile.get() and self.scope is None:
            existing = Path(self.profile.get()) / SCOPE_NAME
            if existing.is_file():
                self.set_scope(str(existing))

    def load_profile_scope(self):
        self.scope = None
        self.scope_profile = None
        self.scope_summary.set("雲端接入正常時毋須匯入；備用 Patch 請使用此帳戶的 scope.json。")
        if self.profile.get():
            existing = Path(self.profile.get()) / SCOPE_NAME
            if existing.is_file():
                self.set_scope(str(existing))

    def check_scope_profile(self):
        if self.scope is not None and self.scope_profile != path_key(self.profile.get()):
            self.load_profile_scope()
            self.append("使用者設定位置已變更；已重新載入該位置的 Scope，請確認後再套用。")

    def choose_directory(self, variable):
        if self.busy:
            return
        from tkinter import filedialog
        value = filedialog.askdirectory(title="選擇資料夾", initialdir=variable.get() or None)
        if value:
            variable.set(value)
            self.refresh_profiles()
            if variable is self.profile:
                self.load_profile_scope()

    def set_scope(self, path):
        try:
            value = read_scope(path)
            self.scope = value
            self.scope_profile = path_key(self.profile.get())
            self.scope_summary.set(f"已載入 {len(value['agentIds'])} 個 Bot · 雲端 {value['hostVersion']} · {Path(path).name}")
            self.append("已載入 Scope；套用前仍會驗證完整格式。")
        except Exception as exc:
            self.scope = None
            self.scope_profile = None
            self.scope_summary.set("Scope 無效，請重新匯入。")
            self.append("Scope 無效：" + str(exc))

    def import_scope(self):
        if self.busy:
            return
        from tkinter import filedialog
        value = filedialog.askopenfilename(title="匯入雲端已啟用 Bot 的 Scope", filetypes=[("Scope JSON", "*.json")])
        if value:
            self.set_scope(value)

    def export_scope(self):
        if self.busy:
            return
        self.check_scope_profile()
        if not self.scope:
            self.append("尚未載入有效 Scope，無可匯出的 Bot。")
            return
        from tkinter import filedialog
        value = filedialog.asksaveasfilename(title="匯出 Scope 給同帳戶另一台電腦", initialfile="scope.json", defaultextension=".json", filetypes=[("Scope JSON", "*.json")])
        if value:
            try:
                Path(value).write_text(json.dumps(self.scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                self.append("已匯出 Scope：" + value)
            except Exception as exc:
                self.append("無法匯出：" + str(exc))

    def start(self, action):
        if self.busy:
            return
        if not self.install.get().strip() or not self.profile.get().strip():
            self.append("請先選擇 Grok Bot 安裝及使用者設定資料夾。")
            return
        self.check_scope_profile()
        if action == "patch" and self.scope is None:
            self.append("套用前必須匯入雲端已啟用 Bot 的 scope.json。")
            return
        snapshot_dir = None
        if action == "import_snapshot":
            from tkinter import filedialog
            snapshot_dir = filedialog.askdirectory(title="選擇含 manifest.json 與 original 的舊版完整候選／備份資料夾")
            if not snapshot_dir:
                return
        request = {"action": action, "install_dir": str(Path(self.install.get()).resolve()),
                   "profile_dir": str(Path(self.profile.get()).resolve()), "scope": self.scope,
                   "node_path": self.args.node_path or find_node(), "state_root": self.state_root,
                   "snapshot_dir": snapshot_dir, "dry_run": False}
        self.busy = True
        for button in self.action_buttons:
            button.configure(state="disabled")
        self.install_box.configure(state="disabled")
        self.profile_box.configure(state="disabled")
        self.progress.start(12)
        self.operation.set("正在處理…")
        self.append("開始：" + action)
        threading.Thread(target=self.worker, args=(request,), daemon=True).start()

    def worker(self, request):
        def progress(stage, message):
            self.events.put(("progress", f"[{stage}] {message}"))
        try:
            prepare_request(request)
            try:
                response = execute(request, progress)
            except PermissionError:
                if request["action"] == "inspect":
                    raise
                progress("elevation", "此安裝目錄需要管理員權限，即將進行一次 UAC。")
                response = elevate_once(request)
            relaunch_if_needed(request, response)
        except Exception as exc:
            response = error_result(exc)
        self.events.put(("done", response))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.operation.set(value)
                    self.append(value)
                else:
                    self.finish(value)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def finish(self, response):
        self.busy = False
        for button in self.action_buttons:
            button.configure(state="normal")
        self.install_box.configure(state="normal")
        self.profile_box.configure(state="normal")
        self.progress.stop()
        self.last_result = json.dumps(response, ensure_ascii=False, indent=2)
        self.append(self.last_result)
        if response.get("ok"):
            result = response.get("result") or {}
            status = result.get("status")
            self.status.set(STATUS_LABELS.get(status, "操作完成"))
            version = result.get("client_version") or "—"
            backup = result.get("backup_id") or "—"
            reason = result.get("reason") or ""
            self.details.set(f"版本：{version}　備份：{backup}\n{reason}")
            self.operation.set("完成")
            if response.get("action") == "import_snapshot":
                self.append("舊部署的設定已作為還原基準保存；無法推知舊部署之前是否已有 Scope。")
            if result.get("relaunch_error"):
                self.append("檔案操作已完成，但重開失敗；請手動啟動 Grok Bot。")
            if response.get("action") != "inspect":
                self.root.after(200, lambda: self.start("inspect"))
        else:
            self.status.set("操作未完成")
            self.details.set(response.get("error", "未知錯誤"))
            self.operation.set("請查看記錄；可複製診斷")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.get("1.0", "end-1c"))
        self.operation.set("診斷記錄已複製")

    def open_state(self):
        if Path(self.state_root).is_dir():
            os.startfile(self.state_root)
        else:
            self.append("尚未建立備份；成功套用或匯入備份後才會出現。")

    def close(self):
        if self.busy:
            self.operation.set("操作進行中，請等候完成後再關閉。")
            return
        self.root.destroy()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    argument_parser = parser()
    args = argument_parser.parse_args()
    if args.inspect or args.patch or args.restore or args.import_snapshot or args.elevated_request:
        return cli(args)
    if args.dry_run or args.no_restart or args.allow_elevation or args.json_output:
        argument_parser.error("--dry-run、--no-restart、--allow-elevation 和 --json-output 必須與 --inspect、--patch、--restore 或 --import-snapshot 一起使用。")
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    import tkinter as tk
    root = tk.Tk()
    Application(root, args)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
