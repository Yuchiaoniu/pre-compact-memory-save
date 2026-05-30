# session-start-menu.ps1
# 觸發時機：SessionStart，matcher = "startup|clear"
#   （在 PowerShell 輸入 claude 進到主畫面、或按 /clear 後都會跑）
#
# 行為：
#   1) 若目前資料夾 cwd 本身就是某個專案資料夾（裡面有 tasks.md / STATE.md）
#      → 直接把該專案的三檔念回，不多問（適用：open-projects.ps1 直接在專案資料夾啟動）。
#   2) 否則 → 列出 openspec\changes 下所有專案，指示 Claude 詢問使用者要進入哪一個，
#      使用者選定後再由 Claude 讀三檔、寫指標檔。
#
# 注意：壓縮後（compact）走另一支 session-start-inject-state.ps1，會自動接續上次專案，不列選單。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$cwd = $null
try { $raw = [Console]::In.ReadToEnd(); if ($raw) { $cwd = ($raw | ConvertFrom-Json).cwd } } catch {}
if (-not $cwd) { $cwd = (Get-Location).Path }

$changes = 'C:\Users\yuchi\openspec\changes'
$pointer = 'C:\Users\yuchi\.claude\last-active-project.txt'

# ---- 情況 1：cwd 自己就是專案資料夾 → 直接載入 ----
if ((Test-Path (Join-Path $cwd 'tasks.md')) -or (Test-Path (Join-Path $cwd 'STATE.md'))) {
    $o = [System.Collections.Generic.List[string]]::new()
    $o.Add("【系統提示：已在專案資料夾啟動，以下是該專案目前狀態，請據此接續，不要重新詢問已知資訊。】")
    $o.Add("（專案資料夾：$cwd）")
    foreach ($pair in @(@('STATE.md','目前現況快照'), @('memory.md','長期查詢/對照資料'), @('tasks.md','任務清單'))) {
        $fp = Join-Path $cwd $pair[0]
        if (Test-Path $fp) {
            try {
                $c = Get-Content $fp -Raw -Encoding UTF8
                if ($c.Trim().Length -gt 0) {
                    $o.Add(""); $o.Add("===== $($pair[0])（$($pair[1])）====="); $o.Add($c.TrimEnd())
                }
            } catch {}
        }
    }
    [Console]::Out.Write(($o -join "`n"))
    exit 0
}

# ---- 情況 2：列出所有專案，請 Claude 詢問 ----
if (-not (Test-Path $changes)) { exit 0 }
$projects = Get-ChildItem $changes -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne 'archive' -and (Test-Path (Join-Path $_.FullName 'tasks.md')) } |
    Sort-Object Name

if (-not $projects -or $projects.Count -eq 0) { exit 0 }

# 上次作用中的專案，標記為預設
$lastName = ''
if (Test-Path $pointer) {
    try { $lp = (Get-Content $pointer -Raw -Encoding UTF8).Trim(); if ($lp) { $lastName = Split-Path $lp -Leaf } } catch {}
}

$o = [System.Collections.Generic.List[string]]::new()
$o.Add("【系統提示：對話剛啟動或清空。請先協助使用者選擇要進入哪一個 openspec 專案，再開始工作。】")
$o.Add("我的第一則回覆要把下面這份清單列給使用者看，並問他要進入哪一個專案：")
$o.Add("")
$i = 0
foreach ($p in $projects) {
    $i++
    $mark = if ($p.Name -eq $lastName) { '  ← 上次作用中' } else { '' }
    $o.Add("$i. $($p.Name)$mark")
}
$o.Add("")
$o.Add("使用者選定專案 X 後，我要依序做：")
$o.Add("1. 讀 $changes\X\tasks.md（任務清單）。")
$o.Add("2. 讀 $changes\X\memory.md（長期查詢/對照資料）。")
$o.Add("3. 讀 $changes\X\STATE.md（目前現況快照）。不存在的檔就略過。")
$o.Add("4. 把 $changes\X 這個完整路徑寫進 $pointer（UTF-8 無 BOM）。")
$o.Add("5. 用白話回報該專案目前進度與待辦，再接著做。")
[Console]::Out.Write(($o -join "`n"))
exit 0
