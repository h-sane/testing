# SARA Product Specification (Presentation Edition)

Version: 1.0  
Date: 2026-04-20  
Product: SARA (Self-healing Automation with Reasoning and Adaptation)

## 1. Executive Summary

SARA is a desktop AI copilot for Windows automation that combines:

- conversational command understanding,
- privacy-aware prompt processing,
- persistent user memory,
- deterministic Automation Tree execution (cache + accessibility + verification),
- optional voice interaction (wake word + push-to-talk),
- and a crawler onboarding workflow for adding new executable apps.

The current implementation is designed for real-time demonstration and practical operator control. It supports full UI mode, compact always-on-top widget mode, CLI mode, and local HTTP API mode.

## 2. Product Vision and Goals

### 2.1 Vision

Deliver a reliable desktop automation copilot that can translate natural language commands into verified UI actions across multiple applications, while preserving safety and observability.

### 2.2 Product Goals

- Execute practical desktop actions with deterministic, verifiable behavior.
- Keep operators in control through visible progress, dry-run mode, and approval gates for risky actions.
- Provide continuity through persistent memory and media-session awareness.
- Make app onboarding scalable via executable-first crawler registration and probing.
- Offer multiple interaction surfaces for different contexts: full UI, widget, CLI, API.

### 2.3 Non-Goals (Current Scope)

- Full autonomous operation on unknown, unprobed apps without onboarding.
- Cross-platform (macOS/Linux) desktop automation parity.
- Cloud/backend multi-tenant deployment; current API is local-first.

## 3. Target Users and Use Cases

### 3.1 Primary Users

- Product demo operators and evaluators.
- Automation engineers validating desktop task reliability.
- Power users seeking command-driven workflow acceleration.

### 3.2 Core Use Cases

- Run command-driven automation in Notepad, browser, Office, media apps, and utilities.
- Onboard a new executable from the crawler tab and immediately automate it.
- Control SARA by text, widget, wake word, or API.
- Store and recall user preferences/facts across sessions.
- Expose live execution traces for debugging and presentation.

## 4. Product Scope and Runtime Modes

SARA entrypoint: `demo.py`

Supported modes:

- `python demo.py`: full chat UI (dry-run by default).
- `python demo.py --live`: full chat UI with real execution enabled.
- `python demo.py --widget`: compact always-on-top control widget.
- `python demo.py --cli`: terminal REPL mode.
- `python demo.py --api`: run local API server alongside UI/CLI.
- `python demo.py --api-only`: local API server only.
- `python demo.py --test`: smoke checks for core routing behavior.
- `python demo.py --preflight`: environment and readiness checks.

## 5. System Architecture

### 5.1 High-Level Layers

1. Interaction layer

- Chat UI (`sara/ui/chat_widget.py`)
- Widget UI (`sara/ui/widget.py`)
- CLI (`demo.py`)
- Local API (`sara/api/local_server.py`)

2. Orchestration layer

- Host Agent (`sara/core/host_agent.py`)
- Command understanding and planning (`sara/llm/service.py`)

3. Safety and personalization layer

- Privacy classifier and routing (`sara/privacy/router.py`)
- Prompt sanitization (`sara/privacy/sanitizer.py`)
- Memory manager (structured + semantic + graph) (`sara/memory/manager.py`)

4. Execution layer

- Deterministic macros (`sara/execution/browser_macros.py`)
- Plan-based step loop (`sara/execution/agent.py`)
- Iterative one-action control loop (`sara/execution/iterative_agent.py`)
- Capability profile policy (`sara/execution/path_policy.py`)

5. Automation harness layer (existing validated stack)

- App control (`src/harness/app_controller.py`)
- Planner/self-healing (`src/automation/execution_planner.py`)
- AX executor (`src/harness/ax_executor.py`)
- Verification (`src/harness/verification.py`)
- Locator (`src/harness/locator.py`)

6. Discovery and onboarding layer

- Installed app discovery (`src/harness/windows_app_discovery.py`)
- Executable inventory (`src/harness/executable_inventory.py`)
- Probe reporting (`src/harness/probe_dashboard.py`)
- Dynamic app registration (`src/harness/config.py` + `.config/user_apps.json`)

### 5.2 End-to-End Command Flow

1. User command received from UI/widget/CLI/API.
2. HostAgent resolves memory references and builds context.
3. Privacy sensitivity classified.
4. Memory recalled and injected into command context.
5. LLM command understanding determines intent/action_type.
6. Branch by intent:

- remember: fact/graph extraction and memory mutation.
- screen_read: UIA text capture + OCR fallback.
- conversation: conversational response.
- automation: planning + safety policy + execution.

