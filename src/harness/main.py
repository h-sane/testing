# harness/main.py
"""
Main orchestrator for the hybrid GUI automation harness.
Runs three-tier execution: Cache -> AX -> Vision
With cache execution now fully wired.
"""

import argparse
import time
import sys
import os
from dotenv import load_dotenv

# MANDATORY: Load environment variables
load_dotenv()

print("[TRACE] VLM INIT CHECK")
print("[STARTUP CHECK] GEMINI_API_KEY loaded:", bool(os.getenv("GEMINI_API_KEY")))
print("[STARTUP CHECK] HF_TOKEN loaded:", bool(os.getenv("HF_TOKEN")))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.harness import config
from src.harness.logger import HarnessLogger, ExecutionLog
from src.harness.app_controller import AppController, create_controller
from src.harness import ax_executor
from src.harness import vision_executor
from src.harness import verification
from src.harness.locator import locate_element_by_fingerprint
from src.automation import matcher, storage, prober


# =============================================================================
# ELEMENT EXECUTION
# =============================================================================

def execute_located_element(elem) -> bool:
    """Execute action on a located element."""
    print(f"[orchestrator] Executing cached element...")
    
    # Try InvokePattern
    try:
        if hasattr(elem, 'iface_invoke') and elem.iface_invoke:
            elem.invoke()
            print("[orchestrator] InvokePattern succeeded (CACHE)")
            return True
    except Exception as e:
        print(f"[orchestrator] InvokePattern failed: {e}")
    
    # Try ExpandCollapsePattern
    try:
        if hasattr(elem, 'iface_expand_collapse') and elem.iface_expand_collapse:
            elem.expand()
            print("[orchestrator] ExpandCollapsePattern succeeded (CACHE)")
            return True
    except Exception as e:
        pass
    
    # Fallback: click_input
    try:
        elem.click_input()
        print("[orchestrator] click_input succeeded (CACHE)")
        return True
    except Exception as e:
        print(f"[orchestrator] click_input failed: {e}")
    
    return False


# =============================================================================
# ORCHESTRATOR
# =============================================================================

