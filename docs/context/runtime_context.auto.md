# Runtime Context (Auto)

Generated: 2026-04-20T08:49:10.320097Z

## LLM Runtime Configuration

- AWS_REGION: eu-north-1
- BEDROCK_COMPLEX_MODELS: amazon.nova-lite-v1:0,eu.anthropic.claude-haiku-4-5-20251001-v1:0,eu.anthropic.claude-sonnet-4-6
- BEDROCK_MODEL_COMPLEX: amazon.nova-lite-v1:0
- BEDROCK_MODEL_SIMPLE: amazon.nova-lite-v1:0
- BEDROCK_SIMPLE_MODELS: amazon.nova-lite-v1:0,eu.anthropic.claude-haiku-4-5-20251001-v1:0,amazon.nova-micro-v1:0
- SARA_LLM_COMPLEX_PROVIDER: bedrock
- SARA_LLM_SIMPLE_PROVIDER: bedrock

## SARA Python Modules

Total modules: 45

- sara/__init__.py
- sara/api/__init__.py
- sara/api/local_server.py
- sara/app_agents/__init__.py
- sara/app_agents/base_agent.py
- sara/app_agents/brave_agent.py
- sara/app_agents/calculator_agent.py
- sara/app_agents/chrome_agent.py
- sara/app_agents/excel_agent.py
- sara/app_agents/notepad_agent.py
- sara/app_agents/spotify_agent.py
- sara/browser_macros.py
- sara/config.py
- sara/core/__init__.py
- sara/core/host_agent.py
- sara/execution/__init__.py
- sara/execution/agent.py
- sara/execution/browser_macros.py
- sara/execution/iterative_agent.py
- sara/execution/path_policy.py
- sara/execution_agent.py
- sara/host_agent.py
- sara/knowledge_base_manager.py
- sara/llm/__init__.py
- sara/llm/prompts.py
- sara/llm/service.py
- sara/llm_service.py
- sara/memory/__init__.py
- sara/memory/graph_store.py
- sara/memory/manager.py
- sara/path_policy.py
- sara/privacy/__init__.py
- sara/privacy/router.py
- sara/privacy/sanitizer.py
- sara/privacy_router.py
- sara/ui/__init__.py
- sara/ui/chat_widget.py
- sara/ui/styles.py
- sara/ui/widget.py
- sara/voice/__init__.py
- sara/voice/service.py
- sara/voice/wake_controller.py
- sara/voice_service.py
- sara/wake_controller.py
- sara/workflow_policy.py

## Quick Commands

- python scripts/sync_docs_context.py
- python demo.py --preflight
- python demo.py --test

## JSON Snapshot

```json
{
  "generated_at": "2026-04-20T08:49:10.320097Z",
  "env": {
    "AWS_REGION": "eu-north-1",
    "BEDROCK_MODEL_COMPLEX": "amazon.nova-lite-v1:0",
    "BEDROCK_COMPLEX_MODELS": "amazon.nova-lite-v1:0,eu.anthropic.claude-haiku-4-5-20251001-v1:0,eu.anthropic.claude-sonnet-4-6",
    "BEDROCK_MODEL_SIMPLE": "amazon.nova-lite-v1:0",
    "BEDROCK_SIMPLE_MODELS": "amazon.nova-lite-v1:0,eu.anthropic.claude-haiku-4-5-20251001-v1:0,amazon.nova-micro-v1:0",
    "SARA_LLM_COMPLEX_PROVIDER": "bedrock",
    "SARA_LLM_SIMPLE_PROVIDER": "bedrock"
  },
  "module_count": 45
}
```