7. For automation in live mode:

- deterministic macro path when applicable,
- otherwise iterative or plan-based execution,
- each step execution is verification-gated.

8. Result persisted to interaction history and memory context.
9. UI/API returns structured response and status.

## 6. Full Feature List

### 6.1 Interaction and UX Features

| ID    | Feature              | Description                                                          | User Value                             | Status      |
| ----- | -------------------- | -------------------------------------------------------------------- | -------------------------------------- | ----------- |
| UX-01 | Multi-mode launcher  | Chat, widget, CLI, API, test, preflight modes from one entrypoint    | Flexible operation context             | Implemented |
| UX-02 | Full chat interface  | Left-nav shell with Assistant, Tasks/Runs, Crawler, Memory, Settings | End-to-end control and visibility      | Implemented |
| UX-03 | Always-on-top widget | Compact live controller with text + PTT                              | Fast command access while multitasking | Implemented |
| UX-04 | Dry-run toggle       | Plan-only mode without live execution                                | Safe testing and demos                 | Implemented |
| UX-05 | Live progress stream | Step progress events rendered in UI and widget                       | Real-time transparency                 | Implemented |
| UX-06 | Runtime status chip  | Idle/running/error state in top bar/context cards                    | Quick operational awareness            | Implemented |
| UX-07 | Keyboard shortcuts   | Mode switching and panel focus shortcuts                             | Operator speed during demos            | Implemented |
| UX-08 | Context panel cards  | Active task, plan summary, health summary                            | Low-cognitive-load monitoring          | Implemented |

### 6.2 Orchestration and Understanding Features

| ID      | Feature                          | Description                                                      | User Value                         | Status      |
| ------- | -------------------------------- | ---------------------------------------------------------------- | ---------------------------------- | ----------- |
| ORCH-01 | Unified host orchestration       | Central policy and flow management in HostAgent                  | Consistent behavior across modes   | Implemented |
| ORCH-02 | Structured command understanding | Intent + action_type + confidence + execution flags              | Safer and more predictable routing | Implemented |
| ORCH-03 | Confidence gate                  | Automation blocked when below threshold                          | Reduces accidental mis-execution   | Implemented |
| ORCH-04 | High-risk approval policy        | Optional approval requirement for destructive actions            | Human control for risky tasks      | Implemented |
| ORCH-05 | App resolution strategy          | Resolve target app from explicit mention/session/fallback policy | Better command routing             | Implemented |
| ORCH-06 | Media session continuity         | Follow-up commands use active browser media context              | Natural conversational continuity  | Implemented |

### 6.3 Automation Runtime Features

| ID      | Feature                      | Description                                                       | User Value                            | Status      |
| ------- | ---------------------------- | ----------------------------------------------------------------- | ------------------------------------- | ----------- |
| AUTO-01 | Plan-based execution agent   | Step-by-step execution with retries and replans                   | Deterministic command fulfillment     | Implemented |
| AUTO-02 | Iterative execution agent    | One-action-per-turn LLM loop with observations                    | Adaptive control in complex screens   | Implemented |
| AUTO-03 | Verification gate            | Post-action verification required before advancing                | Reliability and correctness           | Implemented |
| AUTO-04 | Deterministic macro fallback | Browser and save flows via known shortcuts/URLs                   | Stability in repetitive scenarios     | Implemented |
| AUTO-05 | Live-AX recovery macro       | Recovery path when iterative browser selection is unstable        | Reduced failure rate in browser flows | Implemented |
| AUTO-06 | Protected app policy         | Prevent execution on protected apps unless explicitly allowed     | Operational safety                    | Implemented |
| AUTO-07 | Keep-open policy             | Prevent auto-termination for persistent tasks (play/watch/listen) | Better UX continuity                  | Implemented |
| AUTO-08 | Capability profile policy    | Coverage-aware vision fallback decisioning                        | Better path selection quality         | Implemented |

### 6.4 Crawler and Onboarding Features

| ID     | Feature                        | Description                                                    | User Value                            | Status      |
| ------ | ------------------------------ | -------------------------------------------------------------- | ------------------------------------- | ----------- |
| CRW-01 | Installed app discovery        | Registry and Start Menu based app discovery                    | Faster app selection                  | Implemented |
| CRW-02 | Full executable inventory scan | Fixed-drive exe scan with dedupe and limits                    | Broad onboarding coverage             | Implemented |
| CRW-03 | Browse executable picker       | Manual exe selection from file dialog                          | Precision onboarding                  | Implemented |
| CRW-04 | Auto register + probe chain    | Select exe -> register app -> run probe -> switch to assistant | One-flow onboarding                   | Implemented |
| CRW-05 | Dynamic app registration       | Persist app/task/fallback metadata in user config              | Extensible app catalog                | Implemented |
| CRW-06 | Probe dashboard                | Discovery and cache analytics surfaced in Tasks/Runs panel     | Observability for readiness           | Implemented |
| CRW-07 | Assistant handoff after probe  | Probed app becomes active assistant target                     | Immediate automation after onboarding | Implemented |

