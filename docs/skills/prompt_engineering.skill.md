# Skill: Prompt Engineering for SARA

## Goal

Design prompt templates that keep model output deterministic, parseable, and safe for automation.

## Checklist

- Define strict output schema and enforce JSON-only response.
- Constrain action vocabulary to supported executor actions.
- Include safety constraints for destructive operations.
- Keep planning prompts app-context aware (app name + UI summary + failure context).
- Keep conversation prompts concise and actionable.

## Validation

- Verify parse success on malformed or markdown-wrapped responses.
- Verify fallback heuristics still produce minimal executable plans.
