"""Runtime-faithful full-loop validation with step-by-step telemetry.

This script validates the real runtime loop:
command -> LLM planning -> step execution -> verification -> final result.

By default it enforces strict Bedrock routing so fallback providers are disabled.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _configure_strict_bedrock() -> None:
    os.environ["SARA_LLM_SIMPLE_PROVIDER"] = "bedrock"
    os.environ["SARA_LLM_COMPLEX_PROVIDER"] = "bedrock"
    os.environ["LLM_STRICT_PREFERRED_PROVIDER"] = "1"


def _probe_bedrock_provider() -> Dict[str, Any]:
    from src.llm.llm_client import get_client

    response = get_client().call(
        prompt="Return strict JSON: {\"ok\": true}",
        system="Output JSON only.",
        temperature=0.0,
        max_tokens=40,
        prefer_provider="bedrock",
        strict_preferred=True,
        task_complexity="simple",
    )

    return {
        "provider": response.provider,
        "model": response.model,
        "error": response.error or "",
        "latency_ms": response.latency_ms,
    }


def run_validation(app_name: str, command: str, terminate_after: bool) -> int:
    from sara.core.host_agent import HostAgent

    telemetry: List[Dict[str, Any]] = []

    agent = HostAgent(dry_run=False, terminate_app_after_execute=terminate_after)
    agent.set_active_app(app_name)

    start = time.time()

    def _on_progress(event: Dict[str, Any]) -> None:
        entry = {
            "step_index": int(event.get("step_index", 0) or 0),
            "attempt": int(event.get("attempt", 0) or 0),
            "action": event.get("action", {}),
            "success": bool(event.get("success")),
            "execution_method": str(event.get("execution_method", "")),
            "verification_signal": str(event.get("verification_signal", "")),
            "execution_error": str(event.get("execution_error", "")),
        }
        telemetry.append(entry)
        print("STEP_EVENT", json.dumps(entry, ensure_ascii=False))

    result = agent.process_command(command, progress_callback=_on_progress)
    total_ms = int((time.time() - start) * 1000)

    final = {
        "success": bool(result.execution_success),
        "intent": str(result.intent),
        "tier": str(result.tier_used),
        "error": str(result.error or ""),
        "response_text": str(result.response_text),
        "progress_events": list(result.progress_events),
        "telemetry_steps": len(telemetry),
        "total_ms": total_ms,
    }

    print("FINAL_RESULT", json.dumps(final, ensure_ascii=False))
    return 0 if result.execution_success else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Runtime full-loop validation with strict Bedrock")
    parser.add_argument("--app", default="Notepad", help="Target app name")
    parser.add_argument("--command", required=True, help="User command to execute")
    parser.add_argument(
        "--allow-fallback-providers",
        action="store_true",
        help="Do not enforce strict Bedrock-only routing",
    )
    parser.add_argument(
        "--keep-app-open",
        action="store_true",
        help="Do not terminate the target app after execution",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", force=True)

    if not args.allow_fallback_providers:
        _configure_strict_bedrock()

    provider_probe = _probe_bedrock_provider()
    print("LLM_PROVIDER_PROBE", json.dumps(provider_probe, ensure_ascii=False))

    if provider_probe.get("error"):
        # Under strict mode, this is a hard fail because runtime calls would fail too.
        return 3

    return run_validation(
        app_name=args.app,
        command=args.command,
        terminate_after=not args.keep_app_open,
    )


if __name__ == "__main__":
    raise SystemExit(main())
