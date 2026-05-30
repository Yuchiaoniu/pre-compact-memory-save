# pre-compact-memory-save

Claude Code 的「對話壓縮／清空前後」記憶搶救機制（Windows PowerShell）。
讓 Claude 在對話被壓縮或 `/clear` 之後，仍能接續專案、不失憶。

## 三檔分工（每個專案資料夾各一份）

- **tasks.md**：主要進度（任務清單）。
- **memory.md**：長期查詢／對照資料——IP、地址、餘額、設定值、指令輸出、固定路徑、決策結論。只增與修正、去重。
- **STATE.md**：短期現況快照——只記「做到哪／手上在做什麼／下一步」。已搬進 memory.md 的舊資料會被剔除，保持精簡。

核心機制：每次存檔時，把 STATE.md 裡值得長期保存的資料搬進 memory.md，再從 STATE.md 移除。重要資料不掉，STATE.md 不臃腫。

## 兩支腳本

### `pre-compact-memory-save.ps1`（寫入端，背景安全網）
掛在 Claude Code 的 `Stop` hook（每輪結束、async 背景跑）。對話成長超過門檻時，
抓最近對話交給便宜的 Haiku 模型，更新該專案的 memory.md 與 STATE.md。
不在專案資料夾（無 tasks.md）時直接跳過，不呼叫 API。

### `session-start-inject-state.ps1`（壓縮後讀取端）
掛在 `SessionStart` hook（matcher = `compact`）。自動壓縮後，把該專案的
STATE.md / memory.md / tasks.md 念回給接手的 Claude，自動接續上次專案。
專案來源：先看 cwd 是否為專案資料夾，否則讀 `last-active-project.txt` 指標檔。

### `session-start-menu.ps1`（啟動／清空選單）
掛在 `SessionStart` hook（matcher = `startup|clear`）。在 PowerShell 啟動 claude
或按 `/clear` 後觸發。若 cwd 本身是專案資料夾就直接念回該專案三檔；否則列出
`openspec\changes` 下所有專案，指示 Claude 詢問使用者要進入哪一個，選定後讀三檔、寫指標檔。
（平台限制：Claude 無法在使用者打字前主動開口，啟動後需先送任一則訊息才會跳出選單。）

## settings.json hook 設定範例

```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "compact",
        "hooks": [{ "type": "command",
          "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\<you>\\.claude\\session-start-inject-state.ps1\"",
          "timeout": 10 }] },
      { "matcher": "startup|clear",
        "hooks": [{ "type": "command",
          "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\<you>\\.claude\\session-start-menu.ps1\"",
          "timeout": 10 }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command",
          "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\<you>\\.claude\\pre-compact-memory-save.ps1\"",
          "timeout": 40, "async": true }] }
    ]
  },
  "autoCompactEnabled": false
}
```

## CLAUDE.global.md

全域 `~/.claude/CLAUDE.md` 的備份（所有專案都會載入的規則）。內含：subagent 模型政策、
中文寫作規則（不以「的」結尾、不省略主詞、程式碼名稱補白話、技術說明分層寫法）、
回答風格（只給一個最佳解、簡要）、對話記憶與 clear 流程規則。純規則、不含任何金鑰。

## 注意

- `.ps1` 須存成 UTF-8 帶 BOM，否則 PowerShell 5.1 會把中文註解當 Big5 解讀而亂碼。
- 腳本讀取 API 金鑰來自本機 `~/.claude/.credentials.json`（OAuth token）或環境變數 `ANTHROPIC_API_KEY`，**不會上傳**。
