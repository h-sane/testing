# Legacy SARA Codebase Audit

Date: 2026-04-19

## Resolution Status

RESOLVED (April 2026): All Priority P0/P1/P2 items in this audit are now implemented in this repository.

- Implemented: pre-LLM sanitization gateway, unified command-understanding contract, widget non-blocking worker, wake-loop lifecycle integration in widget/chat, high-risk approval gate, identity bootstrap/profile seed, richer screen-read path, local HTTP API surface, and preference-aware planning bias.
- Validation: demo smoke tests, compile checks, and local API endpoint checks passed.

## Scope

Audited legacy repositories:

- SARA-Hybrid-Assistant
- sara2
- SARA

Objective:

- Identify important capabilities that are missing or only partially implemented in this repository.
- Prioritize features that are practical to implement in the current architecture.

## Deployment Decisions (April 2026)

### Decision 1: Privacy in a Cloud-Only LLM Stack

We are not enforcing local-model routing because the deployment is cloud-first.

Instead, privacy should be handled by a pre-LLM sanitization gateway:

- Detect sensitive entities (PII and secrets) before any cloud LLM call.
- Replace values with placeholders/tokens before sending prompts.
- Keep a short-lived local token map for safe post-processing where needed.
- Prefer irreversible masking for high-risk secrets (passwords, API keys, tokens).

Recommended stack:

- Primary: Microsoft Presidio (Analyzer + Anonymizer) with custom recognizers.
- Backup: Deterministic regex and rule-based redaction for must-catch patterns.

### Decision 2: Intent Routing Strategy

A separate intent-classifier model is not required.

Recommended approach:

- Use one command-understanding prompt contract that returns structured JSON, including route/action type.
- Keep a lightweight rule-based pre-check layer for deterministic overrides on obvious safety cases.
- Keep downstream handlers separate (automation, memory read/write, QA), but derive route from the single structured output.

Benefits:

- Lower latency and fewer LLM round trips.
- Less drift between classifier and planner.
- Simpler failure handling and tracing.

## Implementation Status Update (April 2026)

- DONE: Pre-LLM privacy sanitization gateway implemented at LLM client boundary.
- DONE: Unified command-understanding JSON contract implemented and wired in HostAgent.
- DONE: Cloud-first routing behavior updated to use sensitivity + sanitization instead of local-model enforcement.

## Current Repository Baseline (Already Strong)

The following are already implemented and should be kept as core strengths:

- Modular architecture under `sara/` with clear domains (`core`, `llm`, `execution`, `memory`, `privacy`, `voice`, `ui`).
- Deterministic execution loop with step verification and bounded replan.
- Click path hierarchy via existing runtime executor chain.
- Browser deterministic macros for high-confidence commands.
- Dual memory pattern (structured facts + semantic retrieval fallback).
- Dry-run/live split with preflight and smoke tests.

## Capability Matrix (Legacy vs Current)

### 1) Privacy in Cloud-Only Deployment

- Current status: STRONG
- Legacy value observed:
  - Earlier code paths reduced accidental leakage in some branches using narrower flows, but did not provide robust cloud-safe sanitization.
- Gap in current repo:
  - Optional hardening: expand recognizers/patterns and add audit logging policy around redaction events.

### 1b) Intent Routing Architecture

- Current status: STRONG
- Legacy value observed:
  - Multi-step routing/planning existed to compensate for mixed local/cloud model setups.
- Gap in current repo:
  - Optional hardening: add confidence threshold policy for clarification prompts before risky execution.

### 2) Memory and Personalization

- Current status: STRONG
- Legacy value observed:
  - Identity bootstrap and memory seeding flows.
  - Semantic expansion for recall and active-learning style memory updates.
- Gap in current repo:
  - Resolved: identity bootstrap routine and preference-aware planning priors are implemented.

### 3) Wake Word + Voice Runtime

- Current status: STRONG
- Legacy value observed:
  - Dedicated wake-word listener thread with event signaling.
  - VAD-based command capture and clearer voice lifecycle.
  - TTS playback pipeline integrated with execution state.
- Gap in current repo:
  - Resolved: wake-loop lifecycle callbacks are integrated into widget/chat runtime with explicit state updates.

### 4) UI Governance and Safety Controls

- Current status: STRONG
- Legacy value observed:
  - Explicit permission gate for risky actions.
  - Rich HUD state transitions and operator feedback loops.
- Gap in current repo:
  - Resolved: high-risk commands now require approval when policy is enabled.

### 5) Input/Interaction Responsiveness

- Current status: STRONG
- Legacy value observed:
  - More explicit background execution loops in voice-driven modes.
- Gap in current repo:
  - Resolved: widget execution now runs in background worker threads and no longer blocks UI command loop.

### 6) External API Surface

- Current status: STRONG
- Legacy value observed:
  - HTTP API endpoint for command submission in one earlier codebase.
- Gap in current repo:
  - Resolved: local HTTP API now supports command submission and job/status polling.

## Highest-Value Features to Add Next

Completed in April 2026.

### Priority P0 (Implement first)

1. DONE: Implement pre-LLM privacy sanitization gateway (detect -> redact/tokenize -> cloud call).
2. DONE: Replace separate intent-classifier call with a single command-understanding JSON contract.
3. DONE: Add non-blocking execution worker flow in widget mode.
4. DONE: Integrate wake-word event loop with explicit state transitions into widget/chat lifecycle.

### Priority P1

1. DONE: Add high-risk action permission gate (toggleable policy).
2. DONE: Add identity bootstrap and profile seed routine in memory layer.
3. DONE: Add richer screen-read path (OCR/UI text capture + summarize), replacing stub behavior.

### Priority P2

1. DONE: Add optional local HTTP API endpoint for command ingestion and status polling.
2. DONE: Add preference-aware planning bias (per-app/per-user success priors).

## Keep/Do Not Port As-Is

Some legacy elements should not be copied directly because the current architecture already has better foundations:

- Visual-first executor patterns that bypass deterministic cache/AX-first policy.
- Monolithic host-agent patterns that mix orchestration, UI, and tool execution in one class.
- Hardcoded user identity or machine-specific launch assumptions.

## Recommended Implementation Order

1. Privacy sanitizer gateway (Presidio + regex fallback + token map policy).
2. Unified command-understanding contract (single LLM call for route + action intent).
3. Widget non-blocking + voice wake loop.
4. Permission gate and screen-read upgrade.
5. Identity bootstrap and preference tuning.
6. Optional API server surface.
