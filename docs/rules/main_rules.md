# Main Rules

## Architecture

- Keep runtime orchestration in the sara package.
- Keep low-level UI automation framework in src/.
- Add new functionality in canonical modular packages first.
- Keep backward-compatible shims only when needed for migration.

## Coding

- Prefer deterministic automation paths over vision fallback.
- Keep LLM outputs strictly JSON-parseable for planning and intent.
- Default provider policy should not block development on single-model outages.

## Documentation

- Update skills and context docs whenever architecture or routing policy changes.
- Regenerate runtime context before major implementation sessions.

## Error Resolution

- Do not conclude an external service is down until evidence is collected from all of: env key validation, TCP reachability, active listener check, and service/runtime logs.
- For Neo4j issues, always verify and report: `SARA_NEO4J_*` config values, `Test-NetConnection` result for configured host/port, local listener state for Bolt/HTTP ports, and DBMS log timestamps.
- If a Neo4j database exists on disk but connection fails, classify as runtime exposure/startup issue (not missing database creation) unless `SHOW DATABASES` proves otherwise.
- Capture proof lines in the task report (timestamps, ports, and exact error text) before proposing remediation.
