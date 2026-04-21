# SARA — Product Requirements Document

## Personalized AI Desktop Automation Copilot (Phase II)

**Version:** 1.1 — Demo-Submission Build (Voice + Live Automation Override)  
**Date:** 2026-04-19  
**Author:** Hussain S.  
**Status:** Implementation-Ready (Override Applied)

---

## 1. Executive Summary

SARA (Self-healing Automation with Reasoning and Adaptation) is a personalized AI desktop automation system that combines the Automation Tree research framework with a conversational AI copilot. The project report (xerox.docx) describes the complete system. The current codebase (`src/`) contains only the research/experiment layer. This PRD defines exactly what must be built, adapted, or removed to produce a fully running end-to-end demo by EOD.

### 1.1 Tomorrow Demo Priority Override

The following items are now mandatory for the demo and override earlier lower-scope assumptions:

1. Always-on control widget must remain available on screen for user interaction.
2. Voice wake-word path must work in live mode: "Hey SARA" -> wake -> listen -> execute.
3. Browser automation and Windows app automation are both critical pass criteria.
4. Demo critical path must execute through exposure paths + AX + verification, without depending on VLM fallback.
5. Agent must run in an agentic step loop: execute step, verify result, then continue/replan.

---

## 2. Gap Analysis: Project Report vs Current Codebase

### 2.1 What the Project Report Claims Exists

| Module (per report §5.15)   | Lines         | Status in Codebase                                               | Priority |
| --------------------------- | ------------- | ---------------------------------------------------------------- | -------- |
| `host_agent.py`             | ~850          | ❌ MISSING                                                       | P0       |
| `knowledge_base_manager.py` | ~310          | ❌ MISSING                                                       | P0       |
| `llm_service.py`            | ~380          | ⚠️ PARTIAL (`src/llm/llm_client.py` exists but differs)          | P0       |
| `automation_tree.py`        | ~1200         | ⚠️ SPLIT across `src/automation/` — not unified                  | P0       |
| `app_agents/` (6 agents)    | ~200-400 each | ❌ MISSING                                                       | P0       |
| `config.py`                 | ~120          | ⚠️ PARTIAL (`src/harness/config.py` exists but is research-only) | P1       |
| PyQt5 chat widget UI        | —             | ❌ MISSING                                                       | P0       |
| `voice_service.py`          | ~420          | ❌ MISSING (wake word + STT/TTS orchestration)                   | P0       |
| `exposure_path_planner.py`  | ~280          | ✅ EXISTS as `src/automation/execution_planner.py`               | ADAPT    |
| `ax_executor.py`            | ~350          | ✅ EXISTS as `src/harness/ax_executor.py`                        | REUSE    |
| Privacy Router              | —             | ❌ MISSING                                                       | P0       |
| `demo.py` entry point       | —             | ❌ MISSING                                                       | P0       |

### 2.2 What Exists in Codebase but is NOT in Report

These files are the research/experiment infrastructure. **DO NOT MODIFY OR DELETE.**

| File                                  | Purpose                    | Action            |
| ------------------------------------- | -------------------------- | ----------------- |
| `src/automation/builder.py`           | Tree construction from UIA | REUSE as-is       |
| `src/automation/storage.py`           | JSON cache persistence     | REUSE as-is       |
| `src/automation/fingerprint.py`       | SHA-256 fingerprinting     | REUSE as-is       |
| `src/automation/matcher.py`           | Weighted element scoring   | REUSE as-is       |
| `src/automation/prober.py`            | BFS UI probing             | REUSE as-is       |
| `src/automation/execution_planner.py` | Exposure path execution    | REUSE as-is       |
| `src/harness/main.py`                 | Harness orchestration      | REUSE as-is       |
| `src/harness/app_controller.py`       | App lifecycle              | REUSE as-is       |
| `src/harness/ax_executor.py`          | AX execution               | REUSE as-is       |
| `src/harness/verification.py`         | State verification         | REUSE as-is       |
| `src/harness/vision_executor.py`      | VLM fallback               | REUSE as-is       |
| `src/harness/vlm_provider.py`         | VLM provider               | REUSE as-is       |
| `src/harness/locator.py`              | Element locator            | REUSE as-is       |
| `src/llm/llm_client.py`               | Gemini/Claude key pool     | REUSE as-is       |
| `src/llm/orchestrator.py`             | LLM plan/execute loop      | REUSE via wrapper |
| `src/llm/step_executor.py`            | Action type translation    | REUSE as-is       |
| `scripts/scientific_mass_test.py`     | Research runner            | DO NOT TOUCH      |
| `scripts/scientific_llm_test.py`      | Research runner            | DO NOT TOUCH      |
| `run_validation_experiment.py`        | Experiment driver          | DO NOT TOUCH      |
| `results/`                            | Validated results          | DO NOT TOUCH      |

