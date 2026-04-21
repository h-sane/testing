"""Neo4j-backed graph memory store for user facts and relations."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sara.memory.graph")


class Neo4jGraphMemoryStore:
    """Optional graph-memory backend. Degrades gracefully when unavailable."""

    def __init__(
        self,
        enabled: bool,
        uri: str,
        user: str,
        password: str,
        database: str,
        user_id: str,
    ):
        self.enabled = bool(enabled)
        self.uri = (uri or "").strip()
        self.user = (user or "").strip()
        self.password = (password or "").strip()
        self.database = (database or "neo4j").strip() or "neo4j"
        self.user_id = (user_id or "local-user").strip() or "local-user"

        self._driver = None
        self._ready = False
        self._last_error = ""

        if not self.enabled:
            return

        if not (self.uri and self.user and self.password):
            self._last_error = "neo4j credentials not configured"
            logger.info("Graph memory disabled: %s", self._last_error)
            return

        try:
            from neo4j import GraphDatabase  # type: ignore

            self._connect_with_fallback(GraphDatabase)
            self._ensure_schema()
            logger.info("Neo4j graph memory connected database=%s uri=%s", self.database, self.uri)
        except Exception as exc:
            self._last_error = str(exc)
            self._ready = False
            self._driver = None
            logger.warning("Neo4j graph memory unavailable: %s", exc)

    def _connect_with_fallback(self, graph_database_module) -> None:
        uris = [self.uri]
        if self.uri.lower().startswith("neo4j://"):
            uris.append("bolt://" + self.uri[len("neo4j://") :])

        last_exc: Optional[Exception] = None
        for candidate in uris:
            driver = None
            try:
                driver = graph_database_module.driver(candidate, auth=(self.user, self.password))
                driver.verify_connectivity()
                self._driver = driver
                self._ready = True
                self._last_error = ""
                if candidate != self.uri:
                    logger.warning("Neo4j routing URI failed; connected with fallback URI %s", candidate)
                    self.uri = candidate
                return
            except Exception as exc:
                last_exc = exc
                if driver is not None:
                    try:
                        driver.close()
                    except Exception:
                        pass

        raise last_exc or RuntimeError("Neo4j connectivity failed")

    @property
    def ready(self) -> bool:
        return self._ready and self._driver is not None

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "ready": self.ready,
            "uri": bool(self.uri),
            "database": self.database,
            "user_id": self.user_id,
            "last_error": self._last_error,
        }

    def close(self) -> None:
        if self._driver is None:
            return
        try:
            self._driver.close()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        if not self.ready:
            return

        statements = [
            "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
            "CREATE INDEX fact_user_key_idx IF NOT EXISTS FOR (f:Fact) ON (f.user_id, f.key)",
            "CREATE INDEX entity_name_idx IF NOT EXISTS FOR (e:Entity) ON (e.name)",
        ]
        for stmt in statements:
            self._execute_write(stmt, {})

    def _execute_write(self, query: str, params: Dict[str, Any]) -> None:
        if not self.ready:
            return
        try:
            with self._driver.session(database=self.database) as session:
                session.execute_write(lambda tx: tx.run(query, **params).consume())
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Neo4j write failed: %s", exc)

    def _execute_read(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.ready:
            return []
        try:
            with self._driver.session(database=self.database) as session:
                records = session.execute_read(lambda tx: list(tx.run(query, **params)))
            out: List[Dict[str, Any]] = []
            for rec in records:
                out.append(dict(rec.items()))
            return out
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Neo4j read failed: %s", exc)
            return []

    def upsert_facts(self, facts: Dict[str, Any], source_text: str = "") -> None:
        if not self.ready or not facts:
            return

        now = datetime.utcnow().isoformat()
        query = (
            "MERGE (u:User {id:$user_id}) "
            "MERGE (f:Fact {user_id:$user_id, key:$key}) "
            "SET f.value=$value, f.updated_at=$updated_at, f.source_text=$source_text "
            "MERGE (u)-[:HAS_FACT]->(f)"
        )
        for key, value in facts.items():
            if not isinstance(key, str) or not key.strip():
                continue
            self._execute_write(
                query,
                {
                    "user_id": self.user_id,
                    "key": key.strip().lower(),
                    "value": str(value),
                    "updated_at": now,
                    "source_text": source_text,
                },
            )

    def upsert_relations(self, relations: List[Dict[str, str]], source_text: str = "") -> None:
        if not self.ready or not relations:
            return

        now = datetime.utcnow().isoformat()
        user_relation_query = (
            "MERGE (u:User {id:$user_id}) "
            "MERGE (e:Entity {name:$object_name}) "
            "SET e.type=coalesce($object_type, e.type), e.updated_at=$updated_at "
            "MERGE (u)-[r:HAS_RELATION {role:$role}]->(e) "
            "SET r.updated_at=$updated_at, r.source_text=$source_text"
        )
        entity_relation_query = (
            "MERGE (s:Entity {name:$subject_name}) "
            "SET s.type=coalesce($subject_type, s.type), s.updated_at=$updated_at "
            "MERGE (o:Entity {name:$object_name}) "
            "SET o.type=coalesce($object_type, o.type), o.updated_at=$updated_at "
            "MERGE (s)-[r:RELATION {role:$role}]->(o) "
            "SET r.updated_at=$updated_at, r.source_text=$source_text"
        )

        for rel in relations:
            role = self._normalize_role(str(rel.get("relation", "")))
            object_name = str(rel.get("object", "")).strip()
            if not role or not object_name:
                continue

            subject = str(rel.get("subject", "user")).strip().lower()
            object_type = str(rel.get("object_type", "Person")).strip() or "Person"

            if subject in {"user", "me", "myself", "i", "my"}:
                self._execute_write(
                    user_relation_query,
                    {
                        "user_id": self.user_id,
                        "role": role,
                        "object_name": object_name,
                        "object_type": object_type,
                        "updated_at": now,
                        "source_text": source_text,
                    },
                )
            else:
                self._execute_write(
                    entity_relation_query,
                    {
                        "subject_name": str(rel.get("subject", "")).strip(),
                        "subject_type": str(rel.get("subject_type", "Person")).strip() or "Person",
                        "role": role,
                        "object_name": object_name,
                        "object_type": object_type,
                        "updated_at": now,
                        "source_text": source_text,
                    },
                )

    def delete_facts(self, keys: List[str]) -> None:
        if not self.ready or not keys:
            return

        cleaned = [str(key or "").strip().lower() for key in keys if str(key or "").strip()]
        if not cleaned:
            return

        query = (
            "MATCH (u:User {id:$user_id})-[:HAS_FACT]->(f:Fact) "
            "WHERE f.key IN $keys "
            "DETACH DELETE f"
        )
        self._execute_write(query, {"user_id": self.user_id, "keys": cleaned})

    def delete_user_relations(
        self,
        roles: Optional[List[str]] = None,
        object_names: Optional[List[str]] = None,
    ) -> None:
        if not self.ready:
            return

        role_values = [self._normalize_role(str(role or "")) for role in (roles or []) if str(role or "").strip()]
        object_values = [str(name or "").strip().lower() for name in (object_names or []) if str(name or "").strip()]

        if role_values:
            query = (
                "MATCH (u:User {id:$user_id})-[r:HAS_RELATION]->(e:Entity) "
                "WHERE r.role IN $roles "
                "DELETE r"
            )
            self._execute_write(query, {"user_id": self.user_id, "roles": role_values})

        if object_values:
            query = (
                "MATCH (u:User {id:$user_id})-[r:HAS_RELATION]->(e:Entity) "
                "WHERE toLower(e.name) IN $objects "
                "DELETE r"
            )
            self._execute_write(query, {"user_id": self.user_id, "objects": object_values})

    def store_interaction(self, command: str, intent: str, outcome: str, app_name: str = "") -> None:
        if not self.ready:
            return

        query = (
            "MERGE (u:User {id:$user_id}) "
            "CREATE (m:MemoryEvent {text:$text, intent:$intent, outcome:$outcome, app_name:$app_name, ts:$ts}) "
            "MERGE (u)-[:HAS_EVENT]->(m)"
        )
        self._execute_write(
            query,
            {
                "user_id": self.user_id,
                "text": command,
                "intent": intent,
                "outcome": outcome,
                "app_name": app_name,
                "ts": datetime.utcnow().isoformat(),
            },
        )

    def get_fact(self, key: str) -> Optional[str]:
        if not self.ready:
            return None

        rows = self._execute_read(
            "MATCH (u:User {id:$user_id})-[:HAS_FACT]->(f:Fact {key:$key}) RETURN f.value AS value LIMIT 1",
            {"user_id": self.user_id, "key": key.strip().lower()},
        )
        if not rows:
            return None
        value = str(rows[0].get("value", "")).strip()
        return value or None

    def get_related_entity(self, role: str) -> Optional[str]:
        if not self.ready:
            return None

        rows = self._execute_read(
            "MATCH (u:User {id:$user_id})-[r:HAS_RELATION {role:$role}]->(e:Entity) "
            "RETURN e.name AS name ORDER BY r.updated_at DESC LIMIT 1",
            {"user_id": self.user_id, "role": self._normalize_role(role)},
        )
        if not rows:
            return None
        name = str(rows[0].get("name", "")).strip()
        return name or None

    def search_context(self, query_text: str, limit: int = 6) -> List[str]:
        if not self.ready:
            return []

        tokens = self._query_tokens(query_text)
        if not tokens:
            return []

        query = (
            "MATCH (u:User {id:$user_id}) "
            "OPTIONAL MATCH (u)-[:HAS_FACT]->(f:Fact) "
            "WITH u, collect(DISTINCT CASE "
            "  WHEN any(t IN $tokens WHERE toLower(f.key) CONTAINS t OR toLower(f.value) CONTAINS t) "
            "  THEN 'fact:' + f.key + '=' + f.value "
            "  ELSE NULL END) AS fact_hits "
            "OPTIONAL MATCH (u)-[r:HAS_RELATION]->(e:Entity) "
            "WITH fact_hits, collect(DISTINCT CASE "
            "  WHEN any(t IN $tokens WHERE toLower(r.role) CONTAINS t OR toLower(e.name) CONTAINS t) "
            "  THEN 'relation:' + r.role + '=' + e.name "
            "  ELSE NULL END) AS relation_hits "
            "WITH [h IN (fact_hits + relation_hits) WHERE h IS NOT NULL][0..$limit] AS hits "
            "UNWIND hits AS h "
            "RETURN h AS line"
        )
        rows = self._execute_read(query, {"user_id": self.user_id, "tokens": tokens, "limit": int(limit)})

        out: List[str] = []
        for row in rows:
            line = str(row.get("line", "")).strip()
            if line and line not in out:
                out.append(line)
        return out[:limit]

    def _query_tokens(self, query_text: str) -> List[str]:
        stop = {
            "the",
            "a",
            "an",
            "my",
            "me",
            "i",
            "is",
            "was",
            "what",
            "who",
            "where",
            "tell",
            "please",
            "do",
            "you",
            "know",
            "about",
        }
        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", str(query_text or "").lower())
        return [tok for tok in tokens if tok not in stop and len(tok) > 1][:8]

    def _normalize_role(self, role: str) -> str:
        value = re.sub(r"[^a-z0-9_]+", "_", str(role or "").strip().lower()).strip("_")
        aliases = {
            "teacher_name": "teacher",
            "mentor": "teacher",
            "boss": "manager",
        }
        return aliases.get(value, value)
