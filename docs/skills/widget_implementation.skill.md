# Skill: Widget Implementation Readiness

## Goal

Prepare the codebase for clean implementation of the always-on-top SARA widget.

## Checklist

- Keep UI state transitions explicit (Idle, Listening, Planning, Acting, Verifying, Done, Failed).
- Keep widget transport separate from orchestration logic.
- Use VoiceService and HostAgent via canonical package imports.
- Keep dry-run and live-run behavior switchable at runtime.
- Ensure non-blocking background processing for command execution.

## Validation

- Widget starts from demo entrypoint.
- Typed command and push-to-talk routes both reach HostAgent.
- Status labels update per execution phase.