### 2.3 What Must Be Built (The Delta)

```
MUST BUILD TODAY:
sara/
  __init__.py                    → Package init
  config.py                      → Unified config (wraps src/harness/config.py)
  privacy_router.py              → Keyword sensitivity classifier
  llm_service.py                 → Gemini API wrapper (intent, plan, facts, chat)
  knowledge_base_manager.py      → ChromaDB + SBERT + JSON facts dual memory
  host_agent.py                  → Central orchestrator brain
  voice_service.py               → LIVE wake-word + STT/TTS service with push-to-talk fallback
  app_agents/
    __init__.py
    base_agent.py
    notepad_agent.py
    calculator_agent.py
    excel_agent.py
    chrome_agent.py
    brave_agent.py
    spotify_agent.py
  ui/
    __init__.py
    chat_widget.py               → PyQt5 demo window
    styles.py                    → Dark theme CSS

demo.py                          → Single entry point
requirements_demo.txt            → New deps only
.env.example                     → API key template
DEMO_SCRIPT.md                   → Evaluator demonstration guide
sara_memory/                     → Auto-created at runtime
  facts.json
  chroma/
```

---

## 3. Functional Requirements

### FR-1: Automation Tree Execution (MUST WORK)

- **FR-1.1** System must execute tasks through the existing `src/` harness pipeline
- **FR-1.2** Demo critical execution path: Cache Planner → AX Executor → Verification (Vision disabled by default)
- **FR-1.3** Exposure path traversal must work for Notepad (100% success validated)
- **FR-1.4** Self-healing must trigger on locator failure (already in `src/automation/execution_planner.py`)
- **FR-1.5** Results must show 77.6% baseline matching the paper numbers
- **FR-1.6** Each plan step must be verified before proceeding to the next step
- **FR-1.7** Browser commands must execute via deterministic exposure-path/hotkey flows (open tab, focus bar, search, open result)

### FR-2: LLM Orchestration (MUST WORK)

- **FR-2.1** Gemini 1.5 Flash must generate structured JSON execution plans from NL commands
- **FR-2.2** Intent classification: automation / remember / screen_read / conversation
- **FR-2.3** Plan format: `[{"action": "CLICK", "target": "File"}, ...]`
- **FR-2.4** Graceful fallback to heuristic rules when API key absent
- **FR-2.5** Plan must be executed through `src/llm/orchestrator.py` when live mode enabled

### FR-3: Dual-Memory System (MUST WORK)

- **FR-3.1** Structured JSON fact store: O(1) exact-key lookup
- **FR-3.2** ChromaDB semantic store: cosine-similarity retrieval via Sentence-BERT
- **FR-3.3** Facts persist across sessions (written to `sara_memory/facts.json`)
- **FR-3.4** Semantic interactions indexed after every command completion
- **FR-3.5** Recall returns top-2 relevant memories injected into LLM context
- **FR-3.6** Memory shown live in UI memory tab

### FR-4: Privacy Routing (MUST WORK)

- **FR-4.1** Keyword classifier intercepts every command before LLM processing
- **FR-4.2** HIGH sensitivity → LOCAL route (no cloud API call for plan generation)
- **FR-4.3** LOW sensitivity → CLOUD route (Gemini 1.5 Flash)
- **FR-4.4** Routing decision visible in UI with 🔒 / ☁️ badge
- **FR-4.5** Sensitive keywords include: password, bank, medical, personal, private, ssn, credit

### FR-5: AppAgent Architecture (MUST DEMO)

- **FR-5.1** Six AppAgents: Notepad, Calculator, Excel, Chrome, Brave, Spotify
- **FR-5.2** Each agent provides: `get_ui_summary()`, `get_pre_seeded_paths()`, `get_common_tasks()`
- **FR-5.3** Active AppAgent selected via UI dropdown
- **FR-5.4** AppAgent info panel shows per-app known tasks and UI structure
- **FR-5.5** Electron limitation warning shown for Chrome, Brave, Spotify
- **FR-5.6** Browser AppAgents must expose high-confidence demo macros (YouTube search/play, open URL, tab control)

### FR-6: PyQt5 Chat UI (MUST WORK)

- **FR-6.1** Dark-themed chat window with user/SARA message bubbles
- **FR-6.2** Privacy route badge (🔒 LOCAL / ☁️ CLOUD) on every SARA response
- **FR-6.3** Intent badge (AUTOMATION / REMEMBER / CONVERSATION) visible
- **FR-6.4** Execution Plan tab shows LLM-generated steps in real time
- **FR-6.5** Memory tab shows live fact store and semantic memory count
- **FR-6.6** AppAgents tab shows current agent info and known tasks
- **FR-6.7** System Status tab shows execution stats and tier usage
- **FR-6.8** App selector dropdown to change active application
- **FR-6.9** Dry-run toggle to generate plans without executing
- **FR-6.10** Quick demo buttons pre-load common demo commands
- **FR-6.11** Background thread for all AI/execution calls (UI must never freeze)