### 6.5 Privacy and Safety Features

| ID      | Feature                     | Description                                                         | User Value                  | Status      |
| ------- | --------------------------- | ------------------------------------------------------------------- | --------------------------- | ----------- |
| SAFE-01 | Sensitivity classification  | LOW/MEDIUM/HIGH command classification                              | Policy-aware handling       | Implemented |
| SAFE-02 | Prompt sanitization         | Regex + optional Presidio redaction/tokenization before cloud calls | Data leakage risk reduction | Implemented |
| SAFE-03 | Secret redaction strategy   | Secrets replaced with irreversible placeholders                     | Sensitive-token protection  | Implemented |
| SAFE-04 | Policy-driven risk controls | Keyword-based high-risk action checks                               | Safer automation behavior   | Implemented |

Note: Current deployment is cloud-first for LLM routing; sensitivity controls sanitization rigor and observability behavior.

### 6.6 Memory and Personalization Features

| ID     | Feature                    | Description                                         | User Value                          | Status                                     |
| ------ | -------------------------- | --------------------------------------------------- | ----------------------------------- | ------------------------------------------ |
| MEM-01 | Structured fact memory     | Persistent key-value memory in JSON                 | Cross-session personalization       | Implemented                                |
| MEM-02 | Semantic recall memory     | Chroma + SBERT retrieval of related interactions    | Context continuity                  | Implemented (optional when deps available) |
| MEM-03 | Graph memory backend       | Neo4j-based relations and entity links              | Richer relationship recall          | Implemented (optional by config)           |
| MEM-04 | Memory operations          | Write, update, delete, read from natural language   | Corrective and maintainable memory  | Implemented                                |
| MEM-05 | Reference resolution       | Replace phrases like "my teacher" with known entity | More natural command handling       | Implemented                                |
| MEM-06 | Planning bias from history | Success priors per app/pattern influence context    | Better planning relevance over time | Implemented                                |

### 6.7 Voice Features

| ID     | Feature                  | Description                                                | User Value                         | Status                 |
| ------ | ------------------------ | ---------------------------------------------------------- | ---------------------------------- | ---------------------- |
| VOX-01 | Wake loop                | Continuous wake-state lifecycle in UI/widget               | Hands-free interaction             | Implemented            |
| VOX-02 | Porcupine wake engine    | PPN wake word detection when configured                    | Low-latency wake path              | Implemented (optional) |
| VOX-03 | Transcript wake fallback | Wake handling via transcript flow if Porcupine unavailable | Resilience without hard dependency | Implemented            |
| VOX-04 | STT pipeline             | Deepgram transcription with Google fallback                | Robust command capture             | Implemented            |
| VOX-05 | TTS pipeline             | Deepgram Aura playback with pyttsx3 fallback               | Audible response continuity        | Implemented            |
| VOX-06 | Push-to-talk             | Manual voice capture trigger in UI/widget                  | Reliable fallback control          | Implemented            |

### 6.8 API and Integration Features

| ID     | Feature                         | Description                                             | User Value                       | Status      |
| ------ | ------------------------------- | ------------------------------------------------------- | -------------------------------- | ----------- |
| API-01 | Local HTTP server               | Embedded threaded local server                          | Programmatic integration         | Implemented |
| API-02 | Async job model                 | `/command` enqueue + `/jobs/{id}` polling               | Non-blocking integration pattern | Implemented |
| API-03 | Health/status/history endpoints | Runtime diagnostics and recent activity                 | Integration observability        | Implemented |
| API-04 | Shared agent backend            | API calls use same HostAgent orchestration as UI/widget | Behavior consistency             | Implemented |

### 6.9 Testing, Validation, and Reporting Features

