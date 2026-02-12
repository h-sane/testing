# src/llm/orchestrator.py
"""
ReAct-style LLM Orchestrator for UI Automation.

Takes high-level user instructions (e.g., "Open a file in Notepad") and
decomposes them into concrete UI steps using the LLM's planning ability,
executing each step via the step_executor (Cache → AX → Vision pipeline).

Architecture:
    User Instruction → LLM Plan → Step Executor → Observation → LLM Replan → ...

The LLM sees:
  - Application name and window title
  - Available cached UI elements (names + control types)
  - Action history with success/failure observations
  - Current screenshot description (optional, via VLM)
"""

import os
import sys
import json
import time
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.llm.llm_client import get_client, LLMResponse
from src.llm.step_executor import execute_step

logger = logging.getLogger("orchestrator")

# =============================================================================
# CONFIGURATION
# =============================================================================

MAX_STEPS = 15          # Maximum steps per instruction
MAX_RETRIES = 2         # Retries per step on failure
STEP_TIMEOUT = 30.0     # Seconds per step

SYSTEM_PROMPT = """You are a Windows UI automation agent. You receive a high-level user instruction and must decompose it into concrete UI interaction steps.

## Available Actions
- CLICK: Click a UI element by name/label. Example: {"action_type": "CLICK", "target": "File"}
- TYPE: Type text into the focused element. Example: {"action_type": "TYPE", "text": "hello.txt"}
- HOTKEY: Press a keyboard shortcut. Example: {"action_type": "HOTKEY", "keys": "ctrl+s"}
- WAIT: Wait for UI to update. Example: {"action_type": "WAIT", "seconds": 1.0}
- DONE: Signal completion. Example: {"action_type": "DONE", "reason": "File opened successfully"}
- FAIL: Signal inability to proceed. Example: {"action_type": "FAIL", "reason": "Cannot find Save button"}

## Response Format
Respond with EXACTLY ONE JSON object per turn. No other text.
```json
{
  "thought": "Brief reasoning about what to do next",
  "action": {"action_type": "CLICK", "target": "File"}
}
```

## Rules
1. Execute ONE action per turn, then observe the result before planning the next.
2. For menu items, click the parent menu FIRST, wait briefly, then click the submenu item.
3. Use HOTKEY for common shortcuts (Ctrl+S, Ctrl+N, etc.) when faster than menu navigation.
4. If a CLICK fails, try alternative approaches: HOTKEY, different target name, or WAIT then retry.
5. Target names should match UI element labels EXACTLY as they appear (e.g., "File" not "file menu").
6. After completing all steps, emit a DONE action.
7. If stuck after 3 failures, emit a FAIL action.
"""


# =============================================================================
# ORCHESTRATOR
# =============================================================================

@dataclass
class StepRecord:
    """Record of a single executed step."""
    step_num: int
    thought: str
    action: Dict[str, Any]
    result: Dict[str, Any]
    latency_ms: int


@dataclass
class ExecutionTrace:
    """Full trace of an orchestrated instruction."""
    instruction: str
    app_name: str
    steps: List[StepRecord] = field(default_factory=list)
    success: bool = False
    total_ms: int = 0
    llm_calls: int = 0
    error: str = ""


