"""Backward-compatible shim for legacy sara.execution_agent imports."""

from sara.execution.agent import AgentRunResult, ExecutionAgent, StepTrace

__all__ = ["ExecutionAgent", "StepTrace", "AgentRunResult"]
