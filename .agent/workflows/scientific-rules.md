---
description: Scientific execution, logging, and validation rules for research-grade automation experiments
---

# SCIENTIFIC EXECUTION, LOGGING, AND VALIDATION RULES

## Mandatory Protocol for Research-Grade Automation Experiments

### PURPOSE

This document defines the mandatory logging, execution, validation, and reporting standards required for all automation system runs. These rules exist to ensure the system produces **verifiable, reproducible, and scientifically valid evidence** suitable for inclusion in a research paper.

No claims of success, completion, improvement, or correctness are allowed without full evidentiary artifacts defined below.

---

# SECTION 1 — CORE PRINCIPLE: NO CLAIM WITHOUT EVIDENCE

The system must never claim that any component works unless ALL of the following exist:

1. Raw execution logs
2. Structured trace logs
3. Console stdout capture
4. Console stderr capture
5. Machine-readable execution results
6. Reproducible run identifier
7. Artifact checksums

If any artifact is missing, the result is classified as:

**INCOMPLETE — NOT VALID FOR RESEARCH CLAIMS**

---

# SECTION 2 — MANDATORY ARTIFACTS FOR EVERY RUN

Every execution MUST create a unique Run ID:

Format:
```
RUN_<YYYYMMDD>_<HHMMSS>_<random_suffix>
```

Example:
```
RUN_20260212_154233_A7F3
```

All artifacts MUST be stored in:
```
runs/<RUN_ID>/
```

This directory MUST contain:
```
runs/<RUN_ID>/
│
├── execution_log.jsonl
├── full_execution_trace.jsonl
├── all_logs.json
├── console.log
├── stdout.log
├── stderr.log
├── run_metadata.json
├── results.json
├── checksums.txt
└── screenshots/
    ├── step_001.png
    ├── step_002.png
    └── ...
```

If any file is missing, the run is **INVALID**.

---

# SECTION 3 — execution_log.jsonl REQUIREMENTS

Each executed step MUST create one entry.

Each entry MUST contain ALL fields:
```json
{
  "run_id": "...",
  "timestamp": "...",
  "app_name": "...",
  "task": "...",
  "execution_method": "CACHE | PLANNER | AX | VISION | TYPE | HOTKEY",
  "success": true,
  "plan_length": 2,
  "steps_completed": 2,
  "failure_step_index": -1,
  "locator_score": 0.95,
  "recovery_used": false,
  "vision_used": false,
  "llm_used": false,
  "execution_time_ms": 1234
}
```

No null fields allowed.

---

# SECTION 4 — full_execution_trace.jsonl REQUIREMENTS

This is the forensic trace.

Each step MUST log:
```json
{
  "run_id": "...",
  "event_type": "...",
  "component": "...",
  "action": "...",
  "input": "...",
  "output": "...",
  "success": true,
  "error": "",
  "latency_ms": 123,
  "terminal_stdout_snippet": "...",
  "terminal_stderr_snippet": "..."
}
```

`terminal_stdout_snippet` and `terminal_stderr_snippet` are **MANDATORY**.

---

# SECTION 5 — console.log REQUIREMENTS

`console.log` MUST contain complete stdout and stderr stream.

This file MUST include:

- startup messages
- execution messages
- errors
- recovery attempts
- retries
- locator diagnostics
- planner diagnostics
- LLM diagnostics
- vision diagnostics

Nothing may be suppressed.

---

# SECTION 6 — run_metadata.json REQUIREMENTS

Must contain:
```json
{
  "run_id": "...",
  "timestamp": "...",
  "system": {
    "os": "...",
    "python_version": "...",
    "machine": "...",
    "cpu": "...",
    "ram": "..."
  },
  "git_commit": "...",
  "modules_used": [],
  "llm_provider": "...",
  "vision_provider": "...",
  "cache_enabled": true,
  "vision_enabled": true,
  "llm_enabled": true
}
```

---

# SECTION 7 — results.json REQUIREMENTS

This file summarizes factual outcomes.
```json
{
  "run_id": "...",
  "total_tasks": 20,
  "total_success": 15,
  "total_failure": 5,
  "success_rate": 0.75,
  "by_method": {
    "CACHE": {},
    "PLANNER": {},
    "AX": {},
    "VISION": {},
    "LLM": {}
  },
  "by_application": {
    "Notepad": {},
    "Chrome": {}
  }
}
```

No interpretation allowed here. Only raw computed metrics.

---

# SECTION 8 — stdout.log and stderr.log REQUIREMENTS

`stdout.log` must contain entire stdout stream.
`stderr.log` must contain entire stderr stream.

These MUST be written using explicit redirection or stream interception.

Example requirement:
```
sys.stdout redirected to stdout.log
sys.stderr redirected to stderr.log
```

---

# SECTION 9 — checksums.txt REQUIREMENTS

`checksums.txt` MUST include SHA256 hash of every artifact.

Example:
```
sha256 execution_log.jsonl = abc123...
sha256 full_execution_trace.jsonl = def456...
sha256 console.log = ghi789...
sha256 results.json = jkl012...
```

This ensures artifacts cannot be altered undetected.

---

# SECTION 10 — FAILURE LOGGING REQUIREMENTS

Failures MUST NOT be hidden.

Every failure MUST include:

- exact error message
- component name
- timestamp
- stack trace (if exists)
- recovery attempts
- recovery outcome

Example:
```json
{
  "component": "locator",
  "error": "Element not found",
  "recovery_attempted": true,
  "recovery_success": false
}
```

---

# SECTION 11 — CLAIM VALIDATION RULE

A module may ONLY be declared:

**FUNCTIONALLY VERIFIED**

IF AND ONLY IF:

- `execution_log.jsonl` exists
- `full_execution_trace.jsonl` exists
- `stdout.log` exists
- `stderr.log` exists
- `results.json` exists
- `checksums.txt` exists
- at least one successful execution entry exists

Otherwise verdict MUST be:

**NOT VERIFIED**

---

# SECTION 12 — PROHIBITED BEHAVIOR

The system MUST NOT:

- claim success without logs
- suppress errors
- omit stderr capture
- fabricate results
- summarize without raw evidence
- delete previous logs

Violation invalidates experiment.

---

# SECTION 13 — REPRODUCIBILITY REQUIREMENT

Each report MUST include exact command used:

Example:
```
python harness/main.py --run-id RUN_20260212_154233_A7F3
```

This command must reproduce artifacts.

---

# SECTION 14 — REPORT GENERATION REQUIREMENT

Each module execution MUST generate:
```
runs/<RUN_ID>/validation_report.json
```

Containing:
```json
{
  "run_id": "...",
  "module": "...",
  "verdict": "VERIFIED | FAILED | INCOMPLETE",
  "artifact_paths": {},
  "evidence_lines": []
}
```

---

# SECTION 15 — RULE ENFORCEMENT

These rules are ABSOLUTE and must be followed for:

- `execution_planner.py`
- `locator.py`
- `ax_executor.py`
- `vision_executor.py`
- `llm_client.py`
- `orchestrator.py`
- ALL future modules

No exceptions.

---

# FINAL DIRECTIVE

From this point forward, the system MUST:

1. Always generate full artifacts
2. Always generate `validation_report.json`
3. Never claim success without proof
4. Always preserve logs

These artifacts will be used directly as scientific evidence in the research paper.

Non-compliant runs are **INVALID**.

**END OF RULES**