| ID     | Feature                    | Description                                      | User Value                      | Status      |
| ------ | -------------------------- | ------------------------------------------------ | ------------------------------- | ----------- |
| OPS-01 | Demo preflight             | Environment, imports, LLM, UI, voice, app checks | Faster go/no-go readiness       | Implemented |
| OPS-02 | Layer0 static validator    | Exe/cache/exposure path integrity checks per app | Structural reliability baseline | Implemented |
| OPS-03 | Layer1 smoke runner        | Cross-app live automation smoke                  | Runtime confidence snapshot     | Implemented |
| OPS-04 | Single-app pipeline runner | Discover + analyze + execute + profile           | Targeted app hardening          | Implemented |
| OPS-05 | Docs context auto-sync     | Runtime context document generation              | Faster presentation upkeep      | Implemented |
| OPS-06 | Execution traces           | JSON traces for agent runs                       | Debug and explainability        | Implemented |

## 7. Supported App Profiles

### 7.1 AppAgent Profiles

- NotepadAgent
- CalculatorAgent
- ExcelAgent
- ChromeAgent
- BraveAgent
- SpotifyAgent
- BaseAppAgent fallback for unknown mappings

### 7.2 Harness App Catalog

Configured app catalog in harness includes: Notepad, Calculator, Chrome, VSCode, Windsurf, WhatsApp, Spotify, Zoom, Excel, Telegram, Brave, plus user-registered apps.

### 7.3 Dynamic App Extension Model

Apps can be added without code changes via crawler registration:

1. discover or select executable,
2. auto-populate title regex and seed tasks,
3. persist to `.config/user_apps.json`,
4. probe and cache UI structure,
5. activate app in assistant selector.

## 8. Local API Specification

Base host/port from config: `LOCAL_API_HOST`, `LOCAL_API_PORT`

### 8.1 Endpoints

- `GET /health`
  - Returns service status.

- `GET /status`
  - Returns agent system status payload (mode, success rate, memory summary, etc.).

- `GET /history`
  - Returns recent command history.

- `POST /command`
  - Body: `{ "command": "..." }`
  - Behavior: queues async job.
  - Returns: `{ "job_id": "...", "status": "queued" }`

- `GET /jobs/{job_id}`
  - Returns queued/running/done/failed job state and result/error.

## 9. Data Model and Storage

### 9.1 Primary Runtime Stores

- `sara_memory/facts.json`: structured persistent facts.
- `sara_memory/chroma`: semantic vector memory (optional dependency-based).
- `sara_memory/profile.json`: identity, preference, and success priors.
- `.cache/*.json`: per-app automation-tree cache and fingerprints.
- `.config/user_apps.json`: user-registered apps/tasks/fallbacks.
- `runs/*`: live run artifacts and trace logs.
- `results/*`: validation and reporting outputs.

### 9.2 Command Result Contract

Core result payload contains:

- command,
- intent,
- privacy_route,
- sensitivity,
- plan,
- execution_success,
- response_text,
- memory_recalled,
- facts_stored,
- progress_events,
- app_agent,
- tier_used,
- error.

## 10. Configuration and Environment Controls

### 10.1 Core Runtime Flags

- `SARA_ENABLE_ITERATIVE_AUTOMATION`
- `SARA_REQUIRE_APPROVAL_FOR_RISKY`
- `SARA_AUTOMATION_CONFIDENCE_THRESHOLD`
- `SARA_ENABLE_WAKE_LOOP`
- `SARA_DISABLE_VOICE_INPUT`

### 10.2 Voice Flags

- `DEEPGRAM_API_KEY`
- `PICOVOICE_ACCESS_KEY`
- `SARA_WAKE_WORD_PATH`
- `SARA_WAKE_SENSITIVITY`
- `SARA_DEEPGRAM_STT_MODEL`
- `SARA_DEEPGRAM_TTS_MODEL`

### 10.3 Memory/Graph Flags

- `SARA_ENABLE_GRAPH_MEMORY`
- `SARA_NEO4J_URI`
- `SARA_NEO4J_USER`
- `SARA_NEO4J_PASSWORD`
- `SARA_NEO4J_DATABASE`
- `SARA_MEMORY_USER_ID`

## 11. Reliability, Security, and Safety Requirements

### 11.1 Reliability Requirements

- UI and widget must remain responsive via worker threads.
- Automation must execute with per-step verification.
- Missing optional dependencies must degrade gracefully (voice, semantic memory, graph memory).
- Failures should produce explicit error messages and not crash control surfaces.

### 11.2 Security and Privacy Requirements

- Sensitive entities should be sanitized before cloud-bound prompt payloads.
- High-risk commands should be guarded by approval policy when enabled.
- Protected apps should remain blocked unless explicitly allowed.
- Secrets must not be logged in plaintext by default behavior.

### 11.3 Safety-by-Design Requirements

