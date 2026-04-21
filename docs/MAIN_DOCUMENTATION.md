# SARA Main Documentation (Current Implementation)

This document explains how the current SARA implementation works from the user side, end to end.

## 1. What You Can Run

- `python demo.py`
  - Starts the chat UI.
  - Default is dry-run mode (plans are produced, no real app actions).
- `python demo.py --widget`
  - Starts the compact always-on-top widget.
- `python demo.py --cli`
  - Starts terminal REPL mode.
- `python demo.py --live`
  - Enables real automation execution instead of dry-run.
- `python demo.py --preflight`
  - Runs docs context sync and environment checks.
- `python demo.py --test`
  - Runs smoke tests for remember/automation/conversation routing.
- `python demo.py --api`
  - Starts the local HTTP API alongside UI/CLI mode.
- `python demo.py --api-only`
  - Starts only the local HTTP API server.

## 2. User-Facing Flow (End to End)

### Step 1: You send a command

You can send commands through:

- Chat UI input box
- Widget text input
- Widget PTT button (voice capture)
- CLI prompt

All paths call `HostAgent.process_command(...)`.

### Step 2: Privacy routing and sanitization happen first

SARA classifies your text as HIGH, MEDIUM, or LOW sensitivity.

- All requests use CLOUD provider routing in current deployment.
- For sensitive text, SARA sanitizes prompt payloads before cloud LLM calls.

Sensitive entities (for example email, phone, SSN, API keys, tokens, passwords) are redacted or tokenized before sending.

### Step 3: Memory recall happens before intent

SARA pulls related prior interactions from memory and uses them as context.

- Structured facts: `sara_memory/facts.json`
- Semantic memory (when enabled): `sara_memory/chroma`

### Step 4: Command understanding runs in one call

SARA runs one structured command-understanding call that returns:

- `intent`
- `action_type`
- `requires_db_lookup`
- `requires_execution`

`intent` is one of:

- `automation`
- `remember`
- `screen_read`
- `conversation`

This replaces separate intent-classifier and route-classifier stages.

### Step 5: Branch execution

#### A) Remember

- Fact extraction runs.
- Facts are merged into persistent structured memory.
- Response confirms what was stored.

#### B) Conversation

- SARA generates a cloud response using sanitized input payloads.
- Memory recall context is included when available.

#### C) Screen Read

- Captures visible UI text from the active app window.
- Falls back to OCR capture when UI text extraction is unavailable.
- Returns a short summary response from the captured content.

#### D) Automation

1. App context is selected (UI dropdown/active app/default logic).
2. A step plan is generated (JSON actions only).
3. Confidence policy validates whether the command is safe enough to execute.
4. High-risk commands require explicit approval when policy is enabled.
5. If dry-run is ON, SARA returns the plan only.
6. If live mode is ON, SARA executes the plan through the runtime pipeline below.

## 3. Live Automation Runtime Pipeline

When running with `--live`, the flow is:

1. Resolve target app.
2. Validate app policy (protected apps), config, executable path.
3. Start/connect app window.
4. Apply deterministic macro plan first when available (especially for browser commands).
5. Run strict step loop in `ExecutionAgent`:
   - Execute one step.
   - Verify result.
   - Retry step if needed.
   - Replan once if needed.

For CLICK actions, execution path is:

- Cache + Planner
- AX executor
- Vision fallback (only when allowed)

For TYPE/HOTKEY actions, keyboard dispatch is used.

Every successful action is verification-gated before moving to the next step.

Execution traces are written under:

- `runs/layer1_agentic`

## 4. What You See in the UI

### Chat UI

- Left: chat interaction
- Right tabs:
  - Plan
  - Memory
  - Status
- App selector to change active app
- Dry-run toggle to switch planning vs real execution behavior
- Wake state label and PTT button for voice-driven commands

### Widget UI

- Always-on-top small window
- Status label (`Idle`, planning/acting, done, failed)
- Wake state label with explicit wake lifecycle states
- Text command input
- PTT button (voice attempt + typed fallback)

## 5. Current Runtime Defaults

- Dry-run by default unless `--live` is passed.
- Preferred LLM providers are configured through environment.
- Current Bedrock primary model setup is Nova Lite first for simple and complex calls.
- Privacy sanitizer is enabled by default before cloud calls (`SARA_PRIVACY_SANITIZER_ENABLED=1`).
- Presidio integration is optional and auto-used when installed (`SARA_PRIVACY_USE_PRESIDIO=1`).
- Vision is not the critical default path for core flow.
- Voice service defaults to text-safe mode unless voice mode is explicitly enabled.
- Wake loop is enabled by default in chat/widget (`SARA_ENABLE_WAKE_LOOP=1`).
- High-risk approval policy is enabled by default (`SARA_REQUIRE_APPROVAL_FOR_RISKY=1`).

## 6. Operational Artifacts and Reports

- Preflight reports: `results/demo_preflight_*.json`
- Static validation reports: `results/layer0_static_validation_*.json` and `.md`
- Agentic smoke reports: `results/layer1_agentic_smoke_*.json` and `.md`
- Auto-generated runtime docs context: `docs/context/runtime_context.auto.md`

## 7. Practical User Journey

1. Run `python demo.py --preflight`.
2. Start UI using `python demo.py`.
3. Keep dry-run ON to inspect plan quality.
4. Switch to live execution with `python demo.py --live` when ready.
5. Run commands, review Plan/Memory/Status feedback.
6. Use `python demo.py --test` to quickly confirm core routing behaviors after changes.

## 8. Known Gaps in Current Implementation

- Voice can gracefully fall back to typed command behavior when voice dependencies are unavailable.
