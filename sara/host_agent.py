"""Backward-compatible shim for legacy sara.host_agent imports."""

from sara.core.host_agent import CommandResult, HostAgent

__all__ = ["HostAgent", "CommandResult"]
