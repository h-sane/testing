"""Generate and refresh docs/context/runtime_context.auto.md from live repo state."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SARA_DIR = ROOT / "sara"
DOC_CONTEXT = ROOT / "docs" / "context"
OUT_FILE = DOC_CONTEXT / "runtime_context.auto.md"
ENV_FILE = ROOT / ".env"


def _read_env_subset() -> dict:
    wanted = {
        "AWS_REGION",
        "BEDROCK_MODEL_COMPLEX",
        "BEDROCK_COMPLEX_MODELS",
        "BEDROCK_MODEL_SIMPLE",
        "BEDROCK_SIMPLE_MODELS",
        "SARA_LLM_COMPLEX_PROVIDER",
        "SARA_LLM_SIMPLE_PROVIDER",
    }
    out = {}
    if not ENV_FILE.exists():
        return out

    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in wanted:
            out[key] = value.strip()
    return out


def _module_list() -> list[str]:
    if not SARA_DIR.exists():
        return []
    files = []
    for path in sorted(SARA_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        files.append(path.relative_to(ROOT).as_posix())
    return files


def _render_markdown() -> str:
    env_subset = _read_env_subset()
    modules = _module_list()
    generated_at = datetime.utcnow().isoformat() + "Z"

    lines = [
        "# Runtime Context (Auto)",
        "",
        f"Generated: {generated_at}",
        "",
        "## LLM Runtime Configuration",
        "",
    ]

    if env_subset:
        for key in sorted(env_subset):
            lines.append(f"- {key}: {env_subset[key]}")
    else:
        lines.append("- No env configuration detected")

    lines.extend(
        [
            "",
            "## SARA Python Modules",
            "",
            f"Total modules: {len(modules)}",
            "",
        ]
    )

    if modules:
        lines.extend(f"- {item}" for item in modules)
    else:
        lines.append("- No modules found")

    lines.extend(
        [
            "",
            "## Quick Commands",
            "",
            "- python scripts/sync_docs_context.py",
            "- python demo.py --preflight",
            "- python demo.py --test",
            "",
            "## JSON Snapshot",
            "",
            "```json",
            json.dumps(
                {
                    "generated_at": generated_at,
                    "env": env_subset,
                    "module_count": len(modules),
                },
                indent=2,
            ),
            "```",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    DOC_CONTEXT.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(_render_markdown(), encoding="utf-8")
    print(f"updated: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