### FR-7: Voice Service (LIVE FOR DEMO)

- **FR-7.1** `VoiceService` class must exist and be importable
- **FR-7.2** Wake-word listener must detect "Hey SARA" and trigger command capture
- **FR-7.3** Voice command capture must transcribe and dispatch commands to HostAgent
- **FR-7.4** `speak(text)` must provide audible or visible response feedback (TTS preferred, text fallback allowed)
- **FR-7.5** Push-to-talk fallback must be available if wake-word backend is temporarily unavailable

### FR-8: Demo Entry Point (MUST WORK)

- **FR-8.1** `python demo.py` launches PyQt5 GUI
- **FR-8.2** `python demo.py --cli` falls back to text REPL
- **FR-8.3** `python demo.py --test` runs automated feature verification
- **FR-8.4** `python demo.py --live` enables real Windows automation execution
- **FR-8.5** All paths must work without crashing on missing optional dependencies
- **FR-8.6** `python demo.py --widget` launches compact always-on-top control widget mode

---

## 4. Non-Functional Requirements

### NFR-1: Reliability

- System must not crash if GEMINI_API_KEY is missing (use heuristic fallback)
- System must not crash if ChromaDB/SBERT not installed (use list-based fallback)
- System must not crash if PyQt5 not installed (fall back to CLI mode)
- All imports wrapped in try/except with informative warnings

### NFR-2: Demo Performance

- UI response to text input: < 500ms before background thread starts
- LLM plan generation: < 5 seconds (Gemini Flash)
- Memory recall: < 100ms (ChromaDB local)
- GUI must remain responsive during all async operations

### NFR-3: Code Quality

- All sara/ modules must have docstrings referencing the relevant project report section
- All sara/ modules must have type hints on public functions
- Logging must use Python `logging` module (not print statements)
- No hardcoded API keys anywhere

### NFR-4: Compatibility

- Python 3.10+
- Windows 11 (for live automation), but demo features work on any OS
- Primary demo path assumes microphone availability; push-to-talk text fallback required

---

## 5. Scope Boundaries

### IN SCOPE (Build Today)

- Everything in the `sara/` directory tree listed in §2.3
- `demo.py` entry point with all required modes (`--live`, `--cli`, `--test`, `--widget`)
- `requirements_demo.txt` and `.env.example`
- `DEMO_SCRIPT.md`
- Always-on-top widget mode
- Wake-word + voice command path in live mode
- Browser automation demo flow without VLM in critical path

### OUT OF SCOPE (Do Not Build)

- Ollama local Gemma:2B (requires model download, GPU)
- macOS / Linux automation (project report says Windows only)
- Production authentication / multi-user support

### DEMO WORKAROUNDS (Approved Substitutions)

| Report Feature                     | Demo Substitute                    | Why Acceptable                               |
| ---------------------------------- | ---------------------------------- | -------------------------------------------- |
| Wake word backend instability      | Push-to-talk voice button          | Keeps live spoken-command flow intact        |
| Temporary STT service outage       | Text command input in widget       | Preserves execution path and demo continuity |
| TTS outage                         | On-screen + console response       | Preserves agent feedback channel             |
| Local Gemma:2B                     | Heuristic keyword classifier       | Demonstrates privacy routing decision logic  |
| AX step failure on unprobed screen | Trigger discovery/probe then retry | Maintains exposure-path-first methodology    |

---

## 6. Technology Stack (Final)

| Layer            | Technology                     | Version | Source           |
| ---------------- | ------------------------------ | ------- | ---------------- |
| Core Automation  | pywinauto                      | 0.6.x   | existing `.venv` |
| Input Simulation | pyautogui                      | 0.9.x   | existing `.venv` |
| LLM (Cloud)      | Google Gemini 1.5 Flash        | via API | NEW              |
| UI Framework     | PyQt5                          | 5.15.x  | NEW              |
| Vector DB        | ChromaDB                       | 0.4.x+  | NEW              |
| Embeddings       | Sentence-BERT all-MiniLM-L6-v2 | 2.2.x   | NEW              |
| Env vars         | python-dotenv                  | 1.0.x   | NEW              |
| Logging          | Python stdlib logging          | —       | stdlib           |
| Storage          | JSON + SHA-256                 | —       | stdlib           |

---

## 7. Module Interface Contracts

