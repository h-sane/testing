# SARA Speaking Script (Tomorrow Demo)

## Goal

Show SARA as a practical Windows automation copilot with memory, voice-ready UX, and resilient browser automation.

## Pre-Demo Runbook (Do this 5-10 min before)

1. Activate environment:
   - .\.venv\Scripts\Activate.ps1
2. Smoke test:
   - .\.venv\Scripts\python.exe demo.py --test
3. Preflight:
   - .\.venv\Scripts\python.exe demo.py --preflight
4. Start live UI demo:
   - .\.venv\Scripts\python.exe demo.py --live

## 7-Minute Speaking Script

### 0:00 - 0:45 Opening

Say:
"Today I will show SARA, a desktop copilot that can understand intent, remember user context, and execute real Windows UI actions safely."

"The key point is reliability: SARA combines deterministic shortcuts, AX-tree interaction, and verification, so it can recover from fragile UI situations."

### 0:45 - 1:45 Memory + Context Continuity

Say:
"Let me first establish user context."

Type/speak:

- my name is Hussain
- what do you remember about me

Say:
"SARA stores structured and semantic memory. This lets future turns become more contextual instead of one-off commands."

### 1:45 - 3:00 Notepad Automation

Say:
"Now I will show deterministic desktop automation in Notepad."

Type/speak:

- open file menu in notepad
- type this is tomorrow demo draft in notepad

Say:
"Each step is verified, and if a brittle path fails, SARA can switch strategies instead of silently failing."

### 3:00 - 5:30 Browser Media Flow + Continuation

Say:
"Now I will show browser media automation and multi-turn continuation."

Type/speak:

- play beauty and the beat on youtube

Say:
"SARA opens and starts playback, then keeps this media session alive for follow-up controls."

Type/speak:

- play next song

Say:
"For next-song continuation, SARA now treats this as a continuation of the current media session. It focuses the browser and sends Shift+N, then verifies UI change."

Type/speak:

- pause current song

Say:
"Pause is also treated as continuation on the same session, so SARA does not need a full re-planning cycle from scratch."

### 5:30 - 6:30 Reliability + Safety Summary

Say:
"Operationally, SARA applies confidence and risk gates, keeps audit-like execution traces, and uses policy-based fallbacks."

"So this is not just a chatbot; it is a controlled execution system."

### 6:30 - 7:00 Caveat + Close

Say:
"One caveat in today’s environment is optional Neo4j graph connectivity. Core demo flows still run even if graph memory is unavailable."

"In short: SARA can remember, reason over context, and execute real UI tasks reliably across turns."

## Backup Lines If Something Is Slow

- "I will repeat that command once; SARA keeps session context, so retries are safe."
- "This step uses live UI verification, so a short wait is expected."
- "Even when one path is unstable, SARA falls back to deterministic controls."

## If Asked: What happens after 'play beauty and the beat' then 'play next song'?

Answer:
"SARA treats 'play next song' as a continuation of the active media session. It focuses the browser window, sends Shift+N for YouTube next-track behavior, verifies that UI state changed, updates session state, and returns success."
