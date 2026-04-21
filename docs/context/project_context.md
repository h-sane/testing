# Project Context

## Current Focus

- Bedrock-first LLM routing with stable fallback behavior.
- Canonical modularization of the sara package for cleaner implementation flow.
- Preparation for full widget implementation in the next phase.

## Canonical Module Layout

- sara/core: orchestration entry modules.
- sara/llm: advanced prompt templates and LLM service layer.
- sara/execution: planner/executor runtime logic and browser macros.
- sara/memory: structured + semantic memory manager.
- sara/privacy: sensitivity classification and routing.
- sara/voice: wake and voice service components.

## Notes

- Legacy top-level sara modules remain for compatibility during migration.
- Runtime context snapshot is generated in runtime_context.auto.md.