- Dry-run default for non-live startup.
- Confidence threshold gate for automation.
- Deterministic macro preference for known fragile flows.
- Keep-open override for persistent tasks (media playback) to avoid disruptive teardown.

## 12. Validation Evidence and Current KPI Snapshot

### 12.1 Layer0 Static Validation (2026-04-19)

From `results/layer0_static_validation_20260419_134449.md`:

- Configured apps: 10
- Executables present: 8
- Static ready: 7
- Broken exposure paths: 0 across ready apps
- Orphan parent refs: 0 across ready apps

### 12.2 Layer1 Agentic Smoke (2026-04-19)

From `results/layer1_agentic_smoke_20260419_143246.md`:

- Total apps tested: 8
- Passed: 7
- Failed: 1 (Windsurf launch/connect issue)

### 12.3 Single-App Pipeline Evidence

Notepad (`results/single_app_pipeline_notepad_20260419_145357.md`):

- Cache elements: 468
- Exposure-path coverage: 419/468
- Task match coverage: 20/20 (1.0)
- Run failures: 0

Brave (`results/single_app_pipeline_brave_20260419_153528.md`):

- Cache elements: 516
- Exposure-path coverage: 450/516
- Task match coverage: 9/13 (0.6923)
- Run failures: 0

## 13. Presentation-Ready Demo Narrative

### 13.1 Recommended Storyline (7-10 minutes)

1. Problem and opportunity

- Desktop automation is fragile when flows rely only on visual clicking.

2. SARA approach

- Command understanding + memory + privacy + deterministic execution + verification.

3. Architecture

- Show interaction channels, orchestration core, execution pipeline, crawler onboarding.

4. Live workflow

- Run command in dry-run then live mode.
- Show step trace and verification events.

5. App onboarding

- In crawler tab: scan/browse exe -> register + probe -> automate immediately.

6. Voice and API

- Show wake/ptt states and local API contract.

7. Evidence

- Present Layer0/Layer1 and single-app KPI snapshots.

8. Roadmap

- Mention cross-app intent override hardening and expanded app packs.

### 13.2 Suggested Live Demo Sequence

1. Preflight run (`--preflight`) and status snapshot.
2. Chat mode dry-run command with plan preview.
3. Chat mode live command with progress stream.
4. Crawler onboarding of a selected executable and auto-probe handoff.
5. Widget mode quick command and ptt fallback.
6. API mode command submit and job polling.

## 14. Roadmap and Forward Plan

### 14.1 Near-Term (Next Iteration)

- App-name explicit intent override in HostAgent app resolver.
- Higher browser task-match coverage for Brave/Chrome workflows.
- Enhanced policy controls for route-specific privacy behaviors.
- Extended structured reporting dashboard in UI.

### 14.2 Mid-Term

- Broader app agent packs and richer domain templates.
- Improved multi-step conversational disambiguation.
- Expanded test harness coverage with scenario replay packs.
- Packaging for simpler evaluator setup.

## 15. Acceptance Criteria

Product is considered presentation-ready when:

- all startup modes run successfully in target environment,
- dry-run and live automation both function,
- crawler onboarding can add and probe a new executable app,
- status/history/memory are visible in UI,
- step-level verification events are produced in live runs,
- local API returns healthy status and processes async commands,
- validation reports are available for reliability evidence.

## 16. Appendix: Key Project Files

Primary entry and orchestration:

- `demo.py`
- `sara/core/host_agent.py`
- `sara/llm/service.py`

Execution:

- `sara/execution/agent.py`
- `sara/execution/iterative_agent.py`
- `sara/execution/browser_macros.py`
- `sara/execution/path_policy.py`

UI:

- `sara/ui/chat_widget.py`
- `sara/ui/widget.py`
- `sara/ui/theme/tokens.py`

Voice:

- `sara/voice/service.py`
- `sara/voice/wake_controller.py`

Memory and privacy:

- `sara/memory/manager.py`
- `sara/memory/graph_store.py`
- `sara/privacy/router.py`
- `sara/privacy/sanitizer.py`

Crawler and harness:

- `src/harness/config.py`
- `src/harness/windows_app_discovery.py`
- `src/harness/executable_inventory.py`
- `src/harness/probe_dashboard.py`
- `src/automation/execution_planner.py`
- `src/harness/ax_executor.py`
- `src/harness/verification.py`

Validation artifacts:

- `results/layer0_static_validation_20260419_134449.md`
- `results/layer1_agentic_smoke_20260419_143246.md`
- `results/single_app_pipeline_notepad_20260419_145357.md`
- `results/single_app_pipeline_brave_20260419_153528.md`
