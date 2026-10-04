# Grok Switch Windows 桌面修補工具

**優先保留官方客戶端，使用雲端接入。** 已驗證官方 **Grok Bot 0.66.0** 可配合雲端 host `1494ebd` 的相容層，直接使用已在雲端啟用的本地 Bot，毋須套用桌面 Patch。檢查顯示「官方原版」不代表需要修補。

這個可攜式 Windows GUI 用於還原舊桌面修補，以及確有相容問題時的**備用修補**。發佈的 `GrokSwitchPatcher.exe` 包含 Python、Tkinter 與 Node.js；使用電腦不需要另裝 Python 或 Node。工具不讀取 Grok 登入憑證或供應商 API 金鑰。

**雲端接入與備用 Patch 都不會把所有既有 Bot 切換至自己的模型。** 雲端必須已安裝配對的相容層，目標 Bot 必須已是雲端明確啟用的本地 Bot。既有 Temporal Bot 的身份、聊天、排程不會遷移，官方 weekly quota 的計量亦不在此工具控制範圍。

## 在另一台電腦使用

1. 安裝相同受支援版本的**官方原版** Grok Bot，登入同一帳戶及雲端。
2. 選擇已在雲端啟用的本地 Bot，輸入 `/gs status`，再測試一則普通訊息。
3. 雲端接入正常就可直接使用，不需要桌面 Patch，也不需要匯入 Scope。原有 Temporal Bot 仍維持官方路徑。
4. 若電腦已套用先前的桌面修補，可使用本工具的「還原原版」回復後，再驗收雲端接入。

## 確有需要時才使用備用 Patch

先確認雲端相容層、目標 Bot 及連線均已設定；其他版本或未設定的雲端不能藉此工具自動修復。

1. 在已啟用的電腦匯出 `scope.json`，或使用雲端匯出的同格式 Scope。Scope 只有 Bot ID 與相容版本，沒有密碼或金鑰。
2. 開啟 `GrokSwitchPatcher.exe`。工具自動尋找本機安裝與使用者設定資料夾；有多個候選時請選擇實際使用的那個，亦可手動選擇路徑。
3. 按「檢查」，匯入 `scope.json`，結束正在進行的 Grok Bot 工作，再按「套用備用 Patch」。
4. 工具先驗證版本、來源、完整性及候選檔案，保存可驗證備份，才關閉該安裝的 Grok Bot 並更換檔案。原先有開啟時，完成後會以原使用者重新啟動。
5. 在 Scope 所列的新本地 Bot 輸入 `/gs status`，再測試一則普通訊息。這一步才是實際接入驗收；補丁檢查成功本身不證明雲端連線正常。

本工具只修改選定安裝的 `Grok Bot.exe`、`resources/app.asar` 及選定 profile 的 `grok-switch-local-agents.json`。EXE 的修改用來配對 ASAR 完整性雜湊；這會改動官方檔案，不能視為仍保留官方程式碼簽章。未知版本、陌生修改或找不到可信原始備份時會拒絕操作。

一般情況以普通使用者執行。如安裝目錄需管理員寫入權限，按下套用／還原的那次操作只會要求一次 UAC；操作仍使用原使用者已選定的 profile 與備份目錄。不要事先以另一帳戶「以管理員身分執行」。若工具本身由管理員程序啟動，完成後會請你以一般捷徑手動開啟 Grok Bot，避免應用繼承管理員權限。

## 還原

開啟工具，確認同一安裝及 profile，按「還原原版」。工具會檢查目前檔案是否仍與所保存的修補配對，再復原原始檔案及該次修補前的 Scope 設定。若官方更新或其他軟件改動過檔案，工具會拒絕覆蓋；請先檢查診斷記錄。

備份預設保存在 `%LOCALAPPDATA%\GrokSwitchPatcher`。每個安裝分開管理；可按「開啟備份資料夾」查看。請保留這個資料夾，直到不再需要還原。