def execute_task(
    controller: AppController,
    task: str,
    logger: HarnessLogger,
    trace_logger, # New argument
    use_cache: bool = True,
    use_vision: bool = True,
    dry_run: bool = False
) -> bool:
    """
    Execute a single task using strict three-tier strategy.
    PROTOCOL: CACHE -> PLANNER -> AX -> VISION
    """
    app_name = controller.app_name
    window = controller.get_window()
    
    # 0. Task Start
    trace_logger.log_task_start(app_name, task)
    
    if not window:
        print(f"[orchestrator] ERROR: No window for {app_name}")
        trace_logger.log_task_end("FAILED_NO_WINDOW", False, 0)
        return False
    
    start_time = time.time()
    
    log = ExecutionLog(
        app_name=app_name,
        task=task,
        execution_method="FAILED",
        success=False
    )
    
    pre_state = verification.capture_state(window)
    
    # =========================================================================
    # TIER 1: Cache Lookup + Planner
    # =========================================================================
    planner_success = False
    
    if use_cache:
        print(f"\n[orchestrator] TIER 1: Cache lookup for '{task}'")
        cached = matcher.find_cached_element(app_name, task, min_confidence=0.6)
        
        if cached:
            trace_logger.log_cache_check(True, cached.get("fingerprint"), cached.get("score"))
            
            # Planner Execution
            # Reliability Guard: If exposure path is empty (root item?) but confidence is shaky,
            # skip planner to force fresh AX scan. This prevents "Stale Cache Loops".
            exposure_path = cached.get("exposure_path", [])
            score = cached.get("score", 0)
            
            if len(exposure_path) == 0 and score < 0.95:
                 print(f"[orchestrator] Skipping Planner (Empty path & score {score:.2f} < 0.95). Forcing AX.")
                 trace_logger.log_cache_check(True, cached.get("fingerprint"), score) # Log hit
                 # Fall through to AX
            elif not dry_run and score >= 0.8:
                try:
                    from src.automation import execution_planner
                    print(f"[orchestrator] Triggering Execution Planner...")
                    
                    # Log start
                    trace_logger.log_planner_execution(True, steps_attempted=1, exposure_path_length=len(exposure_path)) # Initial
                    
                    success = execution_planner.execute_with_self_healing(window, app_name, cached.get("fingerprint"))
                    
                    if success:
                        planner_success = True
                        log.execution_method = "PLANNER"
                        log.success = True
                        log.cache_hit = True
                        
                        trace_logger.log_planner_execution(True, success=True)
                        
                        # Verify
                        ver_result = verification.quick_verify(window, pre_state)
                        log.verification_success = ver_result.success
                        log.verification_method = ver_result.primary_signal
                        
                        trace_logger.log_verification(ver_result.signals, ver_result.success, ver_result.confidence)
                        
                        storage.record_success(app_name, cached.get("fingerprint"), task)
                        
                        log.execution_time_ms = int((time.time() - start_time) * 1000)
                        logger.log_execution(log)
                        trace_logger.log_task_end("PLANNER", True, log.execution_time_ms)
                        return True
                    else:
                        print(f"[orchestrator] Planner execution failed. Falling through to AX.")
                        trace_logger.log_planner_execution(True, success=False)
                except Exception as e:
                     print(f"[orchestrator] Planner error: {e}")
                     trace_logger.log_planner_execution(True, success=False)
            else:
                 trace_logger.log_cache_check(True, cached.get("fingerprint"), cached.get("score")) # Log hit but skip
        else:
            trace_logger.log_cache_check(False)
            
    # =========================================================================
    # TIER 2: AX Execution
    # =========================================================================
    print(f"\n[orchestrator] TIER 2: AX execution for '{task}'")
    print(f"[TRACE] AX EXECUTION START")
    print(f"[TRACE] AX EXECUTION START")
    ax_success = False
    
    if not dry_run:
        # Trace log start
        trace_logger.log_ax_execution(True)
        
        ax_result = ax_executor.find_and_execute(window, task, app_name, min_confidence=0.6)
        
        best_score = ax_result.get("score", 0.0)
        trace_logger.log_ax_execution(True, elements_scanned=ax_result.get("scanned_count", 0), best_match_score=best_score, execution_attempted=ax_result.get("executed", False), execution_success=ax_result.get("executed", False))

        if ax_result.get("executed", False):
            ax_success = True
            log.execution_method = "AX"
            log.success = True
            log.ax_element_found = True
            
            ver_result = verification.quick_verify(window, pre_state)
            log.verification_success = ver_result.success
            log.verification_method = ver_result.primary_signal
            
            trace_logger.log_verification(ver_result.signals, ver_result.success, ver_result.confidence)
            
            log.execution_time_ms = int((time.time() - start_time) * 1000)
            logger.log_execution(log)
            trace_logger.log_task_end("AX", True, log.execution_time_ms)
            return True
    
    # =========================================================================
    # TIER 3: Vision Fallback (VLM)
    # =========================================================================
    if not planner_success and use_vision:
        print(f"[orchestrator] TIER 3: Vision Fallback for '{task}'")
        print(f"[TRACE] VISION EXECUTION START")
        
        try:
            from src.harness import vision_executor
            
            # Use strict timeout
            # Pass logger and run_id for granular event logging
            vision_result = vision_executor.detect_and_click(
                window, 
                task, 
                app_name, 
                run_id=logger.run_id if hasattr(logger, "run_id") else "unknown",
                logger=logger,
                timeout=20.0
            )
            
            trace_logger.log_vision_execution(
                triggered=True,
                success=vision_result.clicked,
                api_called=vision_result.api_called,
                latency_ms=vision_result.latency_ms,
                screenshot_path=vision_result.screenshot_path,
                coordinates=vision_result.coordinates,
                trigger_reason="TIER2_FAILED"
            )
            
            log.vision_used = True
            log.coordinates = vision_result.coordinates
            
            if vision_result.clicked:
                print(f"[orchestrator] Vision execution SUCCESS")
                # Wait for UI reaction
                time.sleep(1.0)
                
                # Verify
                ver_result = verification.quick_verify(window, pre_state)
                log.verification_success = ver_result.success
                log.verification_method = ver_result.primary_signal
                
                trace_logger.log_verification(ver_result.signals, ver_result.success, ver_result.confidence)
                
                log.execution_method = "VISION"
                log.success = True
                log.execution_time_ms = int((time.time() - start_time) * 1000)
                logger.log_execution(log)
                trace_logger.log_task_end("VISION", True, log.execution_time_ms)
                return True
            else:
                 print(f"[orchestrator] Vision execution FAILED: {vision_result.error}")
                 if "No matches found" in vision_result.error:
                     print(f"[orchestrator] VLM REFUSAL: Model could not find '{task}' in screenshot.")
                     
                 trace_logger.log_task_end("FAILED", False, int((time.time() - start_time) * 1000))
        except Exception as e:
            print(f"[orchestrator] Vision error: {e}")
            trace_logger.log_vision_execution(True, False, False, 0, "", None,  trigger_reason=f"EXCEPTION: {e}")
    
    # =========================================================================
    # FAILED
    # =========================================================================
    log.execution_method = "FAILED"
    log.execution_time_ms = int((time.time() - start_time) * 1000)
    logger.log_execution(log)
    trace_logger.log_task_end("FAILED", False, log.execution_time_ms)
    print(f"[TRACE] EXECUTION COMPLETE")
    return False


