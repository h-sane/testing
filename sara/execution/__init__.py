"""Canonical execution package for SARA."""

from sara.execution.agent import AgentRunResult, ExecutionAgent, StepTrace
from sara.execution.browser_macros import BROWSER_APPS, get_macro_steps
from sara.execution.iterative_agent import IterativeExecutionAgent, IterativeRunResult, IterativeStepTrace

__all__ = [
    "ExecutionAgent",
    "StepTrace",
    "AgentRunResult",
    "IterativeExecutionAgent",
    "IterativeStepTrace",
    "IterativeRunResult",
    "BROWSER_APPS",
    "get_macro_steps",
]
