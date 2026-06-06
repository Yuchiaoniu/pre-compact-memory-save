# Claude Code Global Rules

## Subagent Model Policy

When spawning subagents via the Agent tool, follow this strictly:

- **Haiku**: search, file reading, grep, simple lookups
- **Sonnet**: everything else — including complex architecture,
  multi-file refactoring, and design decisions
- **Opus**: NEVER, unless the user explicitly requests it in that turn

Rationale: Sonnet 4.6 is sufficient for all routine tasks in this
workflow. Opus is 5x more expensive per output token with marginal
quality gain for well-specified tasks.

## Context 節省原則（避免無謂 token 消耗）

大檔案和遠端腳本是最常見的 context 殺手，每次操作前先問自己「我真的需要整份內容嗎？」。

**讀檔：只取需要的部分，不讀整份**
- 要了解檔案結構 → 用 `grep -n '關鍵字'` 找到行號再讀那幾行，不用 `sed -n '1,800p'` 把全文倒進來。
- 要確認某個欄位存不存在 → `grep -c 'pattern'` 或 `grep -m3` 取前幾筆，不讀整份 JSON。
- 非得看某段落 → `sed -n 'START,ENDp'`，範圍控制在 30–50 行以內；分三次讀 300 行等於讀完整檔，毫無意義。

**遠端腳本回傳：只輸出關鍵數值，不 dump 整個物件**
- SSH 執行 Node.js / Python 腳本時，`console.log` 只印出要驗證的欄位名稱與數值，不印 `JSON.stringify(wholeObject)`。
- `curl | grep` 優於 `curl` 把整頁 HTML 倒進 context 再讓 Claude 解析。

**寫入大檔：Write 工具會把整份內容存進 context，能省則省**
- 超過 150 行的檔案，先問自己能否用 Edit（只傳 diff）取代 Write（傳整份）。
- 若必須用 Write，寫完後不要再用 Read 驗證——Edit/Write 失敗會報錯，成功就是成功。

**數字門檻（違反時需有明確理由）**
- 單次 SSH 腳本回傳 > 50 行 → 改用 grep 或只印摘要。
- 單次 sed 範圍 > 60 行 → 先 grep 確認目標行號再縮範圍。
- Write 整份檔案 > 200 行 → 優先考慮 Edit；若是全新檔案則可以，但寫完就停，不要再 Read 回來。

## Subagent Isolation Policy

Use the Agent tool (subagent_type: Explore, model: haiku) for retrieval tasks:
- Any Glob or Grep that doesn't target a single known path
- Read when the target file is not a single known path, or expected content exceeds ~50 lines
- Any multi-file exploration or open-ended codebase search
- Any PowerShell / SSH / gcloud command whose output exceeds ~10 lines or is purely
  informational (e.g. `instances list`, `ss -tlnp`, `ls`, `cat` on a remote file)

Keep in the main session (never delegate):
- Analysis, diagnosis, and judgment — including interpreting SSH output,
  log analysis, and any decision-making based on retrieved data
- Single known-path Read where only a short section is needed
- All Write / Edit operations
- PowerShell commands that mutate state (e.g. start/stop VM, write file, deploy)

Subagents must return only a summary — never paste raw tool output back
into the main session.

## 回覆原則與寫作規則

中文輸出禁止句子以「的」結尾，改用完整謂語結構。

中文句子必須保留完整的主詞＋動詞＋受詞結構，不可縮略謂語。
錯誤示例：「梯度強度分不清」、「邊緣無法辨別」
正確示例：「無法分清楚梯度強度」、「無法辨別正確的邊緣」

數字/資料值作受詞時同樣禁止話題化（受詞前移）：
錯誤示例：「14 GB 用掉」、「15 GB 剩餘」
正確示例：「已經用掉 14 GB」、「還剩 15 GB」

子句同樣不可省略主詞，每個子句都要有自己的主詞。
錯誤示例：「才能確認裡面 frames 指哪一個」
正確示例：「才能確認函式裡面 frames 指哪一個」

提到程式碼名稱（函式、變數、類別等識別字）時，名稱原樣保留、不翻譯成中文，
但每個名稱第一次出現時，我要在名稱後面用括號補一句白話，說明這個名稱代表什麼。
範例：「我得先把 processVideo 這個函式從頭讀到尾，才能確認函式裡面 frames
這個變數代表整支影片的所有畫面（allFrames），還是只有卡片區那幾張畫面（cardFrames）。」

講技術判斷或操作步驟時，用「分層」寫法，兼顧好懂與精簡：
- 主句只講「結論＋接下來要怎麼辦」，全白話、不夾術語，並把「怎麼辦」提到最前面。
- 技術細節（欄位名、機制原理、章節編號、雜湊值/ID 等長代號）縮進括號補一句，
  給想深究的人看；不想看的人略過也不影響理解。
