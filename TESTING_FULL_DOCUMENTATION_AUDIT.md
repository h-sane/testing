# Testing Repository - Full Documentation Audit

Generated: 2026-04-19 12:19:15 +05:30
Audit Scope: All files under root, .agent, .agent_context, .github, results, scripts, src, tests.
Excluded Heavy Runtime Trees: .venv, .cache, .pytest_cache, experiments, runs, __pycache__.

## 1) Implementation Overview

- Primary implementation is in src/ with a hybrid Windows UI automation pipeline: CACHE -> PLANNER -> AX -> VISION.
- Harness orchestration lives in src/harness/main.py and coordinates app lifecycle, cache lookup, accessibility execution, and vision fallback.
- Reusable cache/fingerprint/matching/planning logic is in src/automation/.
- LLM planning/execution loop is in src/llm/ and uses provider/key-pool logic from src/llm/llm_client.py.
- Validation, diagnostics, and experiment runners live in scripts/, tests/, and root helper files.
- Results snapshots are versioned in results/; high-volume run artifacts are in runs/ and experiments/.

## 2) Coverage Summary

| Metric | Value |
|---|---:|
| Audited files (implementation/doc scope) | 73 |
| Tracked by git | 39 |
| Untracked/ignored but present | 34 |
| Excluded generated files in .venv | 11187 |
| Excluded generated files in .cache | 485 |
| Excluded generated files in experiments | 932 |
| Excluded generated files in runs | 273 |
| Excluded generated files in .pytest_cache | 5 |

## 3) Key Runtime Flow (Current Implementation)

1. run_validation_experiment.py and scripts/scientific_mass_test.py drive end-to-end runs.
2. src/harness/main.py executes task tiers in order: cache planner path, AX executor, then vision fallback.
3. src/automation/storage.py and src/automation/matcher.py provide cache lookup and scoring.
4. src/automation/execution_planner.py performs exposure-path/self-healing plan execution for cached targets.
5. src/harness/ax_executor.py executes accessibility actions and keyboard fallbacks.
6. src/harness/vision_executor.py and src/harness/vlm_provider.py run screenshot-based fallback location/click.
7. src/harness/verification.py, src/harness/logger.py, and src/harness/full_execution_trace_logger.py persist validation and traces.

## 4) Full File-by-File Audit

Legend: tracked = in git index, local = present but untracked/ignored.

### .agent

| File | Status | Size (bytes) | Purpose Seed | Classes | Functions |
|---|---|---:|---|---|---|
| .agent\workflows\scientific-rules.md | tracked | 7103 | --- |  |  |

### .agent_context

| File | Status | Size (bytes) | Purpose Seed | Classes | Functions |
|---|---|---:|---|---|---|
| .agent_context\context_summary.md | local | 3025 | # Agent Context Summary |  |  |
| .agent_context\implementation_plan.md | local | 11453 | # Universal Content Boundary Detection — Design Analysis |  |  |
| .agent_context\task.md | local | 2473 | # Task: Universal Content Boundary Detection |  |  |
| .agent_context\user_rules.md | local | 2735 | # User Rules & Persona: "Momo" |  |  |
| .agent_context\walkthrough.md | local | 2692 | # Universal Content Boundary Detection - Verification Results |  |  |

### .github

| File | Status | Size (bytes) | Purpose Seed | Classes | Functions |
|---|---|---:|---|---|---|
| .github\copilot-instructions.md | local | 4772 | # Copilot Instructions |  |  |

### (root)

