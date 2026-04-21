"""Layer 1 execution agent: plan, execute one step, verify, and replan."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sara.config import (
    DEFAULT_USE_VISION,
    MAX_PLAN_STEPS,
    MAX_REPLAN_ROUNDS,
    STEP_RETRY_LIMIT,
)
from sara.execution import browser_macros, path_policy
from sara.llm import service as llm_service
from sara.workflow_policy import (
    extract_save_as_filename,
    should_allow_browser_navigation_soft_verification,
    should_allow_save_dialog_soft_verification,
)
from src.harness import verification
from src.llm.step_executor import execute_step


logger = logging.getLogger("sara.execution.agent")


@dataclass
class StepTrace:
    """Detailed trace for each attempted step execution."""

    step_index: int
    action: Dict[str, Any]
    attempt: int
    replan_round: int
    success: bool
    execution_method: str
    execution_error: str = ""
    verification_success: bool = False
    verification_signal: str = ""
    latency_ms: int = 0


@dataclass
class AgentRunResult:
    """Execution outcome for one user command."""

    app_name: str
    command: str
    success: bool = False
    done_reason: str = ""
    error: str = ""
    total_ms: int = 0
    replan_rounds_used: int = 0
    used_macro_plan: bool = False
    used_vision: bool = False
    steps: List[StepTrace] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionAgent:
    """Strict step-by-step execution loop with verification gate."""

    def __init__(
        self,
        use_vision: bool = DEFAULT_USE_VISION,
        max_plan_steps: int = MAX_PLAN_STEPS,
        max_replan_rounds: int = MAX_REPLAN_ROUNDS,
        step_retry_limit: int = STEP_RETRY_LIMIT,
        trace_root: str = "runs/layer1_agentic",
    ):
        self.use_vision = use_vision
        self.max_plan_steps = max_plan_steps
        self.max_replan_rounds = max_replan_rounds
        self.step_retry_limit = step_retry_limit
        self.trace_root = trace_root
        logger.info(
            "ExecutionAgent initialized use_vision=%s max_plan_steps=%s max_replan_rounds=%s step_retry_limit=%s trace_root=%s",
            self.use_vision,
            self.max_plan_steps,
            self.max_replan_rounds,
            self.step_retry_limit,
            self.trace_root,
        )

    def execute(
        self,
        window,
        app_name: str,
        command: str,
        initial_plan: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> AgentRunResult:
        start_time = time.time()
        logger.info(
            "Execution start app=%s command=%r initial_plan_steps=%s",
            app_name,
            command,
            len(initial_plan or []),
        )
        run = AgentRunResult(
            app_name=app_name,
            command=command,
            used_vision=self.use_vision,
            used_macro_plan=bool(initial_plan),
        )

        failure_context = ""
        plan = initial_plan

        for replan_round in range(self.max_replan_rounds + 1):
            run.replan_rounds_used = replan_round
            logger.info("Replan round=%s app=%s", replan_round, app_name)

            if not plan:
                plan = llm_service.get_automation_plan(
                    command=command,
                    app_name=app_name,
                    failure_context=failure_context,
                )
                logger.info("Planner produced steps=%s", len(plan or []))

            if not plan and app_name in browser_macros.BROWSER_APPS:
                plan = browser_macros.get_macro_steps(app_name, command)
                if plan:
                    run.used_macro_plan = True
                    logger.info("Using browser macro fallback steps=%s", len(plan))

            if not plan:
                failure_context = "Planner returned no executable steps"
                logger.warning("Planner returned no steps; continuing to next replan round")
                continue

            plan = plan[: self.max_plan_steps]
            if not any(str(step.get("action", "")).strip().upper() == "DONE" for step in plan):
                plan.append({"action": "DONE"})

            plan_failed = False
            for step_index, step in enumerate(plan, start=1):
                action = self._normalize_action(step)
                action_type = action.get("action_type", "")
                logger.info(
                    "Step begin index=%s action=%s target=%s",
                    step_index,
                    action_type,
                    action.get("target", ""),
                )

                if action_type == "DONE":
                    run.success = True
                    run.done_reason = "Execution finished with DONE action"
                    run.total_ms = int((time.time() - start_time) * 1000)
                    self._write_trace(run)
                    logger.info("Execution completed by DONE action total_ms=%s", run.total_ms)
                    return run

                if action_type not in {"CLICK", "TYPE", "HOTKEY", "WAIT"}:
                    failure_context = f"Unsupported action at step {step_index}: {action_type or 'EMPTY'}"
                    plan_failed = True
                    logger.warning("Unsupported action encountered step=%s action=%s", step_index, action_type)
                    break

                step_success = False
                for attempt in range(1, self.step_retry_limit + 2):
                    attempt_start = time.time()
                    pre_state = verification.capture_state(window)

                    step_use_vision = self.use_vision
                    policy_reason = "vision-enabled-by-config" if self.use_vision else "default-no-vision"
                    if action_type == "CLICK":
                        step_use_vision, policy_reason = path_policy.should_enable_vision(
                            app_name=app_name,
                            target=action.get("target", ""),
                            default_use_vision=self.use_vision,
                        )

                    exec_result = execute_step(
                        action,
                        window=window,
                        app_name=app_name,
                        use_vision=step_use_vision,
                    )

                    verification_success = False
                    verification_signal = ""
                    if exec_result.get("success"):
                        ver_result = verification.quick_verify(window, pre_state)
                        verification_success = bool(ver_result.success)
                        verification_signal = ver_result.primary_signal or ""

                    if action_type == "WAIT" and exec_result.get("success"):
                        verification_success = True
                        if not verification_signal:
                            verification_signal = "wait_elapsed"

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
                    step_trace = StepTrace(
                        step_index=step_index,
                        action={**action, "policy_reason": policy_reason, "use_vision": step_use_vision},
                        attempt=attempt,
                        replan_round=replan_round,
                        success=bool(exec_result.get("success") and verification_success),
                        execution_method=str(exec_result.get("method", "")),
                        execution_error=str(exec_result.get("error", "")),
                        verification_success=verification_success,
                        verification_signal=verification_signal,
                        latency_ms=latency_ms,
                    )
                    run.steps.append(step_trace)
                    if progress_callback is not None:
                        try:
                            progress_callback(
                                {
                                    "step_index": step_index,
                                    "attempt": attempt,
                                    "action": dict(action),
                                    "success": step_trace.success,
                                    "execution_method": step_trace.execution_method,
                                    "verification_signal": verification_signal,
                                    "execution_error": step_trace.execution_error,
                                }
                            )
                        except Exception:
                            logger.debug("Progress callback raised; ignoring", exc_info=True)
                    logger.info(
                        "Step attempt index=%s attempt=%s success=%s method=%s verify=%s latency_ms=%s",
                        step_index,
                        attempt,
                        step_trace.success,
                        step_trace.execution_method,
                        step_trace.verification_success,
                        latency_ms,
                    )

                    if step_trace.success:
                        step_success = True
                        break

                if not step_success:
                    plan_failed = True
                    failure_context = self._build_failure_context(step_index, action, run.steps[-1])
                    logger.warning("Step failed index=%s context=%s", step_index, failure_context)
                    break

            if not plan_failed:
                run.success = True
                run.done_reason = "Plan completed without explicit DONE"
                run.total_ms = int((time.time() - start_time) * 1000)
                self._write_trace(run)
                logger.info("Execution completed without explicit DONE total_ms=%s", run.total_ms)
                return run

            plan = None

        run.success = False
        run.error = failure_context or "Execution failed after all replans"
        run.total_ms = int((time.time() - start_time) * 1000)
        self._write_trace(run)
        logger.error("Execution failed app=%s total_ms=%s error=%s", app_name, run.total_ms, run.error)
        return run

    def _normalize_action(self, step: Dict[str, Any]) -> Dict[str, Any]:
        action = str(step.get("action", "")).strip().upper()
        out: Dict[str, Any] = {"action_type": action}

        if "target" in step:
            out["target"] = str(step.get("target", "")).strip()
        if "text" in step:
            out["text"] = str(step.get("text", ""))
        if "keys" in step:
            out["keys"] = str(step.get("keys", ""))
        if "seconds" in step:
            try:
                out["seconds"] = float(step.get("seconds", 0.5))
            except (TypeError, ValueError):
                out["seconds"] = 0.5

        return out

    def _build_failure_context(self, step_index: int, action: Dict[str, Any], trace: StepTrace) -> str:
        return (
            f"Step {step_index} failed. "
            f"Action={action.get('action_type')} "
            f"Method={trace.execution_method} "
            f"ExecError={trace.execution_error or 'NONE'} "
            f"Verified={trace.verification_success}"
        )

    def _write_trace(self, run: AgentRunResult) -> None:
        if not self.trace_root:
            return

        os.makedirs(self.trace_root, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_app = "".join(ch for ch in run.app_name.lower() if ch.isalnum() or ch in {"_", "-"})
        trace_path = os.path.join(self.trace_root, f"{ts}_{safe_app}_agent_trace.json")

        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(run.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("Execution trace written path=%s", trace_path)
