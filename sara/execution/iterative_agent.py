"""Iterative runtime execution agent for one-action-per-turn LLM control."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sara.config import (
    DEFAULT_USE_VISION,
    HIGH_RISK_KEYWORDS,
    ITERATIVE_AX_SNAPSHOT_LIMIT,
    ITERATIVE_MAX_CONSECUTIVE_FAILURES,
    ITERATIVE_MAX_STEPS,
    STEP_RETRY_LIMIT,
)
from sara.execution import browser_macros
from sara.llm import service as llm_service
from sara.workflow_policy import (
    extract_save_as_filename,
    should_allow_browser_navigation_soft_verification,
    should_allow_save_dialog_soft_verification,
)
from src.harness import verification
from src.llm.step_executor import execute_step


logger = logging.getLogger("sara.execution.iterative")


@dataclass
class IterativeStepTrace:
    """Detailed trace for one iterative action attempt."""

    step_index: int
    thought: str
    action: Dict[str, Any]
    attempt: int
    success: bool
    execution_method: str
    execution_error: str = ""
    verification_success: bool = False
    verification_signal: str = ""
    latency_ms: int = 0
    observation: str = ""


@dataclass
class IterativeRunResult:
    """Execution outcome for one iterative command run."""

    app_name: str
    command: str
    success: bool = False
    done_reason: str = ""
    error: str = ""
    total_ms: int = 0
    llm_calls: int = 0
    used_vision: bool = False
    steps: List[IterativeStepTrace] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IterativeExecutionAgent:
    """Runs an iterative LLM loop: propose one action, execute, verify, observe."""

    def __init__(
        self,
        use_vision: bool = DEFAULT_USE_VISION,
        max_steps: int = ITERATIVE_MAX_STEPS,
        max_consecutive_failures: int = ITERATIVE_MAX_CONSECUTIVE_FAILURES,
        step_retry_limit: int = STEP_RETRY_LIMIT,
        ax_snapshot_limit: int = ITERATIVE_AX_SNAPSHOT_LIMIT,
    ):
        self.use_vision = bool(use_vision)
        self.max_steps = max(1, int(max_steps))
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))
        self.step_retry_limit = max(0, int(step_retry_limit))
        self.ax_snapshot_limit = max(10, int(ax_snapshot_limit))
        logger.info(
            "IterativeExecutionAgent initialized use_vision=%s max_steps=%s max_consecutive_failures=%s step_retry_limit=%s ax_snapshot_limit=%s",
            self.use_vision,
            self.max_steps,
            self.max_consecutive_failures,
            self.step_retry_limit,
            self.ax_snapshot_limit,
        )

    def execute(
        self,
        window,
        app_name: str,
        command: str,
        ui_summary: str = "",
        memory_context: str = "",
        planning_bias: str = "",
        approval_callback: Optional[Callable[[Dict[str, Any]], bool]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> IterativeRunResult:
        start_time = time.time()
        run = IterativeRunResult(
            app_name=app_name,
            command=command,
            used_vision=self.use_vision,
        )

        observations: List[str] = []
        consecutive_failures = 0
        requires_playback_confirmation = browser_macros.needs_live_ax_selection(app_name, command)
        playback_confirmed = False
        bootstrap_plan = browser_macros.get_iterative_bootstrap_steps(app_name, command) or []
        macro_plan = bootstrap_plan or (browser_macros.get_macro_steps(app_name, command) or [])
        if bootstrap_plan:
            logger.info(
                "Iterative run bootstrapped for live-AX selection app=%s steps=%d",
                app_name,
                len(bootstrap_plan),
            )
        elif macro_plan:
            logger.info(
                "Iterative run bootstrapped with deterministic macro app=%s steps=%d",
                app_name,
                len(macro_plan),
            )

        for step_index in range(1, self.max_steps + 1):
            if macro_plan and step_index <= len(macro_plan):
                action = dict(macro_plan[step_index - 1])
                action_type = str(action.get("action", "")).strip().upper()
                thought = "deterministic macro step"
            else:
                runtime_ui = self._build_runtime_ui_snapshot(window, command=command)
                action = llm_service.get_next_automation_action(
                    command=command,
                    app_name=app_name,
                    ui_summary=ui_summary,
                    runtime_ui_snapshot=runtime_ui,
                    memory_context=memory_context,
                    planning_bias=planning_bias,
                    step_index=step_index,
                    consecutive_failures=consecutive_failures,
                    recent_observations=observations,
                )
                run.llm_calls += 1
                action_type = str(action.get("action", "")).strip().upper()
                thought = str(action.get("thought", "")).strip()

            if action_type == "DONE":
                if requires_playback_confirmation and not playback_confirmed:
                    consecutive_failures += 1
                    observation = (
                        f"Step {step_index}: DONE rejected because media playback is not confirmed from live AX state"
                    )
                    observations.append(observation)
                    if len(observations) > 12:
                        observations = observations[-12:]
                    logger.info(
                        "Iterative DONE rejected app=%s step=%d reason=playback_not_confirmed consecutive_failures=%d",
                        app_name,
                        step_index,
                        consecutive_failures,
                    )
                    if consecutive_failures >= self.max_consecutive_failures:
                        run.error = "Planner declared DONE before media playback could be confirmed"
                        break
                    continue

                run.success = True
                run.done_reason = str(action.get("reason", "Goal completed")).strip() or "Goal completed"
                run.total_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "Iterative execution completed app=%s steps=%d llm_calls=%d total_ms=%d",
                    app_name,
                    len(run.steps),
                    run.llm_calls,
                    run.total_ms,
                )
                return run

            if action_type == "FAIL":
                run.success = False
                run.error = str(action.get("reason", "Planner declared failure")).strip() or "Planner declared failure"
                run.total_ms = int((time.time() - start_time) * 1000)
                logger.warning(
                    "Iterative planner emitted FAIL app=%s step=%d reason=%s",
                    app_name,
                    step_index,
                    run.error,
                )
                return run

            if action_type not in {"CLICK", "TYPE", "HOTKEY", "WAIT"}:
                consecutive_failures += 1
                observation = f"Step {step_index}: invalid action type '{action_type or 'EMPTY'}'"
                observations.append(observation)
                logger.warning("%s", observation)
                if consecutive_failures >= self.max_consecutive_failures:
                    run.error = "Iterative planner produced invalid actions repeatedly"
                    break
                continue

            if self._is_high_risk_action(action):
                approved = True
                if approval_callback is not None:
                    approved = bool(
                        approval_callback(
                            {
                                "command": command,
                                "app_name": app_name,
                                "risk_reason": "high-risk iterative action detected",
                                "plan": [action],
                            }
                        )
                    )
                if not approved:
                    run.error = "Approval denied for high-risk iterative action"
                    run.total_ms = int((time.time() - start_time) * 1000)
                    logger.warning("Iterative action denied by approval gate app=%s step=%d", app_name, step_index)
                    return run

            step_ok = False
            for attempt in range(1, self.step_retry_limit + 2):
                attempt_start = time.time()
                pre_state = verification.capture_state(window)

                exec_result = execute_step(
                    self._to_executor_action(action),
                    window=window,
                    app_name=app_name,
                    use_vision=self.use_vision,
                )

                verification_success = False
                verification_signal = ""
                if exec_result.get("success"):
                    ver_result = verification.quick_verify(window, pre_state)
                    verification_success = bool(ver_result.success)
                    verification_signal = ver_result.primary_signal or ""

                if action_type == "WAIT" and exec_result.get("success"):
                    verification_success = True
                    verification_signal = verification_signal or "wait_elapsed"

                if exec_result.get("success") and not verification_success:
                    requested_filename = extract_save_as_filename(command)
                    if should_allow_save_dialog_soft_verification(
                        action=action,
                        command=command,
                        requested_filename=requested_filename,
                    ):
                        verification_success = True
                        verification_signal = verification_signal or "soft_policy"
                    elif should_allow_browser_navigation_soft_verification(
                        action=action,
                        command=command,
                        app_name=app_name,
                    ):
                        verification_success = True
                        verification_signal = verification_signal or "soft_browser_nav"

                latency_ms = int((time.time() - attempt_start) * 1000)
                success = bool(exec_result.get("success") and verification_success)
                observation = self._build_observation(
                    step_index=step_index,
                    action=action,
                    exec_result=exec_result,
                    success=success,
                    verification_signal=verification_signal,
                )
                trace = IterativeStepTrace(
                    step_index=step_index,
                    thought=thought,
                    action=dict(action),
                    attempt=attempt,
                    success=success,
                    execution_method=str(exec_result.get("method", "")),
                    execution_error=str(exec_result.get("error", "")),
                    verification_success=verification_success,
                    verification_signal=verification_signal,
                    latency_ms=latency_ms,
                    observation=observation,
                )
                run.steps.append(trace)

                observations.append(observation)
                if len(observations) > 12:
                    observations = observations[-12:]

                if progress_callback is not None:
                    try:
                        progress_callback(
                            {
                                "step_index": step_index,
                                "attempt": attempt,
                                "action": dict(action),
                                "success": success,
                                "execution_method": trace.execution_method,
                                "verification_signal": verification_signal,
                                "execution_error": trace.execution_error,
                            }
                        )
                    except Exception:
                        logger.debug("Progress callback raised; ignoring", exc_info=True)

                logger.info(
                    "Iterative step=%d attempt=%d action=%s success=%s method=%s verify=%s latency_ms=%d",
                    step_index,
                    attempt,
                    action_type,
                    success,
                    trace.execution_method,
                    trace.verification_success,
                    latency_ms,
                )

                if success:
                    if requires_playback_confirmation and self._has_media_playback_evidence(window):
                        playback_confirmed = True
                    step_ok = True
                    consecutive_failures = 0
                    break

            if not step_ok:
                consecutive_failures += 1
                if consecutive_failures >= self.max_consecutive_failures:
                    run.error = (
                        f"Execution stalled after {consecutive_failures} consecutive failures "
                        f"(last action: {action_type})"
                    )
                    break

        run.success = False
        if not run.error:
            run.error = "Reached iterative max step budget without DONE"
        run.total_ms = int((time.time() - start_time) * 1000)
        logger.warning(
            "Iterative execution failed app=%s llm_calls=%d steps=%d error=%s",
            app_name,
            run.llm_calls,
            len(run.steps),
            run.error,
        )
        return run

    def _build_runtime_ui_snapshot(self, window, command: str = "") -> str:
        lines: List[str] = []

        try:
            title = str(window.window_text() or "").strip()
            if title:
                lines.append(f"Window title: {title}")
        except Exception:
            lines.append("Window title: unavailable")

        focused = ""
        sample: List[str] = []
        seen = set()
        candidates: List[Dict[str, Any]] = []
        focus_tokens = self._extract_focus_tokens(command)

        try:
            descendants = list(window.descendants()[: self.ax_snapshot_limit])
        except Exception:
            descendants = []

        for elem in descendants:
            name = ""
            control = ""
            try:
                name = str(elem.window_text() or "").strip()
            except Exception:
                name = ""
            try:
                control = str(getattr(elem.element_info, "control_type", "") or "").strip()
            except Exception:
                control = ""

            try:
                has_focus = bool(getattr(elem, "has_keyboard_focus")())
                if has_focus and (name or control):
                    focused = f"{name or '<unnamed>'} ({control or 'Unknown'})"
            except Exception:
                pass

            if not name:
                continue

            key = (name.lower(), control.lower())
            if key in seen:
                continue
            seen.add(key)

            sample.append(f"- {name} ({control or 'Unknown'})")
            if len(sample) >= 40:
                break

            if focus_tokens and name:
                lowered_name = name.lower()
                score = sum(1 for token in focus_tokens if token in lowered_name)
                if score > 0:
                    candidates.append(
                        {
                            "score": score,
                            "name": name,
                            "control": control or "Unknown",
                        }
                    )

        lines.append(f"AX descendants sampled: {len(descendants)}")
        lines.append(f"Focused element: {focused or 'unknown'}")

        if candidates:
            ranked = sorted(candidates, key=lambda item: (-int(item["score"]), len(str(item["name"]))))
            lines.append("Task-relevant AX candidates:")
            for item in ranked[:12]:
                lines.append(f"- [{item['score']}] {item['name']} ({item['control']})")

        if sample:
            lines.append("Visible labeled elements:")
            lines.extend(sample)
        else:
            lines.append("Visible labeled elements: none captured")

        return "\n".join(lines)

    def _extract_focus_tokens(self, command: str) -> List[str]:
        text = str(command or "").lower()
        text = re.sub(r"[^a-z0-9\s]+", " ", text)
        raw_tokens = [tok for tok in text.split() if len(tok) >= 3]

        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "into",
            "open",
            "click",
            "type",
            "press",
            "play",
            "watch",
            "listen",
            "search",
            "find",
            "youtube",
            "browser",
            "brave",
            "chrome",
        }

        tokens: List[str] = []
        seen = set()
        for token in raw_tokens:
            if token in stopwords:
                continue
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
        return tokens

    def _has_media_playback_evidence(self, window) -> bool:
        title = ""
        try:
            title = str(window.window_text() or "").strip().lower()
        except Exception:
            title = ""

        title_looks_like_watch = bool(title) and "youtube" in title and not any(
            token in title for token in ("search", "results", "shorts", "home")
        )

        playback_hints = {
            "theater mode",
            "full screen",
            "mini player",
            "picture in picture",
            "captions",
            "subtitles",
            "playback speed",
            "remaining time",
            "current time",
            "mute (m)",
            "pause (k)",
        }

        seen_hints = set()
        try:
            descendants = list(window.descendants()[: self.ax_snapshot_limit])
        except Exception:
            descendants = []

        for elem in descendants:
            try:
                name = str(elem.window_text() or "").strip().lower()
            except Exception:
                name = ""
            if not name:
                continue

            if "watch?v=" in name:
                return True

            for hint in playback_hints:
                if hint in name:
                    seen_hints.add(hint)

            if len(seen_hints) >= 1:
                return True

        return title_looks_like_watch and len(seen_hints) >= 1

    def _to_executor_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        action_type = str(action.get("action", "")).strip().upper()
        out: Dict[str, Any] = {"action_type": action_type}

        if "target" in action:
            out["target"] = str(action.get("target", "")).strip()
        if "text" in action:
            out["text"] = str(action.get("text", ""))
        if "keys" in action:
            out["keys"] = str(action.get("keys", ""))
        if "seconds" in action:
            try:
                out["seconds"] = float(action.get("seconds", 0.5))
            except (TypeError, ValueError):
                out["seconds"] = 0.5

        return out

    def _is_high_risk_action(self, action: Dict[str, Any]) -> bool:
        text = " ".join(
            [
                str(action.get("target", "")),
                str(action.get("text", "")),
                str(action.get("keys", "")),
                str(action.get("reason", "")),
            ]
        ).lower()
        return any(keyword in text for keyword in HIGH_RISK_KEYWORDS)

    def _build_observation(
        self,
        step_index: int,
        action: Dict[str, Any],
        exec_result: Dict[str, Any],
        success: bool,
        verification_signal: str,
    ) -> str:
        action_type = str(action.get("action", "")).strip().upper()
        detail = ""
        if action_type == "CLICK":
            detail = str(action.get("target", ""))
        elif action_type == "HOTKEY":
            detail = str(action.get("keys", ""))
        elif action_type == "TYPE":
            detail = f"text_len={len(str(action.get('text', '')))}"
        elif action_type == "WAIT":
            detail = f"seconds={action.get('seconds', 0.5)}"

        return (
            f"Step {step_index}: {action_type} {detail} -> "
            f"{'SUCCESS' if success else 'FAILED'} "
            f"(method={exec_result.get('method', 'UNKNOWN')}, "
            f"verify={verification_signal or 'none'}, "
            f"error={exec_result.get('error', '') or 'none'})"
        )
