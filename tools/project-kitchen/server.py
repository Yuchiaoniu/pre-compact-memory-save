# -*- coding: utf-8 -*-
from flask import Flask, jsonify, Response, request, send_from_directory
import os, re, json, subprocess, datetime, threading, tempfile, time

app = Flask(__name__, static_folder='.')

CHANGES = r"C:\Users\yuchi\openspec\changes"

# In-memory conversation histories — avoids re-reading log.md and pattern poisoning
# project -> [{"role": "user"/"assistant", "content": "..."}]
chat_histories = {}
active_procs   = {}  # project -> Popen (for stop support)


def read_utf8(path, limit=1500):
    if not os.path.exists(path):
        return ''
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read(limit)

def read_utf8_tail(path, limit=50000):
    """Read the last `limit` bytes of a file (for append-only logs)."""
    if not os.path.exists(path):
        return ''
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        if size > limit:
            f.seek(-limit, 2)
        data = f.read(limit)
    return data.decode('utf-8', errors='replace')


def _parse_log_turns(content, n=8):
    turns = []
    for sec in content.split('\n---\n'):
        sec = sec.strip()
        if not sec:
            continue
        um = re.search(r'\*\*使用者\*\*：(.+?)(?=\*\*Claude\*\*：|\Z)', sec, re.DOTALL)
        cm = re.search(r'\*\*Claude\*\*：(.+?)$', sec, re.DOTALL)
        if um and cm:
            turns.append({'user': um.group(1).strip(), 'bot': cm.group(1).strip()})
    return turns[-n:] if len(turns) > n else turns

def _log_since_last_impl(content):
    """Return the portion of log content after the last [IMPL] marker."""
    pos = content.rfind('\n## [IMPL]')
    return content[pos:] if pos >= 0 else content

def read_log_for_prompt(project_path):
    """Read all turns since last [IMPL] marker for subprocess prompt context."""
    content = read_utf8_tail(os.path.join(project_path, 'log.md'), limit=50000)
    if not content:
        return ''
    turns = _parse_log_turns(_log_since_last_impl(content), n=999)
    if not turns:
        return ''
    return '\n'.join(f"使用者：{t['user']}\nClaude：{t['bot']}" for t in turns)

def read_log_for_display(project_path, n=20):
    """Read turns since last [IMPL] for stove history display."""
    content = read_utf8_tail(os.path.join(project_path, 'log.md'), limit=50000)
    if not content:
        return []
    return _parse_log_turns(_log_since_last_impl(content), n)

def append_log_turn(project_path, user_msg, response):
    log_path = os.path.join(project_path, 'log.md')
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    entry = f'\n## {now}\n\n**使用者**：{user_msg}\n\n**Claude**：{response}\n\n---\n'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(entry)