class Orchestrator:
    """
    ReAct-style agent that plans and executes UI automation steps.
    
    Usage:
        orch = Orchestrator()
        trace = orch.execute("Open a new tab in Notepad", window, "Notepad")
    """
    
    def __init__(self):
        self.client = get_client()
    
    def execute(
        self,
        instruction: str,
        window,
        app_name: str,
        available_elements: Optional[List[str]] = None,
    ) -> ExecutionTrace:
        """
        Execute a high-level instruction by planning and executing steps.
        
        Args:
            instruction: Natural language instruction (e.g., "Save the file as report.txt")
            window: pywinauto window wrapper
            app_name: Application name (e.g., "Notepad")
            available_elements: Optional list of known UI element names from cache
        
        Returns:
            ExecutionTrace with full step history
        """
        trace = ExecutionTrace(instruction=instruction, app_name=app_name)
        start_time = time.time()
        
        # Build context for the LLM
        context = self._build_context(instruction, app_name, window, available_elements)
        history: List[Dict[str, str]] = []
        
        logger.info(f"[orchestrator] Starting: '{instruction}' on {app_name}")
        print(f"\n{'='*60}")
        print(f"[LLM Orchestrator] Instruction: {instruction}")
        print(f"{'='*60}")
        
        for step_num in range(1, MAX_STEPS + 1):
            step_start = time.time()
            
            # 1. Build prompt with history
            prompt = self._build_prompt(context, history)
            
            # 2. Call LLM
            llm_response = self.client.call(
                prompt=prompt,
                system=SYSTEM_PROMPT,
                max_tokens=512,
                temperature=0.1,
            )
            trace.llm_calls += 1
            
            if llm_response.error:
                logger.error(f"[orchestrator] LLM error: {llm_response.error}")
                trace.error = f"LLM error: {llm_response.error}"
                break
            
            # 3. Parse LLM response
            parsed = self._parse_response(llm_response.text)
            if not parsed:
                logger.warning(f"[orchestrator] Failed to parse LLM response: {llm_response.text[:200]}")
                history.append({
                    "role": "system",
                    "content": "ERROR: Your response was not valid JSON. Please respond with exactly one JSON object."
                })
                continue
            
            thought = parsed.get("thought", "")
            action = parsed.get("action", {})
            action_type = action.get("action_type", "").upper()
            
            print(f"\n[Step {step_num}] Thought: {thought}")
            print(f"[Step {step_num}] Action: {json.dumps(action)}")
            
            # 4. Check terminal actions
            if action_type == "DONE":
                trace.success = True
                trace.steps.append(StepRecord(
                    step_num=step_num,
                    thought=thought,
                    action=action,
                    result={"success": True, "method": "DONE"},
                    latency_ms=int((time.time() - step_start) * 1000),
                ))
                logger.info(f"[orchestrator] DONE: {action.get('reason', '')}")
                print(f"[Step {step_num}] ✅ DONE: {action.get('reason', '')}")
                break
            
            if action_type == "FAIL":
                trace.error = action.get("reason", "Agent gave up")
                trace.steps.append(StepRecord(
                    step_num=step_num,
                    thought=thought,
                    action=action,
                    result={"success": False, "method": "FAIL"},
                    latency_ms=int((time.time() - step_start) * 1000),
                ))
                logger.info(f"[orchestrator] FAIL: {trace.error}")
                print(f"[Step {step_num}] ❌ FAIL: {trace.error}")
                break
            
            # 5. Execute the step
            result = execute_step(action, window=window, app_name=app_name)
            step_ms = int((time.time() - step_start) * 1000)
            
            trace.steps.append(StepRecord(
                step_num=step_num,
                thought=thought,
                action=action,
                result=result,
                latency_ms=step_ms,
            ))
            
            status = "✅" if result.get("success") else "❌"
            print(f"[Step {step_num}] {status} Result: {result.get('method')} | {result.get('error', '')}")
            
            # 6. Add observation to history
            observation = (
                f"Step {step_num} result: "
                f"{'SUCCESS' if result.get('success') else 'FAILED'} "
                f"(method={result.get('method', '?')}"
                f"{', error=' + result.get('error') if result.get('error') else ''})"
            )
            
            history.append({"role": "assistant", "content": json.dumps(parsed)})
            history.append({"role": "user", "content": f"Observation: {observation}\n\nWhat is your next action?"})
            
            # Brief stabilization pause
            time.sleep(0.5)
        
        trace.total_ms = int((time.time() - start_time) * 1000)
        
        print(f"\n{'='*60}")
        print(f"[LLM Orchestrator] {'SUCCESS' if trace.success else 'FAILED'} in {trace.total_ms}ms ({len(trace.steps)} steps, {trace.llm_calls} LLM calls)")
        print(f"{'='*60}\n")
        
        return trace
    
    def _build_context(
        self, 
        instruction: str, 
        app_name: str, 
        window,
        available_elements: Optional[List[str]] = None,
    ) -> str:
        """Build the initial context string for the LLM."""
        parts = [
            f"Application: {app_name}",
        ]
        
        # Add window title
        try:
            title = window.window_text() or "Unknown"
            parts.append(f"Window Title: {title}")
        except:
            pass
        
        parts.append(f"\nInstruction: {instruction}")
        
        # Add known UI elements from cache
        if available_elements:
            elem_str = ", ".join(available_elements[:30])  # Cap at 30 for context window
            parts.append(f"\nKnown UI Elements: [{elem_str}]")
        else:
            # Try loading from cache
            try:
                from src.automation import storage
                cache = storage.load_cache(app_name)
                elements = cache.get("elements", {})
                names = sorted(set(
                    e.get("name", "") for e in elements.values() if e.get("name")
                ))[:30]
                if names:
                    parts.append(f"\nKnown UI Elements: [{', '.join(names)}]")
            except:
                pass
        
        return "\n".join(parts)
    
    def _build_prompt(self, context: str, history: List[Dict[str, str]]) -> str:
        """Build the full prompt including context and conversation history."""
        parts = [context]
        
        if not history:
            parts.append("\nPlan your first action. Respond with a single JSON object.")
        else:
            parts.append("\n--- Conversation History ---")
            for msg in history[-10:]:  # Keep last 10 messages for context
                role = msg["role"].upper()
                parts.append(f"\n[{role}]: {msg['content']}")
        
        return "\n".join(parts)
    
    def _parse_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse LLM text response into structured action."""
        text = text.strip()
        
        # Try direct JSON parse
        try:
            return json.loads(text)
        except:
            pass
        
        # Try extracting JSON from markdown code block
        if "```" in text:
            for block in text.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                try:
                    return json.loads(block)
                except:
                    continue
        
        # Try finding JSON object in text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except:
                pass
        
        return None


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def run_instruction(
    instruction: str,
    window,
    app_name: str,
    available_elements: Optional[List[str]] = None,
) -> ExecutionTrace:
    """
    Convenience function to run a single instruction.
    
    Usage:
        from src.llm.orchestrator import run_instruction
        trace = run_instruction("Open File menu", window, "Notepad")
        print(trace.success)
    """
    orch = Orchestrator()
    return orch.execute(instruction, window, app_name, available_elements)