- 主句不要塞長代號（例如一長串雜湊值），長代號一律降級到括號當「查得到就好」的細節。
範例：
主句「同一支影片重新上傳不會觸發新的處理流程，系統會當成已處理過直接擋掉。
想讓它真的重跑一次，只能先刪掉舊紀錄再重新上傳。」
括號「（技術細節：影片靠 video_hash 這個不可重複的欄位辨識，雜湊相同就被去重擋下；
要刪的是樹表裡 7cf542e6... 那一列。）」

**回覆風格**
- 說明與敘述時避免使用代名詞，不寫「你怎樣怎樣」，直接描述事實或動作。
- 預設只提供一個最佳解法，不列選項讓使用者挑；只有選項之間有重大衝突且無法代為判斷時才提出選擇。
- 回答簡要，先講結論與重點，細節需要時再展開。
- 每個說明點不超過 150 字；超過時拆成兩點，不得合併堆疊。
- 問句必須保留完整動詞結構；禁止截斷式問法。錯誤：「X 能用嗎」。正確：「能使用 X 嗎」「是否能執行 X」。

### 論文改寫句型規則

只要這次對話提到 **thesis-rewrite / 論文改寫 / 論文段落 / 學術寫作** 這類關鍵字，
就先讀 `C:\Users\yuchi\.claude\docs\thesis-writing-rules.md` 再回答。

## 自訂指令

### 「請存檔」指令

當使用者說「請存檔」時，立刻執行以下三個動作（全部用 PowerShell 以 UTF-8 帶 BOM 寫入）：

1. 把這次對話裡值得長期保存的查詢/對照資料併入當前專案的 `memory.md`（去重、更新，不刪仍有效的舊資料）。
2. 重寫當前專案的 `STATE.md`，只留「現況＋進行中＋下一步」，已完成或已搬進 memory.md 的舊資料一律剔除。
3. 確認當前專案路徑已寫進 `C:\Users\yuchi\.claude\last-active-project.txt`。

執行完畢後，回覆以下兩件事：
- 實際寫入的三個檔案完整路徑
- 說明下次開啟此專案時，系統會自動讀取哪些檔案（tasks.md、memory.md、STATE.md）

## 常用腳本指令

當使用者說「請開啟所有未完成的專案」或類似意思，執行：
```powershell
& "C:\Users\yuchi\open-projects.ps1"
```
此腳本會掃描 `C:\Users\yuchi\openspec\changes\` 下所有專案的 tasks.md，
對每個有 `[ ]` 未完成任務的專案，在同一個 Windows Terminal 視窗內以新分頁開啟 claude，
分頁標題與視窗內文字都會顯示專案名稱，並自動通過授權提示（--dangerously-skip-permissions）。

## 對話記憶機制

記憶系統與「壓縮前搶救」機制的完整白話說明，見
`C:\Users\yuchi\.claude\docs\memory-mechanism.md`（需要細節時再讀）。

規則（每次都要遵守）：
- 不要在記憶檔或對話裡使用「Last Session」這種自創英文標籤。
  一律改用白話中文描述，例如「上一次對話的進度」。

## VM 生產檔案修改流程（違反必問使用者）

只要這次對話提到 **staging / SCP 改檔 / 修改 VM 上的檔案 / public/dashboard / push_gh**
這類關鍵字，就先讀 `C:\Users\yuchi\.claude\docs\vm-file-workflow.md` 再動手。

## 程式碼寫入後的測試要求

每次用 Write 或 Edit 寫入程式碼（.py/.js/.ts/.ps1/.go 等）或 PPTX 相關檔案後，
必須撰寫並執行測試腳本驗證，**嚴禁用視覺審查代替執行**：

1. **邏輯正確**：執行測試腳本或實際跑程式，印出關鍵數值確認結果
2. **無殘留代碼**：舊版本片段、被取代的邏輯、遺留 TODO/placeholder 已清除
3. **版面正確（PPTX）**：執行後截圖或用工具確認版面，不靠目視

多檔任務可等所有檔案寫完後統一跑測試，但不可跳過。
審查結果不需要在回覆中說明，直接繼續下一步。

## OpenSpec 模式切換（嚴格執行，無例外）

**探索模式（任何討論皆強制執行）**
只要對話內容是討論、提問、評估、探索，無論話題大小，必須立即呼叫
Skill(openspec-explore) 並在回覆第一句標示 `【探索模式】`。

**提案＋實作模式（任何寫入皆強制執行）**
任何檔案寫入（.md、.json、.ps1、.html、設定檔、程式碼）在執行前，
必須先呼叫 Skill(openspec-propose) 產生提案並標示 `【提案模式】`，
提案確認後呼叫 Skill(opsx:apply) 並標示 `【實作模式】`。
緊急修復、typo fix、一行改動皆不例外。

**全域設定歸屬規則**
CLAUDE.md、settings.json、全域 ps1 腳本等全域設定的 propose，
一律建在 auto-memory-sync 專案底下，不建立新專案。