### 7.1 `sara.privacy_router.PrivacyRouter`

```python
route(command: str) -> Tuple[str, PrivacySensitivity]
classify(command: str) -> PrivacySensitivity
get_routing_explanation(command: str) -> str
```

### 7.2 `sara.llm_service`

```python
get_intent(command, memory_context, use_local) -> Dict[intent, confidence]
get_automation_plan(command, active_app, ui_summary, context) -> List[Dict]
extract_facts(command) -> Dict
get_conversational_response(command, context) -> str
```

### 7.3 `sara.knowledge_base_manager.KnowledgeBaseManager`

```python
update_structured_facts(new_facts: Dict) -> None
get_structured_facts() -> Dict
get_fact(key: str) -> Optional[Any]
store_interaction(command, outcome, intent) -> None
recall_memories(query, num_results=2) -> List[str]
get_memory_summary() -> Dict
```

### 7.4 `sara.host_agent.HostAgent`

```python
__init__(dry_run=True)
process_command(command: str) -> CommandResult
set_active_app(app_name: str) -> None
get_memory_summary() -> Dict
get_history() -> List[Dict]
get_routing_explanation(command: str) -> str
```

### 7.5 `sara.app_agents.BaseAppAgent`

```python
get_ui_summary() -> str
get_pre_seeded_paths() -> Dict[str, List[Dict]]
get_common_tasks() -> List[str]
validate_preconditions() -> bool
get_description() -> str
```

---

## 8. Data Models

### 8.1 CommandResult (from host_agent.py)

```python
{
  "command": str,
  "intent": "automation|remember|screen_read|conversation",
  "privacy_route": "LOCAL|CLOUD",
  "sensitivity": "HIGH|MEDIUM|LOW",
  "plan": [{"action": str, "target": str, ...}],
  "execution_success": bool,
  "response_text": str,
  "memory_recalled": [str],
  "facts_stored": {str: Any},
  "app_agent": str,
  "tier_used": str,
  "error": Optional[str]
}
```

### 8.2 Automation Plan Step

```python
{
  "action": "CLICK|TYPE|HOTKEY|LAUNCH|WAIT|SCROLL",
  "target": str,   # for CLICK
  "value": str,    # for TYPE, HOTKEY
  "app": str,      # for LAUNCH
  "ms": int        # for WAIT
}
```

### 8.3 Memory Fact Store (`sara_memory/facts.json`)

```json
{
  "name": "Hussain",
  "occupation": "CSE student",
  "preferred_editor": "Notepad",
  "university": "MGR Educational and Research Institute"
}
```

---

## 9. Success Criteria for Demo

| Criterion               | Pass Condition                                                           |
| ----------------------- | ------------------------------------------------------------------------ |
| GUI launches            | `python demo.py` opens dark-themed window without errors                 |
| Privacy routing         | "password" command shows 🔒 LOCAL, "what is AI" shows ☁️ CLOUD           |
| Intent classification   | "open Notepad" → automation, "my name is X" → remember                   |
| Memory storage          | Fact stored after "remember" command, visible in Memory tab              |
| Memory recall           | Second command recalls first stored fact in context                      |
| Plan generation         | Automation command generates ≥2 steps in Plan tab                        |
| AppAgent switching      | Dropdown changes agent info in AppAgents tab                             |
| Wake word               | "Hey SARA" triggers listening indicator and captures command             |
| Live Notepad automation | Spoken Notepad command executes end-to-end without manual clicks         |
| Live browser automation | Spoken browser command opens/searches/plays target without manual clicks |
| No-VLM critical path    | Demo run completes with vision disabled for the primary scenarios        |
| CLI mode                | `python demo.py --cli` enters REPL without errors                        |
| Feature test            | `python demo.py --test` shows ≥5/6 tests passed                          |

---

## 10. Risk Register

| Risk                             | Likelihood | Mitigation                                                             |
| -------------------------------- | ---------- | ---------------------------------------------------------------------- |
| GEMINI_API_KEY missing           | Medium     | Heuristic fallback with clear warning                                  |
| ChromaDB sqlite3 version error   | Medium     | pysqlite3-binary workaround in code                                    |
| SBERT first download slow        | High       | Pre-download command in setup section                                  |
| PyQt5 display issue (DPI)        | Low        | `QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)`                |
| Wake-word false triggers/noise   | Medium     | Confidence threshold + push-to-talk fallback + visible listening state |
| Browser AX instability           | High       | Pre-demo probing + pre-seeded browser macros + keyboard-first backups  |
| src/ import fails on non-Windows | High       | Wrap all src/ imports in try/except; auto-enable dry_run               |
| Gemini rate limit during demo    | Low        | Fallback responses cached in memory system                             |
