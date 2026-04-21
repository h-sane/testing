# SARA Layered Delivery Plan (One-Day Demo)

Date: 2026-04-19
Owner: Hussain + Copilot
Goal: Reliable live demo with always-on widget, wake-word flow, and no-VLM critical execution path.

## 1) Primary Codebase Decision

Primary codebase: testing

Reason:

- The tested Automation Tree pipeline is already in testing/src with cache + exposure-path planner + AX + verification.
- This is the exact execution backbone required for deterministic demo behavior.
- Sara2 execution currently depends heavily on a separate smol/vision path and would require larger rework to enforce exposure-path-first execution.

Reuse from Sara2 (targeted copy/adapt only):

- Wake-word listener from C:/Users/husai/Desktop/CODES/Project/sara2/modules/audio/listener.py
- STT capture/transcription flow from C:/Users/husai/Desktop/CODES/Project/sara2/modules/audio/stt_client.py
- Always-on-top HUD interaction patterns from C:/Users/husai/Desktop/CODES/Project/sara2/modules/governance/orbital_hud.py

Do not migrate wholesale from Sara2:

- modules/execution/smol_executor.py (contains visual-first and non-AT execution behavior)
- modules/perception/vision_client.py flow in critical path

## 2) Layered Build Order

### Layer 0: Baseline and Safety Gates (60-90 min)

Objective: Prove probe/cache/planner/AX path is stable for target apps before adding LLM/UI/voice.

Tasks:

1. Validate discovery and cache health for Notepad + one browser (Chrome or Brave).
2. Run harness with vision disabled and verify tasks execute via planner/AX only.
3. Confirm verification signals are produced after each action.
4. Freeze app/task list for demo (supported and probed only).

Files to use:

- src/harness/main.py
- src/automation/prober.py
- src/automation/execution_planner.py
- src/harness/ax_executor.py
- src/harness/verification.py

Done criteria:

- Notepad scenario passes end-to-end without vision.
- Browser scenario (open tab + search/open target) passes with planner/AX + keyboard fallbacks.
- Known failure cases documented with workaround commands.

### Layer 1: Agentic Execution Layer (LLM + Step Verification) (2-3 hrs)

Objective: Build a robust command-to-plan-to-step execution loop that verifies each step and replans on failure.

Tasks:

1. Add orchestrator wrapper that enforces:
   - one step at a time
   - execute step
   - verify step result
   - retry/replan on failure
2. Disable vision in default demo path.
3. Add browser macros for high-confidence paths (YouTube search/play flow).
4. Add structured execution trace logging for demo explainability.

Target module split:

- sara/host_agent.py: top-level intent routing and loop coordination
- sara/llm_service.py: intent + plan generation only
- sara/execution_agent.py: strict agentic loop (new)
- sara/browser_macros.py: deterministic browser subflows (new)

Done criteria:

- Spoken/text command creates a step plan.
- Each step is verified before next step.
- Replan or fallback occurs automatically on mismatch.
- No-VLM mode can complete core scenarios.

### Layer 2: Always-On Widget Layer (1.5-2 hrs)

Objective: Persistent, minimal control surface that can trigger command capture and show live status.

Tasks:

1. Build compact always-on-top widget mode.
2. Add status states: Listening, Hearing, Planning, Acting, Verifying, Done/Failed.
3. Add push-to-talk and typed-input fallback in same widget.
4. Keep full chat window as secondary debug view.

Reuse guidance:

- Port UX patterns from Sara2 orbital_hud.py
- Keep runtime framework consistent with main demo UI stack (prefer one Qt stack only)

Target modules:

- sara/ui/widget.py (new)
- sara/ui/chat_widget.py (existing plan target)
- demo.py flag: --widget

Done criteria:

- Widget stays on top.
- Command can be sent by button and typed input.
- Status updates mirror agent execution stages.

### Layer 3: Wake-Word + Voice Layer (1.5-2 hrs)

Objective: Hey SARA wake flow working in live demo mode with fallback safety.

Tasks:

1. Integrate wake listener loop.
2. On wake detection, capture voice command via VAD.
3. Transcribe and route to HostAgent.
4. Add push-to-talk fallback and clear failure messaging.

Reuse guidance:

- listener.py logic from Sara2 for wake-word eventing
- stt_client.py logic from Sara2 for VAD + transcription structure
- adapt to testing environment and error handling standards

Target modules:

- sara/voice_service.py
- sara/wake_controller.py (new)
- sara/ui/widget.py integration hooks

Done criteria:

- Saying Hey SARA triggers visible listening state.
- Command is captured and executed through agentic loop.
- If wake/STT fails, push-to-talk still runs demo flow.

### Layer 4: Demo Hardening and Script Lock (60-90 min)

Objective: Make tomorrow demo predictable and resilient.

Tasks:

1. Lock a deterministic demo script with exact spoken prompts.
2. Pre-warm caches and test commands in final environment.
3. Add one-command preflight checker.
4. Produce fallback script for each critical scenario.

Outputs:

- Updated DEMO_SCRIPT.md
- Demo preflight report in runs/ or results/
- Final go/no-go checklist

Done criteria:

- End-to-end dry rehearsal passes 3 times consecutively.
- Critical scenarios pass without manual mouse/keyboard intervention.

## 3) Module Ownership and Interfaces

Core automation (keep in testing/src):

- Discovery/cache/prober: src/automation/prober.py, src/automation/storage.py
- Planner/self-heal: src/automation/execution_planner.py
- AX actions: src/harness/ax_executor.py
- Verification: src/harness/verification.py

New SARA application layer (build in testing/sara):

- host_agent.py: command routing + app context + memory hooks
- execution_agent.py: step loop policy and retries
- llm_service.py: model interactions only
- browser_macros.py: deterministic browser routines
- voice_service.py + wake_controller.py: wake and STT integration
- ui/widget.py + ui/chat_widget.py: operator surfaces

## 4) Browser Strategy for Tomorrow (No-VLM Critical Path)

Default browser app: choose one (Chrome or Brave) and freeze for demo.

Deterministic flow for "open YouTube and play X":

1. Ensure browser focused/opened.
2. Ctrl+L to focus omnibox.
3. Type youtube.com and Enter.
4. Wait and verify page load landmarks.
5. Focus search field via cached exposure path or deterministic shortcut/tab sequence.
6. Type query and Enter.
7. Open first playable result via exposure path/cached target or deterministic keyboard navigation.
8. Verify playback indicator or player state change.

If any step fails:

- Retry once with planner/AX.
- Replan with alternate target labels.
- If still failing, use pre-approved fallback macro path.

## 5) One-Day Execution Timeline

Block A (Morning): Layer 0 + Layer 1
Block B (Midday): Layer 2
Block C (Afternoon): Layer 3
Block D (Evening): Layer 4 + rehearsal

## 6) Immediate Next Actions

1. Run Layer 0 validation in current testing environment.
2. Choose demo browser (Chrome or Brave) based on cache quality.
3. Scaffold sara/execution_agent.py and wire no-vision default policy.
4. Port Sara2 wake listener and HUD concepts into testing/sara modules.
5. Run first full rehearsal with widget + typed commands before voice enablement.
