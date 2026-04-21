# Documentation Workspace

This folder is the operational memory and working documentation area for the SARA build.

Main entry document: [MAIN_DOCUMENTATION.md](MAIN_DOCUMENTATION.md)
Legacy gap audit: [LEGACY_CODEBASE_AUDIT.md](LEGACY_CODEBASE_AUDIT.md)

## Structure

- rules: global development rules for this repository.
- skills: reusable implementation playbooks.
- context: current architecture and generated runtime context snapshots.

## Auto-Maintenance

Run the docs sync script to refresh context from current code and env settings:

```powershell
python scripts/sync_docs_context.py
```

The script updates [context/runtime_context.auto.md](context/runtime_context.auto.md).
