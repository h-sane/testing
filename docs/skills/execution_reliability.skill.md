# Skill: Execution Reliability

## Goal

Maintain high completion rate for automation commands under variable provider and UI conditions.

## Checklist

- Ensure step-by-step verification gates remain enabled.
- Keep per-step retry + bounded replan loops.
- Use model fallback for provider/model-level denials.
- Avoid promoting temporary auth/payment denials into permanent provider disablement.
- Persist run traces for post-mortem analysis.

## Validation

- Compile checks for changed modules.
- Probe simple and complex LLM calls with strict preferred mode.
- Run demo preflight and demo test suite.
