#!/usr/bin/env python3
"""SARA demo entrypoint.

Modes:
- python demo.py            -> chat UI (dry-run default)
- python demo.py --widget   -> compact always-on-top widget
- python demo.py --cli      -> terminal REPL
- python demo.py --test     -> smoke feature test
- python demo.py --live     -> enable real execution (no dry-run)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time


def _configure_runtime_environment() -> None:
    # Constrain BLAS/OpenMP thread fanout to avoid low-memory startup failures.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("BLIS_NUM_THREADS", "1")


def _prime_windows_com_apartment() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        COINIT_APARTMENTTHREADED = 0x2
        ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except Exception:
        pass


_configure_runtime_environment()
_prime_windows_com_apartment()

from sara.api import LocalCommandApiServer
from sara.core.host_agent import HostAgent
from sara.voice.service import VoiceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
logger = logging.getLogger("sara.demo")


def run_cli(agent: HostAgent) -> int:
    logger.info("Starting CLI mode dry_run=%s", agent.dry_run)
    print("SARA CLI ready. Commands: status, memory, history, exit")
    while True:
        try:
            command = input(">>> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not command:
            continue
        if command.lower() in {"exit", "quit"}:
            break
        if command.lower() == "status":
            print(json.dumps(agent.get_system_status(), indent=2, ensure_ascii=False))
            continue
        if command.lower() == "memory":
            print(json.dumps(agent.get_memory_summary(), indent=2, ensure_ascii=False))
            continue
        if command.lower() == "history":
            print(json.dumps(agent.get_history()[-5:], indent=2, ensure_ascii=False))
            continue

        result = agent.process_command(command)
        print(f"[{result.intent}] {result.response_text}")
        if result.error:
            print(f"error: {result.error}")
    return 0


def run_widget(agent: HostAgent) -> int:
    from sara.ui.widget import launch_widget

    voice = VoiceService()
    logger.info("Starting widget UI dry_run=%s", agent.dry_run)
    return launch_widget(agent, voice_service=voice)


def run_chat(agent: HostAgent) -> int:
    from sara.ui.chat_widget import launch_chat

    voice = VoiceService()
    logger.info("Starting chat UI dry_run=%s", agent.dry_run)
    return launch_chat(agent, voice_service=voice)


def run_api_only(server: LocalCommandApiServer) -> int:
    logger.info("Starting API-only mode")
    print("SARA local API server running.")
    print("GET  /health")
    print("GET  /status")
    print("GET  /history")
    print("POST /command  {\"command\": \"...\"}")
    print("GET  /jobs/<job_id>")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        return 0


def run_test() -> int:
    logger.info("Running smoke tests")
    # Smoke tests do not need semantic vector DB; keep startup lightweight and stable.
    os.environ.setdefault("SARA_ENABLE_CHROMA", "0")
    agent = HostAgent(dry_run=True)
    tests = [
        ("remember", "my name is Hussain", "remember"),
        ("automation", "open file menu in notepad", "automation"),
        ("conversation", "what is automation tree", "conversation"),
    ]

    passed = 0
    for label, command, expected_intent in tests:
        result = agent.process_command(command)
        ok = result.intent == expected_intent
        if ok:
            passed += 1
        print(
            f"{label}: {'PASS' if ok else 'FAIL'} | intent={result.intent} | route={result.privacy_route}"
        )

    print(f"tests: {passed}/{len(tests)}")
    return 0 if passed == len(tests) else 1


def run_preflight() -> int:
    subprocess.run([sys.executable, "scripts/sync_docs_context.py"], check=False)
    proc = subprocess.run([sys.executable, "scripts/demo_preflight.py"], check=False)
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="SARA demo entrypoint")
    parser.add_argument("--cli", action="store_true", help="Run terminal REPL")
    parser.add_argument("--widget", action="store_true", help="Run always-on-top widget")
    parser.add_argument("--live", action="store_true", help="Enable real execution (default is dry-run)")
    parser.add_argument("--test", action="store_true", help="Run smoke feature tests")
    parser.add_argument("--preflight", action="store_true", help="Run preflight environment checks")
    parser.add_argument("--api", action="store_true", help="Start local HTTP API server alongside UI/CLI")
    parser.add_argument("--api-only", action="store_true", help="Run only local HTTP API server")
    parser.add_argument(
        "--close-app-after-execute",
        action="store_true",
        help="Terminate app process after each live automation execution",
    )
    args = parser.parse_args()

    logger.info(
        "Launching demo mode cli=%s widget=%s live=%s api=%s api_only=%s",
        args.cli,
        args.widget,
        args.live,
        args.api,
        args.api_only,
    )

    if args.test:
        return run_test()
    if args.preflight:
        return run_preflight()

    agent = HostAgent(
        dry_run=not args.live,
        terminate_app_after_execute=bool(args.close_app_after_execute),
    )
    api_server = None

    if args.api or args.api_only:
        api_server = LocalCommandApiServer(agent)
        api_server.start()

    if args.api_only:
        try:
            return run_api_only(api_server)
        finally:
            api_server.stop()

    if args.cli:
        try:
            return run_cli(agent)
        finally:
            if api_server is not None:
                api_server.stop()

    try:
        if args.widget:
            return run_widget(agent)
        return run_chat(agent)
    except ImportError as exc:
        logger.warning("UI unavailable (%s). Falling back to CLI mode.", exc)
        return run_cli(agent)
    finally:
        if api_server is not None:
            api_server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