舊版手動部署的修補沒有受此工具管理的備份。此時按「匯入舊版備份」，選擇先前 stage 工具產生、含 `manifest.json`、候選 `app.asar`／`Grok Bot.exe` 及完整 `original` 目錄的資料夾。只有完整驗證且與現有安裝完全吻合，才會登記。**此匯入無法推知舊部署前的 Scope；匯入時的 Scope 會作為設定還原基準。**

桌面還原不會拆除雲端相容層，也不會删除雲端 Bot。雲端回復需遵循 [`experimental/host-066/README.md`](../experimental/host-066/README.md) 的獨立步驟。

## 命令列

GUI 是預設入口。自動化使用以下互斥模式；所有模式支援 `--json-output`。Windows 無主控台 EXE 請以此結果檔讀取完整結果與錯誤，並等待程序退出。

```powershell
# 明確指定本機路徑；不要照抄另一台電腦的磁碟或使用者名稱。
$app = 'C:\Apps\Grok Bot'
$profile = Join-Path $env:APPDATA 'Grok Bot'
$arguments = @('--inspect', '--install-dir', $app, '--profile-dir', $profile,
               '--json-output', (Join-Path $PWD 'inspect.json'))
# PowerShell 的 Start-Process -ArgumentList 對含空格路徑需自行引用；
# 使用呼叫運算子及 Wait-Process 亦可，Python 呼叫示例見下。
& .\GrokSwitchPatcher.exe @arguments | Out-Null
```

可靠等待的 Python 自動化示例（僅開發者需要 Python）：

```python
import subprocess
subprocess.run([
    "GrokSwitchPatcher.exe", "--inspect",
    "--install-dir", r"C:\Apps\Grok Bot",
    "--profile-dir", r"C:\Users\example\AppData\Roaming\Grok Bot",
    "--json-output", "inspect.json",
], check=True)
```

其他模式：

- `--patch --scope <scope.json>`：套用指定 Scope。已套用相同 Scope 時不重複修改；要更換 Scope 請先還原再套用，保留明確的設定還原基準。
- `--restore`：從已驗證備份還原。
- `--import-snapshot <directory>`：登記舊版 stage 備份。
- `--dry-run`：驗證並回報計畫，不寫入或停止 Grok Bot。
- `--no-restart`：成功操作後不重開 Grok Bot。
- `--allow-elevation`：CLI 權限不足時允許一次 UAC；預設 CLI 直接回報權限錯誤。
- `--state-root <directory>`：明確指定備份庫，通常不需要。
- `--node-path <node.exe>`：開發時覆寫內附 Node；通常不需要。

讀取 Scope 的格式：

```json
{
  "version": 1,
  "hostVersion": "1494ebd",
  "agentIds": ["11111111-1111-4111-8111-111111111111"]
}
```

上述 ID 只是虛構示例，不可直接使用。只接受 1–16 個不重複、canonical 小寫 UUID v4，且不接受額外欄位。

## 從來源建立可攜式 EXE

開發機需要 Windows、Python 3.10+（含 Tkinter）、PyInstaller 6.20.0 及 Node.js 20+。將與內附 Node 配對的 LICENSE 放到 `desktop-patcher/resources/NODE-LICENSE.txt`，再執行：

```powershell
.\desktop-patcher\build.ps1 -Python C:\Python312\python.exe -NodePath 'C:\Program Files\nodejs\node.exe' -InstallBuildDependency
```

預設輸出為 `desktop-patcher/dist/GrokSwitchPatcher.exe`；可用 `-OutputDirectory` 另選目錄。EXE 不附帶 Grok Bot 的 vendor binaries、帳戶 profile、真實 Bot ID 或供應商設定。它在使用者本機對其既有安裝產生候選。

目前對 GUI 和 CLI 的離線驗證不能代替每台電腦的實際聊天驗收。請參閱儲存庫的 `VALIDATION.md`，區分自動測試、安裝檔驗證與真實訊息往返。