def append_impl_marker(project_path):
    """Insert [IMPL] marker after a spawn completes successfully."""
    log_path = os.path.join(project_path, 'log.md')
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f'\n## [IMPL] {now}\n\n---\n')


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.get('/api/projects')
def list_projects():
    result = []
    for name in sorted(os.listdir(CHANGES)):
        p = os.path.join(CHANGES, name)
        if not os.path.isdir(p):
            continue
        tp = os.path.join(p, 'tasks.md')
        sp = os.path.join(p, 'STATE.md')
        pending = done = 0
        next_task = ''
        if os.path.exists(tp):
            with open(tp, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            pending   = sum(1 for l in lines if re.match(r'\s*-\s*\[ \]', l))
            done      = sum(1 for l in lines if re.match(r'\s*-\s*\[x\]', l, re.I))
            first     = next((l for l in lines if re.match(r'\s*-\s*\[ \]', l)), '')
            next_task = re.sub(r'^\s*-\s*\[ \]\s*', '', first).strip()[:80]
        result.append({
            'name': name,
            'pending': pending,
            'done': done,
            'nextTask': next_task,
            'state': read_utf8(sp),
            'logTurns': read_log_for_display(p),
        })
    return jsonify(result)


@app.post('/api/chat')
def chat():
    d        = request.json
    project  = d.get('project', '')
    user_msg = d.get('userMsg', '')

    project_path = os.path.join(CHANGES, project)
    if not os.path.isdir(project_path):
        return jsonify({'error': '找不到專案'}), 404

    if project not in chat_histories:
        turns = read_log_for_display(project_path, n=20)
        chat_histories[project] = [(t['user'], t['bot']) for t in turns]

    history = chat_histories[project]

    # Read fresh on every request so terminal-session updates (存檔) are visible immediately
    state = read_utf8(os.path.join(project_path, 'STATE.md'), limit=2000)
    tasks_raw = read_utf8(os.path.join(project_path, 'tasks.md'), limit=3000)
    pending = [l.strip() for l in tasks_raw.splitlines() if re.match(r'\s*-\s*\[ \]', l)]
    parts = []
    if state:
        parts.append(f'=== 目前進度（STATE.md）===\n{state.strip()}')
    if pending:
        parts.append('=== 待辦任務 ===\n' + '\n'.join(pending[:20]))
    context = '\n\n'.join(parts)

    _SYSTEM = f"""你是專案「{project}」的對話助理。工作路徑：{project_path}

## 身份與工作目標

協助使用者探索、規劃、實作這個 openspec 專案。三個核心檔案：
- {project_path}\\tasks.md：任務清單（[ ] 未完成、[x] 已完成）
- {project_path}\\memory.md：長期保存的查詢/對照資料
- {project_path}\\STATE.md：短期現況快照（只記目前做到哪、下一步）

## 基本行為規則

- 直接回答問題，不做開場白，不摘要專案現況
- 讀寫專案檔案一律用完整路徑（工作路徑：{project_path}）
- 確認明確可執行任務後，最後一行單獨輸出：[ACTION]<任務一句話>

## 預設探索模式（嚴格執行，無例外）

對話中**沒有**出現「請實作」「實作」「開始做」「好」「可以」「做吧」等明確授權語時，
一律處於探索模式：只討論，不動任何檔案。

探索模式下同樣嚴格遵守所有回覆規則（中文句式結構、禁止話題化、工具名稱括號補充、分層寫法等）。

收到明確授權語後才能動手：
- 先把計劃任務寫進 {project_path}\\tasks.md [ ] 條目，完成後改 [x]
- 每輪結束前更新 {project_path}\\STATE.md（只留現況＋下一步）

## 專案三檔分工

- tasks.md：主要進度，只做任務清單與勾選
- memory.md：查詢/對照資料的長期保存區（IP、地址、設定值、對照關係、重要決策）。只新增與修正、去重，不刪仍有效的舊資料
- STATE.md：短期現況快照，只記「目前做到哪、手上在處理什麼、下一步」。已完成或已存進 memory.md 的資料要從 STATE.md 剔除，保持精簡

## memory.md 查詢規則

不自動載入 memory.md，只有下列情況才查詢：
- 使用者詢問具體數值（IP、地址、設定值、指令輸出等）
- 需要查對照關係時
- 工作過程需引用過去記錄的決策結論時

查詢步驟：先用 Grep 工具以關鍵字掃描 {project_path}\\memory.md，有相關段落才用 offset+limit 只讀那幾行，不整份載入。

## Subagent 模型政策

使用 Agent 工具時：
- Haiku：搜尋、讀檔、grep、簡單查詢
- Sonnet：其餘所有工作（複雜架構、多檔重構、設計決策）
- Opus：禁止，除非使用者明確要求

## Context 節省原則

讀檔：只取需要的部分，不讀整份
- 要了解檔案結構 → 先 Grep 關鍵字找行號，再讀那幾行
- 非得看某段落 → offset+limit 控制在 30–50 行以內

寫入大檔：超過 150 行優先用 Edit（只傳 diff）取代 Write（傳整份）。寫完不要再 Read 驗證。

## 回覆原則與寫作規則

中文輸出禁止句子以「的」結尾，改用完整謂語結構。

中文句子必須保留完整的主詞＋動詞＋受詞結構，不可縮略謂語。
- 錯誤示例：「梯度強度分不清」→ 正確：「無法分清楚梯度強度」

數字/資料值作受詞時禁止話題化（受詞前移）：
- 錯誤：「14 GB 用掉」→ 正確：「已經用掉 14 GB」

子句不可省略主詞，每個子句都要有自己的主詞。

工具或指令名稱在純中文敘述句中，先用白話描述功能，原始名稱以括號補充。

程式碼名稱（函式、變數、類別等）原樣保留、不翻譯，第一次出現時用括號補白話說明。

回覆風格：
- 避免代名詞，直接描述事實或動作
- 預設只提供一個最佳解法，不列選項讓使用者挑
- 回答簡要，先講結論與重點，細節需要時再展開
- 每個說明點不超過 150 字；超過時拆成兩點，不得合併堆疊

## 實作前後的測試要求（嚴格執行，無例外）

動手前：先測試假說
- 提出假說後，先執行診斷測試確認假說成立，才動手修改程式碼
- 探索階段若要提供可行解法，先測試確認方案可執行，才向使用者回報
- 禁止在假說未經測試的前提下直接修改程式碼

確認假說後：等待使用者授權，才能動手
- 假說測試完成、找到可行修法後，必須先回報「根本原因是 X，建議修法是 Y」
- 等使用者明確說「好」「可以」「實作」「請實作」等授權語，才能開始寫入任何檔案
- 禁止在使用者授權前自行啟動實作，即使修法已確定、步驟已清楚

實作後：執行驗證，禁止目測代替執行
- 執行測試腳本或實際跑程式，印出關鍵數值確認結果
- 禁止在實作後測試通過前向使用者說「已完成」

## 自訂指令「請存檔」

當使用者說「請存檔」時，立刻執行：
1. 把這次對話裡值得長期保存的查詢/對照資料併入 {project_path}\\memory.md（去重、更新，不刪仍有效的舊資料）
2. 重寫 {project_path}\\STATE.md，只留「現況＋進行中＋下一步」；已完成或已搬進 memory.md 的資料一律剔除

執行完畢後，回覆實際寫入的兩個檔案完整路徑。

## 對話記憶規則

不要在記憶檔或對話裡使用「Last Session」這種自創英文標籤，一律改用白話中文描述。

## PDF 讀取規則

讀取或分析 .pdf 檔案時，一律先用 Bash 執行預處理腳本：
python C:\\Users\\yuchi\\.claude\\tools\\read_pdf.py "<PDF路徑>" [--pages 1-5]

## GitHub Pages 部署位置規則

部署靜態網站到 GitHub Pages 時，預設使用 main 分支根目錄，不使用 docs 資料夾或其他分支。

## 論文改寫句型規則

對話中提到 thesis-rewrite / 論文改寫 / 論文段落 / 學術寫作 時，先讀 C:\\Users\\yuchi\\.claude\\docs\\thesis-writing-rules.md 再回答。"""

    if history:
        thread = '\n'.join(f'使用者：{u}\n助理：{b}' for u, b in history)
        prompt = f'{context}\n\n{thread}\n\n使用者：{user_msg}' if context else f'{thread}\n\n使用者：{user_msg}'
    else:
        prompt = f'{context}\n\n使用者：{user_msg}' if context else user_msg

    def generate():
        full_lines = []
        tmp_path    = None
        sys_path    = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', encoding='utf-8', delete=False
            ) as f:
                f.write(prompt)
                tmp_path = f.name

            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', encoding='utf-8', delete=False
            ) as f:
                f.write(_SYSTEM)
                sys_path = f.name

            env = dict(os.environ)
            env['CLAUDE_SUBPROCESS'] = '1'
            env['PYTHONIOENCODING']  = 'utf-8'

            cmd = [
                'powershell', '-ExecutionPolicy', 'Bypass', '-Command',
                '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
                '$OutputEncoding = [System.Text.Encoding]::UTF8; '
                '$env:CLAUDE_SUBPROCESS = "1"; '
                f'$sys = Get-Content -Raw -Encoding UTF8 "{sys_path}"; '
                f'Get-Content -Raw -Encoding UTF8 "{tmp_path}" | '
                f'& claude --print --dangerously-skip-permissions --system-prompt $sys'
            ]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', env=env
            )
            active_procs[project] = proc

            for line in proc.stdout:
                full_lines.append(line.rstrip('\n\r'))
                yield f"data: {json.dumps({'t': line.rstrip(chr(13)) }, ensure_ascii=False)}\n\n"

            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()

            response_text = '\n'.join(l for l in full_lines if l).strip()
            if response_text:
                history.append((user_msg, response_text))
                if len(history) > 20:
                    history[:] = history[-20:]
                append_log_turn(project_path, user_msg, response_text)
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'t': f'[錯誤] {e}', 'done': True}, ensure_ascii=False)}\n\n"
        finally:
            active_procs.pop(project, None)
            for p in (tmp_path, sys_path):
                if p:
                    try: os.unlink(p)
                    except: pass
        yield 'data: [DONE]\n\n'

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/api/stop')
def stop_chat():
    project = request.json.get('project', '')
    proc = active_procs.get(project)
    if proc and proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=3)
        except: proc.kill()
        active_procs.pop(project, None)
        return jsonify({'ok': True, 'msg': '子進程已終止'})
    return jsonify({'ok': False, 'msg': '無進行中的請求'})


