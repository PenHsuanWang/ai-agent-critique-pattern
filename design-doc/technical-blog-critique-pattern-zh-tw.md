# 超越單一代理人的侷限：深入解析 Generator–Critique 拮抗迴圈設計模式

> **作者按**：本文以實際開源專案 `ai-agent-critique-pattern`（FastAPI + Anthropic Claude SDK，v0.4.0）為基礎，系統性地解析「生成者—批評者」（Generator–Critique）多代理人架構的設計哲學、核心挑戰與結構性解法。文章對象為具備 Python 基礎、對 LLM 應用開發有一定認識的軟體工程師與 AI 系統架構師。

---

## 目錄

1. [前言：單一代理人的確認偏誤陷阱](#1-前言)
2. [ReAct 框架：思考—行動—觀察循環](#2-react-框架)
3. [Generator–Critique 拮抗模式概覽](#3-generator–critique-拮抗模式概覽)
4. [記憶體隔離：不可妥協的架構契約](#4-記憶體隔離)
5. [八大運行時陷阱與結構性解法](#5-八大運行時陷阱)
6. [Orchestrator 狀態機與生命週期管理](#6-orchestrator-狀態機)
7. [基礎架構三層設計](#7-基礎架構三層設計)
8. [關鍵程式碼模式解析](#8-關鍵程式碼模式解析)
9. [與主流框架的對比視角](#9-與主流框架的對比視角)
10. [適用場景與取捨分析](#10-適用場景與取捨分析)
11. [結語：把架構紀律化為預設行為](#11-結語)

---

## 1. 前言：單一代理人的確認偏誤陷阱

大語言模型（LLM）驅動的 AI Agent 已成為現代軟體架構的重要元素。然而，當任務對品質的要求足夠高時——例如技術文件撰寫、程式碼審查、法規遵循評估——單一代理人往往會掉入一個難以察覺的認知陷阱：**確認偏誤（Confirmation Bias）**。

這個問題的根源在於 LLM 的訓練目標。語言模型被訓練來補全「令人信服的」文字序列，而非「正確的」評估。當你要求同一個 Agent 既負責生成內容、又負責評估自己的產出時，模型的傾向是從已生成的草稿出發，尋找支持它的論據。正如 ReAct 論文所描述的，Agent 的推理軌跡會隨著訊息堆疊而被先前的上下文所錨定（anchoring）。

> *「讓 GPT-4 評估自己寫的程式碼，往往會得到比人工審查高出許多的分數。」*

這不是模型能力的問題，而是**角色衝突的結構性問題**。解決方案是將生成職責與評估職責分配給兩個完全隔離的 Agent，並以嚴格的狀態過濾器作為它們之間唯一的資訊橋樑。這就是 Generator–Critique 模式的核心思想。

---

## 2. ReAct 框架：思考—行動—觀察循環

在深入 Generator–Critique 模式之前，有必要先釐清兩個 Agent 各自的運作機制。本專案中兩個 Agent 均採用 **ReAct**（Reasoning + Acting）框架運作。

### 2.1 ReAct 迴圈結構

```
┌─────────────────────────────────────────────────────────────┐
│                     ReAct Agent 運作循環                      │
│                                                             │
│  System Prompt ──→ [思考 Thought]                           │
│                        │                                    │
│                        ▼                                    │
│                   [行動 Action]                              │
│                   tool_use block                            │
│                        │                                    │
│                        ▼                                    │
│                   [觀察 Observation]                         │
│                   tool_result block                         │
│                        │                                    │
│                        ▼                                    │
│                   下一輪思考 ──→ ... ──→ 最終回應              │
└─────────────────────────────────────────────────────────────┘
```

每一輪 API 呼叫都會將完整的訊息歷史傳給 LLM，形成累積的上下文窗口。這個特性帶來兩個重要含義：

1. **Agent 的工作記憶（Working Memory）受限於 context window**：無法讓同一個 Agent 「記住」無限多的歷史，也無法讓它長期保存跨次執行的狀態。
2. **訊息累積會造成上下文污染**：如果 Generator Agent 在第一輪的 ReAct 軌跡被送入 Critique Agent 的上下文，Critique Agent 的評估就會被 Generator 的推理邏輯所影響，破壞獨立性。

### 2.2 工具呼叫作為行動介面

兩個 Agent 均透過工具呼叫（Tool Use）來與外部世界互動。Generator Agent 可呼叫 `list_local_documents` 和 `read_local_document` 來查閱來源資料；Critique Agent 除了相同的文件工具外，還必須呼叫 `submit_critique` 作為評估的終止信號——這個工具是**強制的終止條件**，也是 Orchestrator 從評估迴圈中取得結構化結果的唯一途徑。

---

## 3. Generator–Critique 拮抗模式概覽

### 3.1 角色定義

| 角色 | 職責 | 系統提示核心原則 |
|------|------|-----------------|
| **Generator Agent** | 根據任務需求與批評意見產生或修訂草稿 | CRITICAL OUTPUT RULE：直接輸出內容，不得以對話式語氣包裝 |
| **Critique Agent** | 獨立評估草稿品質，識別問題，決定通過或要求修訂 | SCOPE BOUNDARY：只評估內容本身的問題，不重複已修正的問題，不超出任務範疇 |
| **Orchestrator** | 管理整個迴圈的狀態、記憶體隔離、中止條件與持久化 | 無 LLM，純 Python 狀態機邏輯 |

### 3.2 高層架構圖

```
客戶端
  │  POST /api/v1/critique
  │  { task, context_documents, max_iterations, enable_hitl }
  ▼
┌─────────────────────────────────────────────────────────────┐
│                    OrchestratorService                      │
│                                                             │
│  iteration=1,2,...,max_iterations                           │
│  ┌────────────┐   final_draft    ┌─────────────────────┐   │
│  │  Generator │ ──────────────── │  Critique Agent     │   │
│  │  Agent     │                  │  (隔離的 AgentSession│   │
│  │  (隔離的   │ ◄──────────────── │   )                 │   │
│  │   Agent    │  CritiqueResult  └─────────────────────┘   │
│  │  Session)  │  (只有 issues +   │                         │
│  └────────────┘   revision_notes │                         │
│                                  ▼                         │
│                   approved?  ──→ 返回最終結果               │
│                   否         ──→ 進入下一輪                  │
│                   達到上限?  ──→ HITL 暫停 或 強制終止       │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
PostgreSQL Checkpointer（持久化狀態）
ChromaDB Episodic Memory（向量化歷史評估）
```

### 3.3 跨邊界傳遞的資料契約

兩個 Agent 之間永遠只傳遞三個值：

```python
# Generator → Orchestrator
final_draft: str          # 純文字草稿，不含任何 ReAct 軌跡

# Orchestrator → Critique
task: str                 # 原始任務描述
current_draft: str        # 最新草稿

# Critique → Orchestrator（透過 submit_critique 工具）
@dataclass
class CritiqueResult:
    approved: bool
    issues: list[str]         # 具體問題列表
    revision_notes: str       # 修訂指引
    overall_score: int        # 0–10 評分

# Orchestrator → Generator（修訂輸入，透過 _build_revision_context() 狀態過濾器）
# 只有 issues + revision_notes 從 CritiqueResult 進入 Generator
# approved, overall_score 不傳遞
```

這個**嚴格的介面契約**（Interface Contract）是整個架構的靈魂。只要維持這個契約，兩個 Agent 的 ReAct 內部軌跡就永遠不會互相污染。

---

## 4. 記憶體隔離：不可妥協的架構契約

記憶體隔離是本架構中最重要、也最容易在演進中遭到侵蝕的設計原則。

### 4.1 三層記憶體矩陣

| 記憶體層次 | 範疇 | 生命週期 | 實作 |
|-----------|------|---------|------|
| **工作記憶（Working Memory）** | 每個 Agent 每次執行 | 單次 `run()` 呼叫結束即釋放 | `AgentSession.messages: list[dict]` |
| **會話記憶（Session Memory）** | 跨迭代的 Orchestrator 狀態 | 持續到任務完成或過期 | `OrchestratorState` + PostgreSQL |
| **長期語意記憶（Episodic Memory）** | 跨任務的歷史評估模式 | 永久保存，按語意檢索 | ChromaDB + sentence-transformers |

### 4.2 工作記憶的隔離實作

```python
# ✅ 正確做法：每次執行都建立全新的 AgentSession
class GeneratorAgentService:
    async def run(self, task: str, ...) -> str:
        session = AgentSession()   # 每次 run() 都是全新實例
        messages = self._build_initial_message(task, ...)
        # session 的 messages 只在此次 run() 範圍內存在
        ...

class CritiqueAgentService:
    async def run(self, task: str, current_draft: str, ...) -> CritiqueResult:
        session = AgentSession()   # 完全獨立，與 Generator 無任何共享
        ...
```

```python
# ❌ 危險做法：重用 Session 或跨 Agent 共享實例
class OrchestratorService:
    def __init__(self):
        self._shared_session = AgentSession()  # 絕對禁止！
```

### 4.3 狀態過濾器：唯一的跨邊界閘道

`OrchestratorService` 中的兩個方法是資料跨越 Agent 邊界的**唯一合法入口**：

```python
def _build_revision_context(
    self, state: OrchestratorState, critique: CritiqueResult
) -> str:
    """
    State Filter — 這是架構的絕對閘道。
    只有 issues 和 revision_notes 可以從 CritiqueResult 流向 Generator。
    overall_score、approved、Critique 的 ReAct 軌跡永遠不會進入此方法。
    """
    issues_text = "\n".join(f"- {issue}" for issue in critique.issues)
    return (
        f"REVISION REQUEST (Iteration {state.current_iteration + 1}):\n"
        f"The previous draft has the following issues:\n{issues_text}\n\n"
        f"REVISION GUIDANCE:\n{critique.revision_notes}\n\n"
        f"PREVIOUS DRAFT:\n{state.current_draft}"
        # ← 注意：critique.approved 和 critique.overall_score 不在此
    )
```

---

## 5. 八大運行時陷阱與結構性解法

在開發過程中，逐步識別並解決了八個常見的運行時失效模式。這些陷阱並非假設性的邊緣情況，而是在實際反覆測試中真實出現的問題。

### 陷阱 1：上下文污染（Context Pollution）

**症狀**：Critique Agent 在評估時引用了 Generator 的推理過程，或對 Generator 的工具呼叫結果進行評論，而非聚焦於草稿本身的品質。

**根因**：兩個 Agent 共享同一個 `AgentSession` 實例，導致訊息歷史互相可見。

**解法（Pattern 3 — Per-Iteration Isolation）**：
強制規定 `AgentSession` 永遠在 `run()` 方法頂部建立，任何路徑都不能繞過此規則。

---

### 陷阱 2：確認偏誤（Confirmation Bias）

**症狀**：Critique Agent 看到 Generator 提交的草稿時，因為看到了「Generator 認為草稿很好」的評估摘要而傾向於批准。

**根因**：Orchestrator 將 Generator 的最終評估或狀態資訊一起傳入 Critique 的輸入。

**解法（Pattern 2 — Clean Draft Delivery）**：
`_build_critique_input()` 只傳遞 `task` 和 `current_draft` 的純文字，不含任何 Generator 的自評或信心評分。

---

### 陷阱 3：生成器失憶症（Generator Amnesia）

**症狀**：在修訂迭代中，Generator 忘記了前一個草稿的內容，從頭開始生成，導致與批評意見毫無關聯的全新草稿。

**根因**：修訂輸入中只包含批評意見，沒有附上前一草稿。

**解法（Pattern 6 — Previous Draft Re-injection）**：
`_build_revision_context()` 永遠在訊息末尾附上完整的 `PREVIOUS DRAFT:` 區塊。

```python
# 修訂提示結構
return (
    f"REVISION REQUEST (Iteration {state.current_iteration + 1}):\n"
    f"... issues ...\n"
    f"... revision_notes ...\n"
    f"\nPREVIOUS DRAFT:\n{state.current_draft}"  # ← 這行至關重要
)
```

---

### 陷阱 4：生成器來源失憶症（Generator Source Amnesia）

**症狀**：在修訂過程中，Generator 基於記憶中的來源文件進行修改，而非重新查閱，導致在批評意見指出的具體段落中出現幻覺（Hallucination）。

**根因**：修訂提示沒有明確要求 Agent 重新查閱來源文件。

**解法（Pattern 6 extension）**：
在修訂提示中加入明確的指示：

```python
if state.current_iteration > 0:
    source_reminder = (
        "\nIMPORTANT: Before revising, re-read the source documents "
        "using the available tools to ensure factual accuracy. "
        "Do not rely on memory of the source content.\n"
    )
```

---

### 陷阱 5：批評者失憶症（Critique Amnesia）

**症狀**：Critique Agent 在第三輪仍然提出與第一輪相同的問題，而 Generator 早已在第二輪修正了那些問題。導致迴圈無法收斂。

**根因**：`CritiqueAgentService.run()` 沒有接收前一輪的評估結果。每一輪 Critique 都從零開始。

**解法（Pattern 8 — Previous Critique Injection）**：
在 `CritiqueAgentService.run()` 中加入 `previous_critique: CritiqueResult | None = None` 參數，並在評估請求中注入 PREVIOUS EVALUATION CONTEXT：

```python
def _build_evaluation_request(
    self,
    task: str,
    current_draft: str,
    previous_critique: CritiqueResult | None,
) -> str:
    prompt = f"TASK:\n{task}\n\nDRAFT TO EVALUATE:\n{current_draft}"

    if previous_critique:
        # 注入先前評估的問題，提醒 Critique Agent 哪些已被處理
        prev_issues = "\n".join(f"- {i}" for i in previous_critique.issues)
        prompt += (
            f"\n\nPREVIOUS EVALUATION CONTEXT:\n"
            f"In the previous iteration, you identified these issues:\n"
            f"{prev_issues}\n"
            f"Focus your evaluation on whether these have been addressed "
            f"and any NEW issues in the revised draft."
        )
    return prompt
```

---

### 陷阱 6 & 7：對話式前言混亂與偽批評拒絕

**對話式前言混亂（Conversational Preamble Chaos）**：
**症狀**：Generator 的輸出前面帶著「好的，以下是我為您撰寫的文章：」這類對話式語氣，而非直接輸出草稿內容。

**解法**：在 Generator 的系統提示最頂部加入強制規則：
```
CRITICAL OUTPUT RULE: Your response MUST be the requested content itself.
Do NOT begin with phrases like "Here is...", "Certainly!", "Below you'll find...".
Output the content directly with zero preamble.
```

**偽批評拒絕（False Critique Rejection）**：
**症狀**：Critique Agent 拒絕通過草稿，理由是「缺少我認為應該包含的章節」，但那些章節並不在原始任務要求中。

**解法**：在 Critique 的系統提示中加入範疇邊界：
```
SCOPE BOUNDARY: Only evaluate the draft against the explicit requirements
in the TASK. Do not penalize for missing elements that were not requested.
Do not re-raise issues that have already been addressed in this revision.
```

---

### 陷阱 8：工具呼叫失控螺旋（Runaway Tool Spirals）

**症狀**：Generator Agent 陷入無限的工具呼叫迴圈，重複查閱同一份文件，消耗大量 Token 但沒有產出草稿。

**解法**：透過設定可配置的上限強制終止：
```python
# .env 設定
GENERATOR_MAX_TOOL_CALLS=15
CRITIQUE_MAX_TOOL_CALLS=10
```

```python
# 在 ReAct 迴圈內強制中止
if tool_call_count >= settings.generator_max_tool_calls:
    # 注入強制終止訊息
    messages.append({
        "role": "user",
        "content": "MAX_TOOL_CALLS reached. You MUST now produce the final draft."
    })
```

---

## 6. Orchestrator 狀態機

`OrchestratorState` 是整個系統的中樞，管理迴圈的推進與暫停。

### 6.1 狀態生命週期

```
pending
  │
  ▼
running ──→ (每輪迭代)
  │
  ├──→ success               # Critique 批准，任務完成
  ├──→ max_iterations_reached # 達到上限，強制終止（未啟用 HITL）
  ├──→ paused_for_hitl       # 達到上限，等待人工介入（已啟用 HITL）
  └──→ error                 # 不可恢復的例外
```

### 6.2 HITL 暫停與恢復流程

當任務啟用 `enable_hitl=true` 且達到 `max_iterations` 時，狀態機進入 `paused_for_hitl` 狀態，保存完整的 `OrchestratorState` 到 PostgreSQL，並將評審 URL 回傳給客戶端。

```bash
# 暫停後，人工審查者可以：

# 選項 A：批准最後一個草稿
POST /api/v1/sessions/{session_id}/resume
{
  "action": "approve",
  "reviewer_comment": "符合要求，品質足夠。"
}

# 選項 B：提供額外修訂指引後繼續
POST /api/v1/sessions/{session_id}/resume
{
  "action": "revise",
  "reviewer_comment": "請特別加強第三節的技術細節。",
  "additional_iterations": 2
}
```

---

## 7. 基礎架構三層設計

### 7.1 PostgreSQL Checkpointer：跨請求狀態持久化

`PostgreSQLOrchestratorStore` 使用 asyncpg 實作，自動建立 `orchestrator_sessions` 資料表：

```sql
CREATE TABLE IF NOT EXISTS orchestrator_sessions (
    session_id TEXT PRIMARY KEY,
    state      TEXT NOT NULL,      -- OrchestratorState.to_dict() 的 JSON 序列化
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**關鍵設計決策**：狀態欄位使用 `TEXT` 而非 `JSONB`。原因是 asyncpg 的 JSONB codec 需要額外的型別註冊程序，而 TEXT 可以直接 `json.dumps()` / `json.loads()`，在 Python 端完成序列化，無需 asyncpg JSONB codec 設定，降低了環境複雜度。

### 7.2 向量情節記憶（Episodic Memory）

當 `VECTOR_MEMORY_ENABLED=true` 時，每次迭代的評估結果會被向量化儲存到 ChromaDB：

```python
# 儲存情節（每次評估後）
await self._episodic_memory.store_episode(
    task=state.task,
    draft_summary=state.current_draft[:500],  # 截斷，避免向量過長
    critique_result=critique,
    iteration=state.current_iteration,
)

# 在 Critique Agent 的工具中查詢相似歷史
async def retrieve_similar_critiques(task_description: str, **kwargs):
    episodes = await memory_store.retrieve_similar(
        query=task_description,
        top_k=3,
        only_failed=True,  # 只取歷史失敗案例，避免重蹈覆轍
    )
    return format_episodes_for_prompt(episodes)
```

這個機制讓 Critique Agent 能夠跨任務地積累評估智慧：當它評估一篇技術文章時，它可以查詢到過去類似任務中哪些問題模式最常出現，從而更精準地識別潛在缺陷。

### 7.3 開發環境降級策略

三個基礎架構組件均實作了 **Graceful Degradation（優雅降級）** 機制：

| 組件 | 生產環境 | 開發環境（未設定依賴） |
|------|---------|---------------------|
| 狀態持久化 | PostgreSQL（asyncpg） | InMemoryOrchestratorStore |
| 情節記憶 | ChromaDB（PersistentClient） | 直接跳過 `store_episode()` |
| HITL | 需要 PostgreSQL | 降級為 `max_iterations_reached` |

```python
# main.py lifespan — 依環境按需注入
async def lifespan(app: FastAPI):
    pool = None
    if settings.database_url:
        pool = await asyncpg.create_pool(settings.database_url)
        store = PostgreSQLOrchestratorStore(pool)
    else:
        store = InMemoryOrchestratorStore()   # 開發模式降級

    orchestrator_service.set_checkpointer(store)

    if settings.vector_memory_enabled:
        episodic = EpisodicMemoryStore(...)
        orchestrator_service.set_episodic_memory(episodic)
    # 若不啟用，episodic memory 保持 None，相關呼叫為 no-op
```

---

## 8. 關鍵程式碼模式解析

### 8.1 Pattern 1：Per-Run Closure Factory（每次執行的閉包工廠）

`submit_critique` 工具是 Critique Agent 宣告評估完成的唯一方式。它的處理器透過工廠函式動態建立，確保每次 `run()` 呼叫都有專屬的結果容器，不會發生跨呼叫的狀態洩漏：

```python
def make_submit_critique_handler(result_holder: list) -> Callable:
    """
    閉包工廠 — 每次 CritiqueAgentService.run() 呼叫都建立獨立的閉包。
    result_holder 是一個單元素列表，作為可變容器傳入閉包。
    """
    def submit_critique_handler(
        approved: bool,
        issues: list[str],
        revision_notes: str,
        overall_score: int,
    ) -> str:
        result_holder.append(
            CritiqueResult(
                approved=approved,
                issues=issues,
                revision_notes=revision_notes,
                overall_score=overall_score,
            )
        )
        return "Critique submitted successfully."
    return submit_critique_handler


# 在 run() 中使用：
async def run(self, task: str, current_draft: str, ...) -> CritiqueResult:
    result_holder: list[CritiqueResult] = []
    submit_handler = make_submit_critique_handler(result_holder)

    # 動態注入工具
    tool_registry = {**CRITIQUE_BASE_TOOL_REGISTRY, "submit_critique": submit_handler}

    # ... ReAct 迴圈 ...

    if not result_holder:
        raise CritiqueLoopError("Critique agent did not call submit_critique.")
    return result_holder[0]
```

### 8.2 Pattern 4：序列化契約（Serialisation Contract）

`OrchestratorState` 的 `to_dict()` / `from_dict()` 方法確保狀態可以安全地在 Python 物件與 PostgreSQL TEXT 之間往返轉換，且不依賴任何 ORM：

```python
@dataclass
class OrchestratorState:
    session_id: str
    task: str
    status: str
    current_iteration: int
    max_iterations: int
    current_draft: str | None
    critiques: list[CritiqueResult]
    # ...

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "task": self.task,
            "status": self.status,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "current_draft": self.current_draft,
            "critiques": [
                {
                    "approved": c.approved,
                    "issues": c.issues,
                    "revision_notes": c.revision_notes,
                    "overall_score": c.overall_score,
                }
                for c in self.critiques
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OrchestratorState":
        data["critiques"] = [CritiqueResult(**c) for c in data.get("critiques", [])]
        return cls(**data)
```

### 8.3 Pattern 5：依賴注入（DI via Setters）

服務層透過 setter 方法接收基礎架構依賴，而非在建構子中硬編碼：

```python
class OrchestratorService:
    def __init__(self):
        self._checkpointer: OrchestratorStore | None = None
        self._episodic_memory: EpisodicMemoryStore | None = None

    def set_checkpointer(self, store: OrchestratorStore) -> None:
        self._checkpointer = store

    def set_episodic_memory(self, store: EpisodicMemoryStore) -> None:
        self._episodic_memory = store

    async def _checkpoint(self, state: OrchestratorState) -> None:
        if self._checkpointer:  # 若未注入，直接 no-op
            await self._checkpointer.save(state)
```

這個模式讓單元測試可以輕易地注入 Mock 物件，同時保持生產環境中的彈性配置。

---

## 9. 與主流框架的對比視角

在設計本架構時，參考了三個主流多代理人框架的記憶體隔離策略：

| 框架 | 隔離機制 | 特點 |
|------|---------|------|
| **LangGraph** | 子圖（Subgraph）的私有 `TypedDict` 狀態 | 透過圖結構天然隔離，但需要學習 Graph API |
| **Mastra** | Thread ID 隔離 | 以不同 threadId 建立對話執行緒，簡單直接 |
| **Google ADK** | `EscalationContext` 傳遞 | 強調明確的升級（Escalation）路徑 |
| **本架構** | Per-run `AgentSession` + State Filter | 以 Python dataclass 實作，無框架依賴 |

本架構的優勢在於**零框架依賴**：整個隔離機制完全由 Python dataclass 和函式設計實現，不需要引入 LangGraph 或 Mastra 的 DSL。這使得架構更容易被理解、調試和遷移。

---

## 10. 適用場景與取捨分析

### 10.1 適合使用 Generator–Critique 模式的場景

- **高品質文件生成**：技術規格書、API 文件、學術報告
- **程式碼審查自動化**：讓 Generator 輸出程式碼，Critique 驗證安全性與架構合規性
- **法規遵循評估**：需要確保輸出符合特定規範（例如 GDPR 隱私政策審查）
- **多輪迭代創作**：需要逐步收斂至高品質輸出的創意寫作或提案撰寫

### 10.2 不適合使用的場景

- **低延遲需求**：每個迭代都需要兩次 LLM API 呼叫，延遲明顯高於單一 Agent
- **簡單查詢回答**：若任務沒有「品質評估」的需求，引入 Critique Agent 是過度設計
- **成本敏感場景**：每次迭代的 Token 消耗約為單一 Agent 的 2–3 倍

### 10.3 成本與品質的平衡策略

```python
# 建議的 max_iterations 配置策略：
# - 探索性草稿（允許品質較低）：max_iterations=1
# - 標準品質輸出：max_iterations=2-3
# - 高品質關鍵文件：max_iterations=3-5（搭配 HITL）

# 透過 Extended Thinking 強化 Generator 品質，減少所需迭代次數
EXTENDED_THINKING=true
THINKING_BUDGET_TOKENS=10000
GENERATOR_MAX_TOKENS=16000  # 必須 > THINKING_BUDGET_TOKENS
```

---

## 11. 結語：把架構紀律化為預設行為

Generator–Critique 模式的本質，是將**認知分工原則（Cognitive Division of Labor）**從人類協作流程移植到 AI Agent 系統設計中。一個能夠同時生成與評估的萬能 Agent 在語言層面是可行的，但在認知結構上是脆弱的——它缺乏真正的對抗性張力（Antagonistic Tension）。

本文所介紹的八個陷阱，都是在這個系統被反覆真實測試後逐步浮現的。它們不是邊緣案例，而是在 LLM 的統計特性與有限上下文窗口的交互作用下幾乎必然出現的問題。架構師的工作，是在系統設計層面將這些問題的解法**固化為預設行為**，而非依賴 Prompt Engineering 的臨時補丁。

> 記憶體隔離不是優化選項，而是多代理人系統的基本衛生。

對於計畫在生產環境中部署 LLM 多代理人系統的工程師，以下三點是最重要的提醒：

1. **永遠不要讓 Agent 評估自己的輸出**：確認偏誤是統計必然，不是偶發的模型失誤。
2. **狀態過濾器是隔離邊界的守門人**：所有跨 Agent 的資料傳遞必須通過顯式的過濾層，而非隱式的物件共享。
3. **工具呼叫上限必須作為架構配置存在**：Tool Use 迴圈的失控是實際觀察到的現象，而非理論上的風險。

完整的參考實作位於 [ai-agent-critique-pattern](https://github.com/PenHsuanWang/ai-agent-critique-pattern)，包含 HANDBOOK.md（v0.4.0）與完整的原始架構設計文件（繁體中文）。

---

*本文基於 ai-agent-critique-pattern v0.4.0（2025年），採用 FastAPI + Anthropic Claude SDK 實作。所有程式碼範例均為實際生產程式碼的簡化版本，完整實作請參考原始碼庫。*