def run_app(
    app_name: str,
    app_config: dict,
    logger: HarnessLogger,
    trace_logger, # New arg
    tasks: list = None,
    use_cache: bool = True,
    use_vision: bool = True,
    dry_run: bool = False,
    max_tasks: int = None
):
    """Run all tasks for a single application."""
    print("\n" + "=" * 60)
    print(f"APP: {app_name}")
    print("=" * 60)
    
    if tasks is None:
        tasks = config.get_tasks_for_app(app_name)
    
    if max_tasks:
        tasks = tasks[:max_tasks]
    
    if not tasks:
        print(f"[orchestrator] No tasks defined for {app_name}")
        return
    
    print(f"[orchestrator] {len(tasks)} tasks to execute")
    
    controller = create_controller(app_name, app_config)
    
    if not controller.start_or_connect():
        print(f"[orchestrator] ERROR: Could not start/connect to {app_name}")
        return
    
    controller.focus()
    time.sleep(0.5)
    
    for i, task in enumerate(tasks):
        print(f"\n--- Task {i+1}/{len(tasks)}: {task} ---")
        
        # Universal home state recovery between tasks
        if i > 0:
            try:
                from src.harness.ui_state_manager import ensure_home_state
                window = controller.get_window()
                if window:
                    recovery = ensure_home_state(window, app_name, trace_logger)
                    if recovery.get("back_clicks", 0) > 0:
                        print(f"[orchestrator] Home recovery: {recovery['back_clicks']} Back click(s)")
                    # Re-focus after recovery
                    controller.focus()
                    time.sleep(0.3)
            except Exception as e:
                print(f"[orchestrator] Home recovery error (non-fatal): {e}")
        
        try:
            execute_task(
                controller,
                task,
                logger,
                trace_logger, 
                use_cache=use_cache,
                use_vision=use_vision,
                dry_run=dry_run
            )
        except Exception as e:
            print(f"[orchestrator] Task error: {e}")
            import traceback
            traceback.print_exc()
        
        time.sleep(0.5)
    
    # Strict kill protocol
    controller.terminate_app()