@app.post('/api/reset')
def reset_history():
    """清除某專案的 in-memory 歷史（拖出爐子時呼叫）"""
    project = request.json.get('project', '')
    chat_histories.pop(project, None)
    return jsonify({'ok': True})


@app.post('/api/spawn')
def spawn():
    d  = request.json
    project_path = os.path.join(CHANGES, d.get('project', ''))
    ps = r"C:\Users\yuchi\.claude\tools\spawn-project.ps1"
    cmd = ['powershell', '-ExecutionPolicy', 'Bypass', '-File', ps,
           '-ProjectName', d['project'], '-Task', d['task']]

    def generate():
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace'
            )
            for line in proc.stdout:
                text = line.rstrip('\n\r')
                if text:
                    yield f"data: {json.dumps({'t': text}, ensure_ascii=False)}\n\n"
            proc.wait()
            if proc.returncode == 0 and os.path.isdir(project_path):
                append_impl_marker(project_path)
            status = '✅ 子進程完成，STATE.md 已更新' if proc.returncode == 0 \
                     else f'❌ 子進程失敗 (exit {proc.returncode})'
            yield f"data: {json.dumps({'t': status, 'done': True}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'t': f'[錯誤] {e}', 'done': True}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


if __name__ == '__main__':
    print('Project Kitchen → http://localhost:7799')
    app.run(port=7799, debug=False)