| File | Status | Size (bytes) | Purpose Seed | Classes | Functions |
|---|---|---:|---|---|---|
| .env | local | 870 | [REDACTED: environment secrets file] |  |  |
| .gitignore | tracked | 439 | # Python |  |  |
| debug_windows.py | local | 687 | from pywinauto import Desktop |  |  |
| inspect_notepad.json | local | 49786 | { |  |  |
| integrity_report_utf8.txt | local | 2139 | Orphan Node: 5a3bc9fc04ede49f refs missing parent c6eb45c6c2bd2d4f |  |  |
| integrity_report.txt | local | 194 | COMPLETENESS: Known element 'page setup' NOT found |  |  |
| notepad_tree.txt | local | 13901 | Control Identifiers: |  |  |
| planner_debug.txt | local | 644 | Looking for: ddc85047566d9a9c |  |  |
| run_validation_experiment.py | tracked | 7108 | import os |  | ensure_dir, save_json, snapshot_cache, collect_logs, parse_run_stats, run_stage, main |
| tasks.csv | local | 44 | task_id,app_name,exe_path,task_description |  |  |

### results

| File | Status | Size (bytes) | Purpose Seed | Classes | Functions |
|---|---|---:|---|---|---|
| results\experiment_data_summary.json | tracked | 7101 | { |  |  |
| results\scientific_executor_tuning_report.md | tracked | 11018 | # Scientific Experiment Report: Executor Tuning v2 |  |  |

### scripts

| File | Status | Size (bytes) | Purpose Seed | Classes | Functions |
|---|---|---:|---|---|---|
| scripts\analyze_cache_integrity.py | tracked | 6323 | """ |  | analyze_integrity, fail, warn |
| scripts\analyze.py | tracked | 0 |  |  |  |
| scripts\check_page_setup.py | local | 936 | import json, os, sys |  |  |
| scripts\crawl_app.py | tracked | 2439 | """ |  | crawl_app |
| scripts\debug_file_menu_expansion.py | local | 3304 | import sys |  | debug_file_expansion, find_file, find_page_setup |
| scripts\debug_orphans.py | local | 2351 | import json |  | debug_orphans |
| scripts\debug_prober.py | local | 1398 | import sys |  | debug_prober |
| scripts\debug_tab_patterns.py | local | 2382 | import sys |  | inspect_tabs |
| scripts\deep_probe_notepad.py | tracked | 1837 | import sys |  | deep_probe |
| scripts\extract_experiment_data.py | tracked | 7014 | """ |  | scan_execution_logs, compute_metrics, scan_cache_files, scan_verification_logs, main |
| scripts\inspect_ax_tree.py | local | 1725 | import sys |  | inspect_app, _analyze_exposure |
| scripts\inspect_file_menu.py | local | 1340 | import sys |  | inspect_file_menu |
| scripts\inspect_open_windows.py | local | 1883 | import sys |  | inspect_popup |
| scripts\scientific_llm_test.py | tracked | 23302 | # scripts/scientific_llm_test.py | Tee | generate_run_id, __init__, write, flush, fileno, generate_metadata, generate_checksums, build_results, write_execution_log, main |
| scripts\scientific_mass_test.py | tracked | 13726 | # scripts/scientific_mass_test.py | Tee | generate_run_id, generate_metadata, generate_results_from_harness, generate_checksums, generate_validation_report, main, __init__, write, flush, fileno |
| scripts\simple_connect.py | local | 869 | from pywinauto import Application, Desktop |  |  |
| scripts\target_file_menu.py | local | 1884 | import sys |  | probe_file_menu |
| scripts\trace_open_task.py | local | 1028 | """Extract full execution trace for failed tasks from Run 1 console.log""" |  |  |
| scripts\trace_output.txt | local | 9730 | ============================================================ |  |  |
| scripts\verify_complex_flow.py | local | 3085 | import sys |  | verify_complex_flow |
| scripts\verify_execution.py | local | 1786 | import sys |  | verify_execution |

### src

| File | Status | Size (bytes) | Purpose Seed | Classes | Functions |
|---|---|---:|---|---|---|
| src\automation\__init__.py | tracked | 309 | # automation_tree/__init__.py |  |  |
| src\automation\builder.py | tracked | 10540 | # automation_tree/builder.py |  | get_patterns, get_rect, truncate, node_from_elem, count_nodes, build_tree_from_window, save_tree |
| src\automation\execution_planner.py | tracked | 16221 | # automation_tree/execution_planner.py |  | log_execution, build_execution_plan, execute_execution_plan, _validate_start_element, _execute_action_on_element, _recover_step, _verify_path_continuity, execute_with_self_healing, _update_cache_from_tree, _walk_and_add |
| src\automation\fingerprint.py | tracked | 3293 | # automation_tree/fingerprint.py |  | normalize_text, node_identity_string, compute_hybrid_fingerprint, compute_fingerprint, compute_tree_hash, rec |
| src\automation\matcher.py | tracked | 13468 | # automation_tree/matcher.py |  | normalize_text, strip_suffix, numeric_normalize, tokenize_and_normalize, token_jaccard, subset_score, name_similarity, history_bonus, length_penalty, match_score, log_match_debug, init_debug_log, find_cached_element |
| src\automation\prober.py | tracked | 39667 | # automation_tree/prober.py | UIProber | __init__, _get_probe_action, log, is_safe, is_timed_out, _is_content_boundary, _is_data_explosion, _is_content_popup, probe_window, _phase1_static_snapshot, _store_tree_phase1, _phase2_bfs_probing, _is_invoke_safe, _phase3_dialog_probing, _execute_exposure_steps, _find_element_live, _quick_node, _capture_new_elements, _scan_popups, _store_tree_phase2, _dequeue_data_children, _take_action, _reset_ui, reset_ui |
| src\automation\storage.py | tracked | 10234 | # automation_tree/storage.py | CacheSession | safe_filename, get_cache_path, utc_now_iso, load_cache, save_cache, truncate, add_element, record_success, remove_element, get_all_elements, clear_cache, __init__, add, has, get, count, flush, stats |
| src\harness\__init__.py | tracked | 483 | # harness/__init__.py |  |  |
| src\harness\app_controller.py | tracked | 17233 | # harness/app_controller.py | AppController | __init__, pre_start_cleanup, start, _start_electron, _warmup_accessibility, connect, start_or_connect, close, _get_window, get_window, terminate_app, kill, focus, is_running, create_controller |
| src\harness\ax_executor.py | tracked | 13771 | # harness/ax_executor.py |  | log_candidate, search_elements, execute_element, cache_element, is_menu_action, get_keyboard_fallback, try_keyboard_fallback, rescan_tree, find_and_execute |
| src\harness\config.py | tracked | 8086 | # harness/config.py |  | get_available_apps, get_tasks_for_app, get_app_config |
| src\harness\experiment_logger.py | tracked | 9239 | # harness/experiment_logger.py | ExperimentLogger | __init__, start_experiment, _write_manifest, _log_jsonl, log_execution, log_verification, log_matcher, log_vlm, finalize_experiment, _percentile |
| src\harness\full_execution_trace_logger.py | tracked | 4626 | import os | FullExecutionTraceLogger | __init__, _log, log_task_start, log_cache_check, log_planner_execution, log_ax_execution, log_vision_execution, log_recovery_event, log_verification, log_task_end |
| src\harness\full_hybrid_harness.py | tracked | 4851 | import os |  | capture_screenshot, grok_detect, ax_targeted_action, run_app |
| src\harness\locator.py | tracked | 10562 | # harness/locator.py |  | _safe_descendants, _reacquire_toplevel_window, _score_element, _search_descendants, locate_element_by_fingerprint, compute_fuzzy_score, recover_element |
| src\harness\logger.py | tracked | 8707 | # harness/logger.py | ExecutionLog, RunSummary, HarnessLogger, RedirectStdout, TeeStream | __post_init__, __init__, log_execution, save_app_log, save_summary, log_execution_event, save_all, __init__, __enter__, __exit__, _make_stream, write, flush, isatty, create_logger |
| src\harness\main.py | tracked | 20461 | # harness/main.py |  | execute_located_element, execute_task, run_app, run_all, run_discovery, main |
| src\harness\ui_state_manager.py | tracked | 15815 | # harness/ui_state_manager.py |  | _safe_descendants, _elem_prop, _matches_any, _find_back_button, _has_home_landmarks, _has_back_button, _is_truly_home, _has_dialog, ensure_home_state |
| src\harness\verification.py | tracked | 8635 | # harness/verification.py | VerificationResult, VerificationEngine | __init__, capture_full_state, compute_image_hash, _compute_average_hash, verify, _compare_properties, _compare_text_maps, capture_state, verify_action, quick_verify, deep_verify |
| src\harness\vision_executor.py | tracked | 7512 | # harness/vision_executor.py | VisionResult | capture_screenshot, locate_element, locate_elements, execute_action, detect_and_click, _vision_task |
| src\harness\vlm_provider.py | tracked | 12437 | # harness/vlm_provider.py | BaseVLM, GeminiVLM, HFVLM | log_debug, log_error, load_image_base64, get_image_dimensions, validate_bbox, parse_coordinates_from_response, __init__, rotate_key, current_key, _call_api, locate_elements, __init__, _call_api, __init__, _call_api, get_available_vlm, locate_elements |
| src\llm\__init__.py | tracked | 69 | # src/llm/__init__.py |  |  |
| src\llm\llm_client.py | tracked | 13644 | # src/llm/llm_client.py | KeySlot, KeyPool, LLMResponse, LLMClient | is_available, __init__, _load_keys, next_gemini, next_claude, _next, mark_success, mark_failure, __init__, call, _call_gemini, _call_claude, health_check, get_client |
| src\llm\orchestrator.py | tracked | 13183 | # src/llm/orchestrator.py | StepRecord, ExecutionTrace, Orchestrator | __init__, execute, _build_context, _build_prompt, _parse_response, run_instruction |
| src\llm\step_executor.py | tracked | 7302 | # src/llm/step_executor.py |  | execute_click, execute_type, execute_hotkey, execute_wait, execute_step |
| src\utils\seed_cache.py | tracked | 1407 | import json |  | seed_cache |
| src\utils\uia_utils.py | tracked | 2606 | # uia_utils.py |  | attach_or_start, dump_window_tree, rec, find_candidate_by_name, try_invoke |

### tests

| File | Status | Size (bytes) | Purpose Seed | Classes | Functions |
|---|---|---:|---|---|---|
| tests\automation\test_builder_storage.py | local | 5349 | # automation_tree/test_builder_storage.py |  | find_actionable_nodes, main |
| tests\automation\test_matcher_cases.py | local | 7541 | # automation_tree/test_matcher_cases.py |  | test_format_menu_exact, test_format_menu_false_positive, test_numeric_normalization, test_exact_match, test_history_bonus, test_suffix_normalization, test_click_one_button, main |
| tests\harness\test_vision_health.py | local | 5437 | # test_vision_health.py |  | get_api_keys, create_test_image, test_vision_api, main |
| tests\harness\test_vlm_provider.py | local | 4639 | # harness/test_vlm_provider.py |  | create_test_screenshot, test_vlm_provider, main |
| tests\integration\test_lifecycle.py | local | 2602 | import sys |  | test_notepad_lifecycle |
| tests\integration\test_planner.py | local | 5640 | import sys | MockLogger | validate_planner_phase4, __init__, log_execution |

## 5) Gaps/Notable Signals For Incoming Agent

- No packaging manifest detected in this repo root (pyproject.toml/requirements.txt absent). Environment appears managed via local .venv.
- .env exists and contains API credentials; treat as sensitive and rotate if exposed.
- tests/ exists but is currently untracked in this workspace state.
- scripts/analyze.py is currently empty (0 bytes).
- Repository contains both source-of-truth implementation and large generated runtime artifacts; keep them separated in analysis.