def run_all(
    apps: list = None,
    output_dir: str = "runs",
    use_cache: bool = True,
    use_vision: bool = True,
    dry_run: bool = False,
    max_tasks: int = None
):
    """Run harness on all specified applications."""
    available = config.get_available_apps()
    
    if apps:
        apps = [a for a in apps if a in available]
    else:
        apps = available
    
    if not apps:
        print("[orchestrator] No apps available to test")
        return
    
    print(f"\n{'=' * 60}")
    print("HYBRID GUI AUTOMATION HARNESS")
    print(f"{'=' * 60}")
    print(f"[TRACE] MAIN START") # MANDATORY TRACE MARKER
    print(f"[TRACE] MAIN START") # MANDATORY TRACE MARKER
    print(f"Apps to test: {apps}")
    print(f"Output: {output_dir}")
    print(f"Cache: {'enabled' if use_cache else 'disabled'}")
    print(f"Vision: {'enabled' if use_vision else 'disabled'}")
    print(f"Dry run: {dry_run}")
    print(f"{'=' * 60}\n")
    
    # Initialize matcher debug log
    matcher.init_debug_log(output_dir)
    
    logger = HarnessLogger(output_dir)
    
    # Initialize Full Trace Logger
    from src.harness.full_execution_trace_logger import FullExecutionTraceLogger
    from src.harness.logger import RedirectStdout
    
    trace_logger = FullExecutionTraceLogger(logger.run_id, output_dir=logger.run_dir)
    # Redirect stdout/stderr to console.log
    log_file = os.path.join(logger.run_dir, "console.log")
    
    print(f"[logger] Redirecting stdout/stderr to {log_file}")
    
    with RedirectStdout(log_file):
        for app_name in apps:
            app_config = config.get_app_config(app_name)
        
            try:
                run_app(
                    app_name,
                    app_config,
                    logger,
                    trace_logger,
                    use_cache=use_cache,
                    use_vision=use_vision,
                    dry_run=dry_run,
                    max_tasks=max_tasks
                )
            except Exception as e:
                print(f"[orchestrator] App error ({app_name}): {e}")
        
            time.sleep(1)
    
    logger.save_all()


def run_discovery(
    apps: list = None,
    output_dir: str = "experiments",
    max_time: int = 120
):
    """Run proactive UI discovery mapping for specified apps."""
    print(f"\n{'='*60}")
    print(f"STARTING DISCOVERY RUN")
    print(f"{'='*60}\n")
    
    available_apps = config.get_available_apps()
    if apps:
        targets = [a for a in apps if a in available_apps]
    else:
        targets = available_apps
        
    print(f"[discovery] Target apps: {targets}")
    
    crawler = prober.UIProber(max_time=max_time)
    
    for app_name in targets:
        print(f"\n[discovery] Processing '{app_name}'...")
        app_cfg = config.get_app_config(app_name)
        controller = create_controller(app_name, app_cfg)
        
        try:
            # 1. Start App
            if controller.start_or_connect():
                window = controller.get_window()
                if window:
                    # 2. Run Prober
                    new_elements = crawler.probe_window(window, app_name)
                    print(f"[discovery] Success: Found {new_elements} new elements for {app_name}")
                    
                    # 3. Contraction (Reset UI)
                    crawler.reset_ui(window)
                else:
                    print(f"[discovery] Error: Could not get window for {app_name}")
            else:
                print(f"[discovery] Error: Could not start {app_name}")
        except Exception as e:
            print(f"[discovery] Exception during discovery of {app_name}: {e}")
        finally:
            controller.terminate_app()
            
    print(f"\n{'='*60}")
    print(f"DISCOVERY RUN COMPLETE")
    print(f"{'='*60}\n")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Hybrid GUI Automation Harness"
    )
    
    parser.add_argument(
        "--apps",
        nargs="+",
        help="Specific apps to test (default: all available)"
    )
    
    parser.add_argument(
        "--output-dir",
        default="runs",
        help="Output directory for logs (default: runs)"
    )
    
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cache lookup"
    )
    
    parser.add_argument(
        "--no-vision",
        action="store_true",
        help="Disable vision fallback"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually click, just log"
    )
    
    parser.add_argument(
        "--max-tasks",
        type=int,
        help="Max tasks per app"
    )
    
    parser.add_argument(
        "--list-apps",
        action="store_true",
        help="List available apps and exit"
    )
    
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Run proactive discovery mapping"
    )
    
    parser.add_argument(
        "--discover-time",
        type=int,
        default=300,
        help="Max time per app for discovery (default: 300s)"
    )
    
    args = parser.parse_args()
    
    if args.list_apps:
        print("Available apps:")
        for app in config.get_available_apps():
            tasks = config.get_tasks_for_app(app)
            print(f"  {app}: {len(tasks)} tasks")
        return
    
    if args.discover:
        run_discovery(
            apps=args.apps,
            output_dir=args.output_dir,
            max_time=args.discover_time
        )
        return

    run_all(
        apps=args.apps,
        output_dir=args.output_dir,
        use_cache=not args.no_cache,
        use_vision=not args.no_vision,
        dry_run=args.dry_run,
        max_tasks=args.max_tasks
    )


if __name__ == "__main__":
    main()
