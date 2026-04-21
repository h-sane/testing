"""Top-level SARA host agent orchestrating privacy, memory, intent, and execution."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sara.app_agents import get_agent_for_app
from sara.config import (
    AUTOMATION_CONFIDENCE_THRESHOLD,
    DEFAULT_USE_VISION,
    ENABLE_ITERATIVE_AUTOMATION,
    HIGH_RISK_KEYWORDS,
    PROTECTED_APPS,
    REQUIRE_APPROVAL_FOR_RISKY,
)
from sara.execution import browser_macros
from sara.execution.agent import ExecutionAgent
from sara.execution.iterative_agent import IterativeExecutionAgent
from sara.llm import service as llm_service
from sara.memory.manager import KnowledgeBaseManager
from sara.privacy.router import PrivacyRouter
from sara.workflow_policy import looks_like_text_entry_intent, should_keep_app_open_after_execution
from src.automation import matcher, storage
from src.harness import config as harness_config
from src.harness.app_controller import create_controller


logger = logging.getLogger("sara.host_agent")


@dataclass
class CommandResult:
    command: str
    intent: str = "conversation"
    privacy_route: str = "CLOUD"
    sensitivity: str = "LOW"
    plan: List[Dict[str, Any]] = field(default_factory=list)
    execution_success: bool = False
    response_text: str = ""
    memory_recalled: List[str] = field(default_factory=list)
    facts_stored: Dict[str, Any] = field(default_factory=dict)
    progress_events: List[str] = field(default_factory=list)
    app_agent: str = "Generic"
    tier_used: str = "N/A"
    error: Optional[str] = None

    # Backward-compatible aliases for older scripts that expect legacy names.
    @property
    def tier(self) -> str:
        return self.tier_used

    @property
    def success(self) -> bool:
        return self.execution_success

    @property
    def response(self) -> str:
        return self.response_text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "intent": self.intent,
            "privacy_route": self.privacy_route,
            "sensitivity": self.sensitivity,
            "plan": self.plan,
            "execution_success": self.execution_success,
            "response_text": self.response_text,
            "memory_recalled": self.memory_recalled,
            "facts_stored": self.facts_stored,
            "progress_events": self.progress_events,
            "app_agent": self.app_agent,
            "tier_used": self.tier_used,
            "error": self.error,
        }


class HostAgent:
    """Main orchestration brain for text/voice commands."""

    def __init__(
        self,
        dry_run: bool = True,
        use_vision: bool = DEFAULT_USE_VISION,
        trace_root: str = "runs/layer1_agentic",
        demo_browser: str = "Chrome",
        approval_callback: Optional[Callable[[Dict[str, Any]], bool]] = None,
        terminate_app_after_execute: bool = True,
    ):
        self.dry_run = bool(dry_run)
        self.demo_browser = demo_browser
        self.approval_callback = approval_callback
        self.terminate_app_after_execute = bool(terminate_app_after_execute)
        self.router = PrivacyRouter()
        self.memory = KnowledgeBaseManager()
        self.execution_agent = ExecutionAgent(use_vision=use_vision, trace_root=trace_root)
        self.iterative_execution_agent = IterativeExecutionAgent(use_vision=use_vision)
        self.use_iterative_automation = ENABLE_ITERATIVE_AUTOMATION
        self._active_app = "Notepad"
        self._history: List[CommandResult] = []
        self._media_session: Dict[str, Any] = {
            "active": False,
            "app_name": "",
            "platform": "",
            "query": "",
            "playback_state": "",
            "last_action": "",
            "last_command": "",
            "last_tier": "",
        }
        logger.info(
            "HostAgent initialized dry_run=%s use_vision=%s trace_root=%s terminate_app_after_execute=%s iterative=%s",
            self.dry_run,
            use_vision,
            trace_root,
            self.terminate_app_after_execute,
            self.use_iterative_automation,
        )

    def set_active_app(self, app_name: str) -> None:
        self._active_app = app_name
        logger.info("Active app set to %s", app_name)

    def get_memory_summary(self) -> Dict[str, Any]:
        return self.memory.get_memory_summary()

    def get_history(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self._history[-100:]]

    def get_routing_explanation(self, command: str) -> str:
        return self.router.get_routing_explanation(command)

    def get_system_status(self) -> Dict[str, Any]:
        total = len(self._history)
        success = sum(1 for item in self._history if item.execution_success)
        return {
            "dry_run": self.dry_run,
            "active_app": self._active_app,
            "total_commands": total,
            "successful_commands": success,
            "success_rate": round((success / total), 4) if total else 0.0,
            "require_approval_for_risky": REQUIRE_APPROVAL_FOR_RISKY,
            "automation_confidence_threshold": AUTOMATION_CONFIDENCE_THRESHOLD,
            "iterative_automation_enabled": self.use_iterative_automation,
            "media_session": dict(self._media_session),
            "memory": self.get_memory_summary(),
        }

    def process_command(
        self,
        command: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> CommandResult:
        text = (command or "").strip()
        if not text:
            return CommandResult(command="", response_text="Please enter a command.")

        resolved_text = self.memory.resolve_references(text)
        if resolved_text != text:
            logger.info("Memory reference resolved command=%r -> %r", text, resolved_text)

        logger.info("Command received app=%s dry_run=%s text=%r", self._active_app, self.dry_run, text)

        route, sensitivity = self.router.route(resolved_text)
        recalled = self.memory.recall_memories(resolved_text)
        app_context = self._get_automation_app_context()
        llm_context = self._build_llm_context(recalled, resolved_text, app_context=app_context)
        understanding = llm_service.get_command_understanding(
            text,
            memory_context=llm_context,
        )
        intent = str(understanding.get("intent", "conversation"))
        action_type = str(understanding.get("action_type", "conversation"))
        confidence = float(understanding.get("confidence", 0.0) or 0.0)

        if browser_macros.is_media_followup_command(resolved_text) and bool(self._media_session.get("active")):
            intent = "automation"
            action_type = "automation"
            confidence = max(confidence, 0.9)
            logger.info("Media continuation override applied for command=%r", resolved_text)

        logger.info(
            "Understanding route=%s sensitivity=%s intent=%s action_type=%s confidence=%.2f recalled=%d",
            route,
            sensitivity.value,
            intent,
            action_type,
            confidence,
            len(recalled),
        )

        result = CommandResult(
            command=text,
            intent=intent,
            privacy_route=route,
            sensitivity=sensitivity.value,
            memory_recalled=recalled,
        )
        interaction_app = self._active_app

        if intent == "remember" or action_type in {"memory_write", "memory_update", "memory_delete", "memory_read"}:
            if action_type == "memory_read":
                memory_answer = self.memory.answer_memory_query(text)
                result.execution_success = True
                result.tier_used = "MEMORY_READ"
                result.response_text = memory_answer or "I do not have stored memory for that yet."
                logger.info("Remember intent rerouted to memory read")
            elif action_type == "memory_delete":
                operations = llm_service.extract_memory_operations(text)
                mutation = self.memory.apply_memory_operations(operations, source_text=text)
                removed_facts = mutation.get("removed_facts", []) if isinstance(mutation, dict) else []
                removed_relations = mutation.get("removed_relations", []) if isinstance(mutation, dict) else []

                result.execution_success = True
                result.tier_used = "MEMORY_DELETE"
                if removed_facts or removed_relations:
                    parts: List[str] = []
                    if removed_facts:
                        parts.append("facts=" + ", ".join(removed_facts))
                    if removed_relations:
                        parts.append("relations=" + ", ".join(removed_relations))
                    result.response_text = "Memory updated. Removed " + " | ".join(parts)
                else:
                    result.response_text = "I could not find matching memory to delete from that request."
                logger.info(
                    "Memory delete handled removed_facts=%d removed_relations=%d",
                    len(removed_facts),
                    len(removed_relations),
                )
            else:
                facts = llm_service.extract_facts(text)
                memory_graph = llm_service.extract_memory_graph(text)
                relations = memory_graph.get("relations", []) if isinstance(memory_graph, dict) else []
                relation_facts = self._relation_facts(relations)
                combined_facts = dict(facts)
                for key, value in relation_facts.items():
                    if key not in combined_facts:
                        combined_facts[key] = value

                operations = llm_service.extract_memory_operations(text)
                mutation = self.memory.apply_memory_operations(operations, source_text=text)
                removed_facts = mutation.get("removed_facts", []) if isinstance(mutation, dict) else []
                removed_relations = mutation.get("removed_relations", []) if isinstance(mutation, dict) else []

                result.facts_stored = combined_facts
                if combined_facts:
                    self.memory.update_structured_facts(combined_facts)
                if relations:
                    self.memory.update_graph_memory(facts={}, relations=relations, source_text=text)
                result.execution_success = True
                result.tier_used = "MEMORY_UPDATE" if action_type == "memory_update" else "MEMORY_WRITE"

                if combined_facts or relations or removed_facts or removed_relations:
                    parts: List[str] = []
                    if combined_facts:
                        parts.append(", ".join(f"{k}={v}" for k, v in combined_facts.items()))
                    if relations:
                        rel_lines = []
                        for rel in relations[:3]:
                            rel_lines.append(
                                f"{rel.get('subject', 'user')} -{rel.get('relation', '')}-> {rel.get('object', '')}"
                            )
                        if rel_lines:
                            parts.append("relations=" + "; ".join(rel_lines))
                    if removed_facts:
                        parts.append("removed_facts=" + ", ".join(removed_facts))
                    if removed_relations:
                        parts.append("removed_relations=" + ", ".join(removed_relations))
                    result.response_text = "Remembered: " + " | ".join(parts)
                else:
                    result.response_text = "Noted. I saved this interaction in memory context."
                logger.info(
                    "Remember intent stored_facts=%d stored_relations=%d removed_facts=%d removed_relations=%d",
                    len(combined_facts),
                    len(relations),
                    len(removed_facts),
                    len(removed_relations),
                )

        elif intent == "screen_read":
            screen = self._execute_screen_read(resolved_text, recalled)
            result.execution_success = bool(screen.get("success"))
            result.tier_used = str(screen.get("tier", "SCREEN_READ"))
            result.response_text = str(screen.get("response", ""))
            result.error = str(screen.get("error", "") or "") or None
            logger.info("Screen-read result success=%s tier=%s", result.execution_success, result.tier_used)

        elif intent == "automation":
            if confidence < AUTOMATION_CONFIDENCE_THRESHOLD:
                result.execution_success = False
                result.response_text = (
                    "I am not confident enough to execute this safely. "
                    "Please rephrase with explicit action and target."
                )
                result.error = f"Low confidence ({confidence:.2f}) for automation"
                logger.warning("Automation blocked by confidence policy: %.2f < %.2f", confidence, AUTOMATION_CONFIDENCE_THRESHOLD)
            else:
                target_app = self._resolve_app(resolved_text, None, app_context=app_context)
                if not target_app:
                    result.execution_success = False
                    result.error = "Could not resolve target app from configured automation apps"
                    result.response_text = (
                        "I could not determine a safe target app for this command. "
                        "Please mention the app explicitly or verify app discovery/cache readiness in Crawler."
                    )
                    logger.warning("Automation target app resolution failed command=%r", resolved_text)
                    outcome = result.error
                    self.memory.store_interaction(resolved_text, outcome, intent, app_name=interaction_app)
                    self._history.append(result)
                    return result

                interaction_app = target_app
                logger.info(
                    "Automation target app resolved app=%s active_app=%s command=%r",
                    target_app,
                    self._active_app,
                    resolved_text,
                )

                agent = get_agent_for_app(target_app)
                result.app_agent = agent.app_name
                planning_bias = self.memory.get_planning_bias(target_app, resolved_text)
                use_iterative_live = bool(not self.dry_run and self.use_iterative_automation)

                plan: List[Dict[str, Any]] = []
                if not use_iterative_live:
                    plan = llm_service.get_automation_plan(
                        command=resolved_text,
                        active_app=target_app,
                        ui_summary=agent.get_ui_summary(),
                        context=llm_context,
                        planning_bias=planning_bias,
                    )
                    result.plan = plan
                    logger.info("Automation plan generated steps=%d app_agent=%s", len(plan), result.app_agent)
                else:
                    logger.info("Iterative automation active for live execution app=%s", target_app)

                if self._is_high_risk_command(resolved_text, plan):
                    approved = self._request_approval(
                        {
                            "command": resolved_text,
                            "app_name": target_app,
                            "risk_reason": "high-risk keyword/action detected",
                            "plan": plan,
                        }
                    )
                    if not approved:
                        result.execution_success = False
                        result.response_text = "Action canceled: approval not granted for high-risk command."
                        result.error = "Approval denied"
                        outcome = result.error
                        self.memory.store_interaction(resolved_text, outcome, intent, app_name=target_app)
                        self._history.append(result)
                        logger.warning("Automation denied by approval gate command=%r", resolved_text)
                        return result

                if self.dry_run:
                    result.execution_success = True
                    result.tier_used = "DRY_RUN"
                    result.response_text = f"Plan ready with {len(plan)} step(s). Dry-run mode is enabled."
                    self._active_app = target_app
                    logger.info("Dry-run active; plan returned without execution")
                else:
                    execution = self.execute(
                        resolved_text,
                        target_app=target_app,
                        memory_context=llm_context,
                        planning_bias=planning_bias,
                        ui_summary=agent.get_ui_summary(),
                        iterative=use_iterative_live,
                        progress_callback=progress_callback,
                    )
                    result.execution_success = bool(execution.get("success"))
                    result.tier_used = str(execution.get("mode", "AGENTIC_EXECUTION"))
                    result.progress_events = self._build_progress_events(execution)
                    result.error = execution.get("error")
                    if result.execution_success:
                        self._active_app = str(execution.get("app_name", target_app))
                        if result.tier_used == "ITERATIVE":
                            result.response_text = (
                                f"Executed on {execution.get('app_name', self._active_app)} in {execution.get('total_ms', 0)}ms "
                                f"with iterative control ({execution.get('llm_calls', 0)} LLM turns, "
                                f"{len(execution.get('steps', []))} step attempt(s))."
                            )
                        else:
                            result.response_text = (
                                f"Executed on {execution.get('app_name', self._active_app)} "
                                f"in {execution.get('total_ms', 0)}ms."
                            )
                    else:
                        result.response_text = f"Execution failed: {result.error or 'unknown error'}"
                    logger.info(
                        "Automation execution success=%s app=%s tier=%s error=%s",
                        result.execution_success,
                        execution.get("app_name", target_app),
                        result.tier_used,
                        result.error,
                    )
                    self._update_media_session(
                        command=resolved_text,
                        app_name=str(execution.get("app_name", target_app)),
                        execution_success=result.execution_success,
                        tier_used=result.tier_used,
                    )

        else:
            if action_type == "memory_read":
                memory_answer = self.memory.answer_memory_query(text)
                result.execution_success = True
                result.tier_used = "MEMORY_READ"
                if memory_answer:
                    result.response_text = memory_answer
                elif recalled:
                    result.response_text = "From memory:\n- " + "\n- ".join(recalled[:4])
                elif self.memory.get_structured_facts():
                    facts = self.memory.get_structured_facts()
                    pairs = [f"{k}={v}" for k, v in sorted(facts.items())[:6]]
                    result.response_text = "I found these stored facts: " + ", ".join(pairs)
                else:
                    result.response_text = "I do not have stored memory for that yet."
            else:
                result.response_text = llm_service.get_conversational_response(resolved_text, context=llm_context)
                result.execution_success = True

        outcome = "success" if result.execution_success else (result.error or "failed")
        self.memory.store_interaction(text, outcome, intent, app_name=interaction_app)
        self._history.append(result)
        logger.info("Command completed intent=%s success=%s tier=%s", result.intent, result.execution_success, result.tier_used)
        return result

    def execute(
        self,
        command: str,
        target_app: Optional[str] = None,
        allow_protected: bool = False,
        memory_context: str = "",
        planning_bias: str = "",
        ui_summary: str = "",
        iterative: Optional[bool] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        app_name = self._resolve_app(command, target_app)
        logger.info("Execute request resolved_app=%s target_app=%s command=%r", app_name, target_app, command)
        if not app_name:
            return {
                "success": False,
                "app_name": "",
                "command": command,
                "error": "Could not resolve target app",
            }

        if self._is_high_risk_command(command):
            approved = self._request_approval(
                {
                    "command": command,
                    "app_name": app_name,
                    "risk_reason": "high-risk keyword detected",
                    "plan": [],
                }
            )
            if not approved:
                logger.warning("Execution blocked by approval gate app=%s command=%r", app_name, command)
                return {
                    "success": False,
                    "app_name": app_name,
                    "command": command,
                    "error": "Approval denied",
                }

        if app_name in PROTECTED_APPS and not allow_protected:
            logger.warning("Execution blocked by protected-app policy app=%s", app_name)
            return {
                "success": False,
                "app_name": app_name,
                "command": command,
                "error": f"Protected app blocked by policy: {app_name}",
            }

        app_cfg = harness_config.get_app_config(app_name)
        if not app_cfg:
            logger.warning("Execution failed: missing app config for %s", app_name)
            return {
                "success": False,
                "app_name": app_name,
                "command": command,
                "error": f"App config missing for {app_name}",
            }

        exe_path = app_cfg.get("exe", "")
        if not exe_path or not os.path.exists(exe_path):
            logger.warning("Execution failed: executable missing app=%s path=%s", app_name, exe_path)
            return {
                "success": False,
                "app_name": app_name,
                "command": command,
                "error": f"Executable missing for {app_name}: {exe_path}",
            }

        controller = create_controller(app_name, app_cfg)
        if not controller.start_or_connect():
            logger.warning("Execution failed: could not start/connect app=%s", app_name)
            return {
                "success": False,
                "app_name": app_name,
                "command": command,
                "error": f"Could not start/connect to {app_name}",
            }

        try:
            controller.focus()
            window = controller.get_window()
            if not window:
                return {
                    "success": False,
                    "app_name": app_name,
                    "command": command,
                    "error": "Window unavailable after app launch",
                }

            use_iterative = self.use_iterative_automation if iterative is None else bool(iterative)
            logger.info("Execution start app=%s iterative=%s", app_name, use_iterative)
            macro = None
            if bool(self._media_session.get("active")) and str(self._media_session.get("app_name", "")).strip() == app_name:
                macro = browser_macros.get_media_followup_steps(app_name, command)

            if macro:
                logger.info(
                    "Execution media-followup macro selected app=%s steps=%d",
                    app_name,
                    len(macro),
                )
            else:
                macro = browser_macros.get_macro_steps(app_name, command)

            if use_iterative and browser_macros.needs_live_ax_selection(app_name, command):
                logger.info(
                    "Execution live-AX handoff enabled app=%s command=%r; skipping full macro completion",
                    app_name,
                    command,
                )
                macro = None

            if macro:
                logger.info(
                    "Execution deterministic macro selected app=%s steps=%d iterative_requested=%s",
                    app_name,
                    len(macro),
                    use_iterative,
                )
                run = self.execution_agent.execute(
                    window=window,
                    app_name=app_name,
                    command=command,
                    initial_plan=macro,
                    progress_callback=progress_callback,
                )
                out = run.to_dict()
                out["mode"] = "MACRO_EXECUTION"
            elif use_iterative:
                run = self.iterative_execution_agent.execute(
                    window=window,
                    app_name=app_name,
                    command=command,
                    ui_summary=ui_summary,
                    memory_context=memory_context,
                    planning_bias=planning_bias,
                    approval_callback=self._request_approval if REQUIRE_APPROVAL_FOR_RISKY else None,
                    progress_callback=progress_callback,
                )
                out = run.to_dict()
                out["mode"] = "ITERATIVE"

                if not out.get("success") and browser_macros.needs_live_ax_selection(app_name, command):
                    recovery_macro = browser_macros.get_live_ax_recovery_steps(app_name, command)
                    if recovery_macro:
                        logger.warning(
                            "Iterative live-AX execution failed for app=%s command=%r; attempting deterministic recovery macro",
                            app_name,
                            command,
                        )

                        recovery_run = self.execution_agent.execute(
                            window=window,
                            app_name=app_name,
                            command=command,
                            initial_plan=recovery_macro,
                            progress_callback=progress_callback,
                        )
                        recovery_out = recovery_run.to_dict()
                        recovery_out["mode"] = "ITERATIVE_RECOVERY_MACRO"
                        recovery_out["recovered_from_mode"] = "ITERATIVE"
                        recovery_out["iterative_error"] = out.get("error", "")
                        recovery_out["iterative_llm_calls"] = int(out.get("llm_calls", 0) or 0)
                        recovery_out["iterative_steps_before_recovery"] = len(out.get("steps", []))

                        if recovery_out.get("success"):
                            iterative_total_ms = int(out.get("total_ms", 0) or 0)
                            recovery_total_ms = int(recovery_out.get("total_ms", 0) or 0)
                            recovery_out["total_ms"] = iterative_total_ms + recovery_total_ms
                            recovery_out["steps"] = list(out.get("steps", [])) + list(recovery_out.get("steps", []))
                            logger.info(
                                "Deterministic recovery macro succeeded app=%s iterative_steps=%d recovery_steps=%d",
                                app_name,
                                len(out.get("steps", [])),
                                len(recovery_run.steps),
                            )
                            out = recovery_out
                        else:
                            out["recovery_attempted"] = True
                            out["recovery_error"] = recovery_out.get("error", "")
            else:
                logger.info("Execution macro planner fallback steps=%d", len(macro or []))
                run = self.execution_agent.execute(
                    window=window,
                    app_name=app_name,
                    command=command,
                    initial_plan=macro,
                    progress_callback=progress_callback,
                )
                out = run.to_dict()
                out["mode"] = "AGENTIC_EXECUTION"

            out["protected_app"] = app_name in PROTECTED_APPS
            logger.info(
                "Execution complete app=%s success=%s total_ms=%s steps=%d mode=%s",
                app_name,
                out.get("success"),
                out.get("total_ms"),
                len(out.get("steps", [])),
                out.get("mode"),
            )
            return out
        finally:
            keep_open_for_command = should_keep_app_open_after_execution(command)
            should_terminate = self.terminate_app_after_execute and not keep_open_for_command

            if should_terminate:
                controller.terminate_app()
                logger.info("Execution cleanup: app terminated app=%s", app_name)
            else:
                if keep_open_for_command and self.terminate_app_after_execute:
                    logger.info(
                        "Execution cleanup override: keeping app open for persistent task app=%s command=%r",
                        app_name,
                        command,
                    )
                else:
                    logger.info("Execution cleanup skipped: keeping app open app=%s", app_name)

    def _build_progress_events(self, execution: Dict[str, Any]) -> List[str]:
        events: List[str] = []
        for index, trace in enumerate(execution.get("steps", []), start=1):
            action = trace.get("action", {}) if isinstance(trace, dict) else {}
            action_type = str(action.get("action_type") or action.get("action") or "").strip().upper()

            target = ""
            if "target" in action:
                target = str(action.get("target", "")).strip()
            elif "keys" in action:
                target = str(action.get("keys", "")).strip()
            elif "text" in action:
                target = f"text_len={len(str(action.get('text', '')))}"

            method = str(trace.get("execution_method") or trace.get("method") or "").strip()
            signal = str(trace.get("verification_signal") or "").strip()
            status = "ok" if bool(trace.get("success")) else "failed"
            details = ", ".join(part for part in [method, signal] if part)

            label = f"{index}. {action_type}"
            if target:
                label += f" {target}"
            label += f" -> {status}"
            if details:
                label += f" ({details})"
            events.append(label)

        return events

    def _relation_facts(self, relations: List[Dict[str, Any]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for rel in relations or []:
            if not isinstance(rel, dict):
                continue
            subject = str(rel.get("subject", "user")).strip().lower()
            role = str(rel.get("relation", "")).strip().lower()
            obj = str(rel.get("object", "")).strip()
            if subject in {"user", "me", "my", "myself", "i"} and role and obj:
                out[f"{role}_name"] = obj
        return out

    def _resolve_app(
        self,
        command: str,
        target_app: Optional[str],
        app_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if target_app:
            return target_app

        context = app_context or self._get_automation_app_context()
        available = [str(app).strip() for app in context.get("available_apps", []) if str(app).strip()]
        automation_ready = [str(app).strip() for app in context.get("automation_ready_apps", []) if str(app).strip()]
        if not available:
            return None

        candidates = automation_ready if automation_ready else available
        command_l = (command or "").strip().lower()

        explicit_app = self._extract_explicit_app_from_text(command_l, available)
        if explicit_app:
            return explicit_app

        if browser_macros.is_media_followup_command(command_l):
            session_app = str(self._media_session.get("app_name", "")).strip()
            if session_app and session_app in available:
                return session_app

        llm_pick = self._llm_select_target_app(command, candidates, context)
        if llm_pick:
            return llm_pick

        if self._looks_like_media_play_request(command_l):
            media_target = self._pick_media_app(command_l, candidates)
            if media_target:
                return media_target

            media_target = self._pick_media_app(command_l, available)
            if media_target:
                return media_target

        if self._looks_like_browser_task(command_l):
            browser_target = self._pick_browser_app(candidates)
            if browser_target:
                return browser_target

            browser_target = self._pick_browser_app(available)
            if browser_target:
                return browser_target

        if self._looks_like_calculator_task(command_l):
            calculator_target = self._pick_available_app(candidates, "Calculator")
            if calculator_target:
                return calculator_target

        if self._looks_like_excel_task(command_l):
            excel_target = self._pick_available_app(candidates, "Excel")
            if excel_target:
                return excel_target

        if self._looks_like_text_entry_task(command_l):
            notepad_target = self._pick_available_app(candidates, "Notepad")
            if notepad_target:
                return notepad_target

        if "browser" in command_l:
            demo_browser_target = self._pick_available_app(candidates, self.demo_browser)
            if demo_browser_target:
                return demo_browser_target

        if self._looks_like_app_local_command(command_l):
            active_target = self._pick_available_app(candidates, self._active_app, allow_protected=True)
            if active_target:
                return active_target

        for preferred in ("Notepad", "Calculator", "Chrome", "Brave"):
            if preferred in candidates and preferred not in PROTECTED_APPS:
                return preferred

        for app_name in candidates:
            if app_name not in PROTECTED_APPS:
                return app_name

        for app_name in available:
            if app_name not in PROTECTED_APPS:
                return app_name

        return available[0] if available else None

    def _llm_select_target_app(
        self,
        command: str,
        candidate_apps: List[str],
        app_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        apps = [str(app).strip() for app in candidate_apps if str(app).strip()]
        if not apps:
            return None
        if len(apps) == 1:
            return apps[0]

        context = app_context or {}
        ready_set = {str(app).strip() for app in context.get("automation_ready_apps", []) if str(app).strip()}
        task_hints = context.get("tasks_hint", {}) if isinstance(context.get("tasks_hint", {}), dict) else {}

        app_rows: List[Dict[str, Any]] = []
        for app_name in apps:
            cfg = harness_config.get_app_config(app_name) or {}
            exe_name = os.path.basename(str(cfg.get("exe", "") or "")).strip()
            app_rows.append(
                {
                    "name": app_name,
                    "ready": app_name in ready_set,
                    "exe": exe_name,
                    "task_hints": list(task_hints.get(app_name, []) or [])[:6],
                }
            )

        prompt = (
            "Select the best desktop app for this automation command.\n"
            f"Command: {command}\n"
            f"Available apps JSON: {json.dumps(app_rows, ensure_ascii=False)}\n"
            "Rules:\n"
            "1. If command explicitly asks for a specific available app, pick that app.\n"
            "2. For browser/youtube/web actions, pick a browser app.\n"
            "3. For text writing/typing/document drafting, prefer Notepad if available.\n"
            "4. For music playback, use Spotify when explicitly asked; otherwise browser/youtube is acceptable.\n"
            "Return strict JSON only: {\"app_name\": \"<one app name from list or empty>\", \"reason\": \"...\"}."
        )

        response = llm_service.get_conversational_response(prompt, context="")
        payload = self._extract_json_object(response)
        if not payload:
            return None

        selected_raw = str(payload.get("app_name", "")).strip()
        if not selected_raw:
            return None

        selected = self._pick_available_app(apps, selected_raw, allow_protected=True)
        if selected:
            logger.info("LLM app routing selected app=%s reason=%s", selected, str(payload.get("reason", "")))
            return selected

        selected_l = selected_raw.lower()
        for app_name in apps:
            app_l = app_name.lower()
            if app_l in selected_l or selected_l in app_l:
                logger.info("LLM app routing selected by fuzzy match app=%s raw=%s", app_name, selected_raw)
                return app_name

        return None

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"(\{.*\})", raw, flags=re.DOTALL)
        if not match:
            return {}

        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}

        return {}

    def _is_app_automation_ready(self, app_name: str, task_match_threshold: float = 0.65) -> bool:
        cache_path = storage.get_cache_path(app_name)
        if not cache_path or not os.path.exists(cache_path):
            return False

        try:
            with open(cache_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return False

        elements = data.get("elements", {}) if isinstance(data, dict) else {}
        if not isinstance(elements, dict) or not elements:
            return False

        has_exposure_path = False
        for node in elements.values():
            if not isinstance(node, dict):
                continue
            exposure_path = node.get("exposure_path", [])
            if isinstance(exposure_path, list) and exposure_path:
                has_exposure_path = True
                for step in exposure_path:
                    if not isinstance(step, dict):
                        continue
                    step_fp = str(step.get("fingerprint", "")).strip()
                    if step_fp and step_fp not in elements:
                        return False

        if not has_exposure_path:
            return False

        tasks = harness_config.get_tasks_for_app(app_name)
        if tasks:
            for task in tasks:
                if not matcher.find_cached_element(app_name, task, min_confidence=task_match_threshold):
                    return False

        return True

    def _get_automation_app_context(self) -> Dict[str, Any]:
        available_apps = [str(app).strip() for app in harness_config.get_available_apps() if str(app).strip()]
        automation_ready_apps: List[str] = []
        task_hints: Dict[str, List[str]] = {}

        for app_name in available_apps:
            task_hints[app_name] = list(harness_config.get_tasks_for_app(app_name) or [])[:8]
            if self._is_app_automation_ready(app_name):
                automation_ready_apps.append(app_name)

        return {
            "available_apps": available_apps,
            "automation_ready_apps": automation_ready_apps,
            "tasks_hint": task_hints,
        }

    def _extract_explicit_app_from_text(self, command_l: str, available_apps: List[str]) -> Optional[str]:
        for app_name in available_apps:
            app_l = str(app_name).strip().lower()
            if not app_l:
                continue
            if re.search(rf"\b{re.escape(app_l)}\b", command_l):
                return app_name

            exe_name = os.path.splitext(os.path.basename(str(harness_config.get_app_config(app_name).get("exe", ""))))[0].lower()
            if exe_name and re.search(rf"\b{re.escape(exe_name)}\b", command_l):
                return app_name

        return None

    def _pick_available_app(self, available_apps: List[str], *candidates: str, allow_protected: bool = False) -> Optional[str]:
        available_map = {str(app).strip().lower(): str(app).strip() for app in available_apps if str(app).strip()}
        for candidate in candidates:
            key = str(candidate or "").strip().lower()
            if not key or key not in available_map:
                continue
            resolved = available_map[key]
            if not allow_protected and resolved in PROTECTED_APPS:
                continue
            return resolved
        return None

    def _pick_browser_app(self, available_apps: List[str]) -> Optional[str]:
        browser_candidates = [self.demo_browser, "Brave", "Chrome", "Edge", "Firefox"]
        return self._pick_available_app(available_apps, *browser_candidates)

    def _looks_like_media_play_request(self, command: str) -> bool:
        text = str(command or "").strip().lower()
        if not text:
            return False

        if browser_macros.is_media_play_command(text):
            return True

        if not re.search(r"\b(play|watch|listen|stream)\b", text):
            return False

        if re.search(r"\b(song|music|track|video|playlist|podcast|album|radio|youtube|spotify)\b", text):
            return True

        # STT often transcribes "YouTube" as "you" in phrases like "play ... on you".
        if re.search(r"\bon\s+you\b", text):
            return True

        if text.startswith("play ") and len(text.split()) >= 3:
            blocked_markers = (
                "file menu",
                "edit menu",
                "view menu",
                "help menu",
                "button",
                "checkbox",
                "dropdown",
            )
            return not any(marker in text for marker in blocked_markers)

        return False

    def _looks_like_browser_task(self, command: str) -> bool:
        text = str(command or "").strip().lower()
        if not text:
            return False

        if "http://" in text or "https://" in text or "www." in text:
            return True

        return bool(
            re.search(
                r"\b(browser|web|website|url|link|search|google|youtube|chrome|brave|edge|firefox|incognito|history|downloads)\b",
                text,
            )
        )

    def _looks_like_calculator_task(self, command: str) -> bool:
        text = str(command or "").strip().lower()
        if not text:
            return False

        if re.search(r"\b(calculator|calculate|sum|add|subtract|minus|plus|multiply|divide|percent|square root)\b", text):
            return True

        return bool(re.search(r"\d+\s*(?:\+|-|\*|/|x)\s*\d+", text))

    def _looks_like_excel_task(self, command: str) -> bool:
        text = str(command or "").strip().lower()
        if not text:
            return False

        return bool(
            re.search(
                r"\b(excel|spreadsheet|worksheet|workbook|cell|row|column|formula|pivot|table)\b",
                text,
            )
        )

    def _looks_like_text_entry_task(self, command: str) -> bool:
        text = str(command or "").strip().lower()
        if not text:
            return False

        if looks_like_text_entry_intent(text):
            return True

        return bool(re.search(r"\b(write|type|draft|compose|note|paragraph|essay|letter|document)\b", text))

    def _looks_like_app_local_command(self, command: str) -> bool:
        text = str(command or "").strip().lower()
        if not text:
            return False

        if self._looks_like_browser_task(text) or self._looks_like_media_play_request(text):
            return False

        local_markers = (
            "file menu",
            "edit menu",
            "view menu",
            "help menu",
            "open file",
            "save",
            "save as",
            "undo",
            "redo",
            "copy",
            "paste",
            "find",
            "replace",
            "new tab",
        )
        if any(marker in text for marker in local_markers):
            return True

        return bool(re.match(r"^(click|select|press|open)\b", text))

    def _pick_media_app(self, command_l: str, available_apps: List[str]) -> Optional[str]:
        available = [str(app).strip() for app in available_apps if str(app).strip()]
        if not available:
            return None

        if "spotify" in command_l:
            spotify_target = self._pick_available_app(available, "Spotify")
            if spotify_target:
                return spotify_target

        session_app = str(self._media_session.get("app_name", "")).strip()
        if session_app and session_app in available and session_app not in PROTECTED_APPS:
            return session_app

        browser_target = self._pick_browser_app(available)
        if browser_target:
            return browser_target

        fallback_media_target = self._pick_available_app(available, "Spotify")
        if fallback_media_target:
            return fallback_media_target

        return None

    def _is_high_risk_command(self, command: str, plan: Optional[List[Dict[str, Any]]] = None) -> bool:
        if not REQUIRE_APPROVAL_FOR_RISKY:
            return False

        text = (command or "").lower()
        if any(keyword in text for keyword in HIGH_RISK_KEYWORDS):
            return True

        for step in plan or []:
            target = str(step.get("target", "")).lower()
            action_text = str(step.get("text", "")).lower()
            if any(keyword in target or keyword in action_text for keyword in HIGH_RISK_KEYWORDS):
                return True

        return False

    def _request_approval(self, context: Dict[str, Any]) -> bool:
        if not REQUIRE_APPROVAL_FOR_RISKY:
            logger.info("Approval bypassed: policy disabled")
            return True
        if self.dry_run:
            logger.info("Approval bypassed: dry-run enabled")
            return True

        if self.approval_callback:
            try:
                approved = bool(self.approval_callback(context))
                logger.info("Approval callback decision=%s", approved)
                return approved
            except Exception:
                logger.warning("Approval callback raised exception; denying action")
                return False

        if sys.stdin.isatty():
            command = str(context.get("command", ""))
            app_name = str(context.get("app_name", ""))
            answer = input(f"Approve risky action for {app_name}: '{command}'? (yes/no): ").strip().lower()
            approved = answer in {"y", "yes"}
            logger.info("TTY approval decision=%s", approved)
            return approved

        logger.warning("Approval denied: no callback and non-interactive stdin")
        return False

    def _recent_turns_snapshot(self, limit: int = 6) -> List[Dict[str, Any]]:
        snapshot: List[Dict[str, Any]] = []
        for item in self._history[-max(1, int(limit)) :]:
            snapshot.append(
                {
                    "command": item.command,
                    "intent": item.intent,
                    "success": item.execution_success,
                    "tier_used": item.tier_used,
                    "app_agent": item.app_agent,
                }
            )
        return snapshot

    def _build_llm_context(
        self,
        recalled: List[str],
        current_command: str,
        app_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        memory_hits = [str(line).strip() for line in recalled if str(line).strip()]
        memory_hits = memory_hits[-8:]

        context = app_context or self._get_automation_app_context()
        available_apps = [str(app).strip() for app in context.get("available_apps", []) if str(app).strip()]
        automation_ready_apps = [
            str(app).strip() for app in context.get("automation_ready_apps", []) if str(app).strip()
        ]
        task_hints = context.get("tasks_hint", {}) if isinstance(context.get("tasks_hint", {}), dict) else {}

        app_hints: Dict[str, List[str]] = {}
        for app_name in available_apps[:20]:
            app_hints[app_name] = list(task_hints.get(app_name, []) or [])[:5]

        session_payload = {
            "active_app": self._active_app,
            "current_command": current_command,
            "available_apps": available_apps,
            "automation_ready_apps": automation_ready_apps,
            "app_task_hints": app_hints,
            "media_session": dict(self._media_session),
            "recent_turns": self._recent_turns_snapshot(limit=6),
        }
        session_json = json.dumps(session_payload, ensure_ascii=False)
        if len(session_json) > 3500:
            session_json = session_json[:3500] + "..."

        chunks: List[str] = []
        if memory_hits:
            chunks.append("memory_hits: " + " | ".join(memory_hits))
        chunks.append("session_context_json: " + session_json)
        return "\n".join(chunks)

    def _update_media_session(self, command: str, app_name: str, execution_success: bool, tier_used: str) -> None:
        if not execution_success:
            return

        command_text = str(command or "").strip()
        if not command_text:
            return

        if app_name in browser_macros.BROWSER_APPS and browser_macros.is_media_play_command(command_text):
            self._media_session = {
                "active": True,
                "app_name": app_name,
                "platform": "youtube",
                "query": browser_macros.extract_media_query(command_text),
                "playback_state": "playing",
                "last_action": "play",
                "last_command": command_text,
                "last_tier": tier_used,
            }
            logger.info("Media session activated app=%s query=%r", app_name, self._media_session.get("query", ""))
            return

        if bool(self._media_session.get("active")) and browser_macros.is_media_followup_command(command_text):
            followup_action = browser_macros.get_media_followup_action(command_text) or "followup"
            playback_state = str(self._media_session.get("playback_state", "")).strip().lower()
            if followup_action in {"pause_toggle", "resume_toggle"}:
                playback_state = "paused" if playback_state == "playing" else "playing"
            elif followup_action == "next":
                playback_state = "playing"

            self._media_session.update(
                {
                    "active": True,
                    "app_name": app_name or str(self._media_session.get("app_name", "")),
                    "last_action": followup_action,
                    "last_command": command_text,
                    "last_tier": tier_used,
                    "playback_state": playback_state,
                }
            )
            logger.info(
                "Media session updated app=%s action=%s playback_state=%s",
                self._media_session.get("app_name", ""),
                followup_action,
                playback_state,
            )

    def _execute_screen_read(self, command: str, recalled: List[str]) -> Dict[str, Any]:
        app_name = self._active_app
        cfg = harness_config.get_app_config(app_name) or {}
        title_re = cfg.get("title_re", "")
        logger.info("Screen-read start app=%s title_re=%s", app_name, bool(title_re))

        texts: List[str] = []
        tier = "UIA_TEXT_CAPTURE"
        error = ""

        try:
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
            windows = desktop.windows(title_re=title_re) if title_re else []
            if not windows:
                windows = desktop.windows()

            window = windows[0] if windows else None
            if window is not None:
                seen = set()
                for elem in window.descendants():
                    try:
                        value = str(elem.window_text() or "").strip()
                    except Exception:
                        continue
                    if not value or len(value) > 180:
                        continue
                    key = value.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    texts.append(value)
                    if len(texts) >= 80:
                        break
        except Exception as exc:
            error = str(exc)

        if not texts:
            try:
                from PIL import ImageGrab
                import pytesseract

                tier = "OCR_FALLBACK"
                image = ImageGrab.grab()
                ocr_text = str(pytesseract.image_to_string(image) or "").strip()
                if ocr_text:
                    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
                    texts.extend(lines[:80])
            except Exception as exc:
                if not error:
                    error = str(exc)

        if not texts:
            return {
                "success": False,
                "tier": "SCREEN_READ_FALLBACK",
                "response": "I could not read visible content from the current screen.",
                "error": error,
            }

        preview = "\n".join(f"- {line}" for line in texts[:20])
        summarize_prompt = (
            "Summarize these visible on-screen items into a short user-friendly status update.\n"
            f"{preview}"
        )
        summary = llm_service.get_conversational_response(
            summarize_prompt,
            context=" | ".join(recalled),
        )
        logger.info("Screen-read success tier=%s captured_lines=%d", tier, len(texts))
        return {
            "success": True,
            "tier": tier,
            "response": summary or ("Visible content:\n" + preview),
            "error": "",
        }
