"""Dual-memory manager for structured facts and semantic interaction recall."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sara.config import (
    CHROMA_DIR,
    FACTS_FILE,
    MEMORY_RECALL_K,
    PROFILE_FILE,
    SARA_ENABLE_GRAPH_MEMORY,
    SARA_MEMORY_USER_ID,
    SARA_NEO4J_DATABASE,
    SARA_NEO4J_PASSWORD,
    SARA_NEO4J_URI,
    SARA_NEO4J_USER,
)
from sara.memory.graph_store import Neo4jGraphMemoryStore

logger = logging.getLogger("sara.memory")


def _sbert_allowed_by_env_and_numpy() -> bool:
    """Gate SBERT to avoid known noisy NumPy/Torch incompatibility paths."""
    force = os.getenv("SARA_FORCE_SBERT", "0").strip().lower() in {"1", "true", "yes", "on"}
    if force:
        return True

    try:
        version = importlib.metadata.version("numpy")
        major = int(str(version).split(".")[0])
        if major >= 2:
            logger.debug(
                "SBERT disabled by default on NumPy>=2 environment. "
                "Set SARA_FORCE_SBERT=1 to force-enable if your torch stack supports it."
            )
            return False
    except importlib.metadata.PackageNotFoundError:
        return True
    except Exception:
        pass

    return True


def _sbert_allowed_by_tokenizers() -> bool:
    """Gate SBERT when tokenizers is outside common transformers compatibility."""
    force = os.getenv("SARA_FORCE_SBERT", "0").strip().lower() in {"1", "true", "yes", "on"}
    if force:
        return True

    try:
        version = importlib.metadata.version("tokenizers")
        parts = version.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        if major > 0 or minor >= 19:
            logger.debug(
                "SBERT disabled by default because tokenizers=%s is outside common "
                "sentence-transformers compatibility (<0.19). Set SARA_FORCE_SBERT=1 "
                "to override.",
                version,
            )
            return False
    except importlib.metadata.PackageNotFoundError:
        return True
    except Exception:
        return True

    return True


def _load_sentence_transformer_class():
    if not _sbert_allowed_by_env_and_numpy():
        return None
    if not _sbert_allowed_by_tokenizers():
        return None

    try:
        module = importlib.import_module("sentence_transformers")
        return getattr(module, "SentenceTransformer", None)
    except Exception as exc:
        logger.warning("SBERT library unavailable: %s", exc)
        return None


def _load_chromadb_module():
    enabled = os.getenv("SARA_ENABLE_CHROMA", "1").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return None

    try:
        return importlib.import_module("chromadb")
    except Exception as exc:
        logger.debug("Chroma module unavailable: %s", exc)
        return None


class KnowledgeBaseManager:
    """Maintains structured facts + semantic history with graceful fallbacks."""

    def __init__(self):
        Path(FACTS_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)
        Path(PROFILE_FILE).parent.mkdir(parents=True, exist_ok=True)

        self._facts: Dict[str, Any] = self._load_facts()
        self._history: List[str] = []
        self._encoder = None
        self._collection = None
        self._profile: Dict[str, Any] = self._load_profile()
        self._seed_profile_defaults()
        self.bootstrap_identity(self._facts)
        self._graph = Neo4jGraphMemoryStore(
            enabled=SARA_ENABLE_GRAPH_MEMORY,
            uri=SARA_NEO4J_URI,
            user=SARA_NEO4J_USER,
            password=SARA_NEO4J_PASSWORD,
            database=SARA_NEO4J_DATABASE,
            user_id=SARA_MEMORY_USER_ID,
        )

        sentence_transformer_cls = _load_sentence_transformer_class()
        if sentence_transformer_cls is not None:
            try:
                self._encoder = sentence_transformer_cls("all-MiniLM-L6-v2")
            except Exception as exc:
                logger.warning("SBERT disabled: %s", exc)

        chromadb_module = _load_chromadb_module()
        if chromadb_module is not None:
            try:
                client = chromadb_module.PersistentClient(path=str(CHROMA_DIR))
                self._collection = client.get_or_create_collection(
                    name="sara_semantic_memory", metadata={"hnsw:space": "cosine"}
                )
            except Exception as exc:
                logger.warning("Chroma disabled: %s", exc)

        # Keep graph memory in sync with facts recovered from disk.
        if self._facts:
            self._graph.upsert_facts(self._facts, source_text="bootstrap_facts")

    def __del__(self):
        try:
            self._graph.close()
        except Exception:
            pass

    def _load_facts(self) -> Dict[str, Any]:
        if not os.path.exists(FACTS_FILE):
            return {}
        try:
            with open(FACTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_facts(self) -> None:
        with open(FACTS_FILE, "w", encoding="utf-8") as f:
            json.dump(self._facts, f, indent=2, ensure_ascii=False)

    def _load_profile(self) -> Dict[str, Any]:
        if not os.path.exists(PROFILE_FILE):
            return {}
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_profile(self) -> None:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(self._profile, f, indent=2, ensure_ascii=False)

    def _seed_profile_defaults(self) -> None:
        if "identity" not in self._profile or not isinstance(self._profile.get("identity"), dict):
            self._profile["identity"] = {
                "user_id": "local-user",
                "display_name": "",
                "created_at": datetime.utcnow().isoformat(),
            }

        if "preferences" not in self._profile or not isinstance(self._profile.get("preferences"), dict):
            self._profile["preferences"] = {
                "response_style": "concise",
                "preferred_apps": [],
            }

        if "app_success_priors" not in self._profile or not isinstance(
            self._profile.get("app_success_priors"), dict
        ):
            self._profile["app_success_priors"] = {}

        if "pattern_success_priors" not in self._profile or not isinstance(
            self._profile.get("pattern_success_priors"), dict
        ):
            self._profile["pattern_success_priors"] = {}

        self._profile["last_bootstrap_at"] = datetime.utcnow().isoformat()
        self._save_profile()

    def bootstrap_identity(self, seed_facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        facts = seed_facts or self._facts
        identity = self._profile.setdefault("identity", {})

        name = str(facts.get("name", "")).strip()
        if name:
            identity["display_name"] = name

        organization = str(facts.get("organization", "")).strip()
        if organization:
            self._profile.setdefault("preferences", {}).setdefault("organization", organization)

        location = str(facts.get("location", "")).strip()
        if location:
            self._profile.setdefault("preferences", {}).setdefault("location", location)

        for key, value in facts.items():
            if isinstance(key, str) and key.startswith("preference_"):
                self._profile.setdefault("preferences", {})[key] = value

        self._profile["last_bootstrap_at"] = datetime.utcnow().isoformat()
        self._save_profile()
        return dict(identity)

    def update_graph_memory(self, facts: Dict[str, Any], relations: List[Dict[str, str]], source_text: str) -> None:
        if facts:
            self._graph.upsert_facts(facts, source_text=source_text)
        if relations:
            self._graph.upsert_relations(relations, source_text=source_text)

    def answer_memory_query(self, query: str) -> Optional[str]:
        text = (query or "").strip().lower()
        if not text:
            return None

        # High-priority personal fact lookups.
        if "name" in text and "my" in text:
            name = self._graph.get_fact("name") or str(self._facts.get("name", "")).strip()
            if name:
                return f"Your name is {name}."

        if ("work" in text or "organization" in text or "company" in text) and "my" in text:
            org = (
                self._graph.get_fact("organization")
                or self._graph.get_fact("company")
                or str(self._facts.get("organization", "")).strip()
            )
            if org:
                return f"You work at {org}."

        if ("live" in text or "location" in text or "city" in text) and "my" in text:
            location = self._graph.get_fact("location") or str(self._facts.get("location", "")).strip()
            if location:
                return f"You live in {location}."

        role = self._role_from_query(text)
        if role:
            person = self._graph.get_related_entity(role)
            if not person:
                person = str(self._facts.get(f"{role}_name", "")).strip()
            if person:
                return f"Your {role} is {person}."

        graph_lines = self._graph.search_context(query, limit=6)
        if graph_lines:
            bullets = "\n- ".join(graph_lines)
            return f"From graph memory:\n- {bullets}"

        if self._facts:
            pairs = [f"{k}={v}" for k, v in sorted(self._facts.items())[:8]]
            return "I found these stored facts: " + ", ".join(pairs)

        return None

    def resolve_references(self, text: str) -> str:
        source = str(text or "")
        if not source:
            return source

        role_patterns = {
            "teacher": [r"\bmy teacher\b"],
            "manager": [r"\bmy manager\b", r"\bmy boss\b"],
            "doctor": [r"\bmy doctor\b"],
            "friend": [r"\bmy friend\b"],
        }

        resolved = source
        for role, patterns in role_patterns.items():
            entity_name = self._graph.get_related_entity(role)
            if not entity_name:
                local_key = f"{role}_name"
                entity_name = str(self._facts.get(local_key, "")).strip()
            if not entity_name:
                continue

            for pattern in patterns:
                resolved = re.sub(pattern, entity_name, resolved, flags=re.IGNORECASE)

        return resolved

    def _role_from_query(self, text: str) -> str:
        role_aliases = {
            "teacher": ["teacher", "mentor", "professor"],
            "manager": ["manager", "boss", "lead"],
            "doctor": ["doctor", "physician"],
            "friend": ["friend"],
        }
        for role, markers in role_aliases.items():
            if any(marker in text for marker in markers):
                return role
        return ""

    def update_structured_facts(self, new_facts: Dict[str, Any]) -> None:
        if not new_facts:
            return
        self._facts.update(new_facts)
        self._save_facts()
        self.bootstrap_identity(new_facts)
        self._graph.upsert_facts(new_facts, source_text="structured_facts")

    def _remove_profile_fact_bindings(self, key: str) -> None:
        normalized = str(key or "").strip().lower()
        identity = self._profile.setdefault("identity", {})
        preferences = self._profile.setdefault("preferences", {})

        if normalized == "name":
            identity["display_name"] = ""
        elif normalized in {"organization", "company", "location"}:
            preferences.pop(normalized, None)
        elif normalized.startswith("preference_"):
            preferences.pop(normalized, None)

    def delete_structured_facts(self, keys: List[str]) -> List[str]:
        if not keys:
            return []

        removed: List[str] = []
        for raw in keys:
            key = str(raw or "").strip().lower()
            if not key:
                continue
            if key in self._facts:
                self._facts.pop(key, None)
                self._remove_profile_fact_bindings(key)
                removed.append(key)

        if removed:
            self._save_facts()
            self._save_profile()
            self._graph.delete_facts(removed)

        return removed

    def apply_memory_operations(self, operations: Dict[str, Any], source_text: str = "") -> Dict[str, List[str]]:
        delete_fact_keys = [str(key or "").strip().lower() for key in operations.get("delete_fact_keys", [])]
        delete_relation_roles = [str(role or "").strip().lower() for role in operations.get("delete_relation_roles", [])]
        delete_relation_objects = [str(obj or "").strip() for obj in operations.get("delete_relation_objects", [])]

        removed_facts: List[str] = []
        removed_relations: List[str] = []

        if delete_fact_keys:
            removed_facts.extend(self.delete_structured_facts(delete_fact_keys))

        if delete_relation_roles or delete_relation_objects:
            self._graph.delete_user_relations(roles=delete_relation_roles, object_names=delete_relation_objects)

            role_to_keys = {
                "teacher": ["teacher_name", "mentor_name"],
                "mentor": ["teacher_name", "mentor_name"],
                "manager": ["manager_name", "boss_name"],
                "boss": ["manager_name", "boss_name"],
                "doctor": ["doctor_name"],
                "friend": ["friend_name"],
                "parent": ["parent_name"],
                "spouse": ["spouse_name"],
                "sibling": ["sibling_name"],
                "works_at": ["organization", "company"],
                "lives_in": ["location"],
            }

            local_keys_to_remove: List[str] = []
            for role in delete_relation_roles:
                local_keys_to_remove.extend(role_to_keys.get(role, [f"{role}_name"]))
                removed_relations.append(f"role:{role}")

            if delete_relation_objects:
                targets = {value.lower() for value in delete_relation_objects}
                for key, value in list(self._facts.items()):
                    if str(value or "").strip().lower() in targets:
                        local_keys_to_remove.append(key)
                for obj in delete_relation_objects:
                    removed_relations.append(f"object:{obj}")

            if local_keys_to_remove:
                removed_facts.extend(self.delete_structured_facts(local_keys_to_remove))

        deduped_facts: List[str] = []
        for key in removed_facts:
            if key not in deduped_facts:
                deduped_facts.append(key)

        deduped_relations: List[str] = []
        for rel in removed_relations:
            if rel not in deduped_relations:
                deduped_relations.append(rel)

        if source_text and (deduped_facts or deduped_relations):
            self._graph.store_interaction(
                command=source_text,
                intent="remember",
                outcome="memory_mutation",
                app_name="",
            )

        return {
            "removed_facts": deduped_facts,
            "removed_relations": deduped_relations,
        }

    def get_structured_facts(self) -> Dict[str, Any]:
        return dict(self._facts)

    def get_fact(self, key: str) -> Optional[Any]:
        return self._facts.get(key)

    def store_interaction(
        self,
        command: str,
        outcome: str,
        intent: str = "unknown",
        app_name: Optional[str] = None,
    ) -> None:
        text = f"Command: {command} | Outcome: {outcome} | Intent: {intent}"
        self._history.append(text)

        self._graph.store_interaction(
            command=command,
            intent=intent,
            outcome=outcome,
            app_name=str(app_name or ""),
        )

        self._update_success_priors(command=command, app_name=app_name, success=(outcome == "success"))

        if self._collection is None or self._encoder is None:
            return

        try:
            emb = self._encoder.encode(text).tolist()
            self._collection.add(
                ids=[f"interaction_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"],
                documents=[text],
                embeddings=[emb],
                metadatas=[{"intent": intent, "timestamp": datetime.utcnow().isoformat()}],
            )
        except Exception as exc:
            logger.debug("Semantic store skipped: %s", exc)

    def _command_pattern(self, command: str) -> str:
        tokens = [tok for tok in str(command or "").lower().split() if tok.isalpha() or tok.isalnum()]
        return " ".join(tokens[:5]).strip() or "generic"

    def _update_success_priors(self, command: str, app_name: Optional[str], success: bool) -> None:
        app_key = str(app_name or "generic")
        app_priors = self._profile.setdefault("app_success_priors", {})
        app_entry = app_priors.setdefault(app_key, {"success": 0, "total": 0})
        app_entry["total"] = int(app_entry.get("total", 0)) + 1
        if success:
            app_entry["success"] = int(app_entry.get("success", 0)) + 1

        pattern_key = self._command_pattern(command)
        pattern_priors = self._profile.setdefault("pattern_success_priors", {})
        pattern_entry = pattern_priors.setdefault(pattern_key, {"success": 0, "total": 0})
        pattern_entry["total"] = int(pattern_entry.get("total", 0)) + 1
        if success:
            pattern_entry["success"] = int(pattern_entry.get("success", 0)) + 1

        prefs = self._profile.setdefault("preferences", {})
        preferred_apps = prefs.setdefault("preferred_apps", [])
        if success and app_key != "generic" and app_key not in preferred_apps:
            preferred_apps.append(app_key)

        self._save_profile()

    def get_planning_bias(self, app_name: str, command: str) -> str:
        app_priors = self._profile.get("app_success_priors", {})
        pattern_priors = self._profile.get("pattern_success_priors", {})

        app_entry = app_priors.get(app_name, {"success": 0, "total": 0})
        app_total = int(app_entry.get("total", 0))
        app_success = int(app_entry.get("success", 0))
        app_rate = (app_success / app_total) if app_total else 0.0

        pattern_key = self._command_pattern(command)
        pattern_entry = pattern_priors.get(pattern_key, {"success": 0, "total": 0})
        pattern_total = int(pattern_entry.get("total", 0))
        pattern_success = int(pattern_entry.get("success", 0))
        pattern_rate = (pattern_success / pattern_total) if pattern_total else 0.0

        prefs = self._profile.get("preferences", {})
        preferred_apps = prefs.get("preferred_apps", [])

        return (
            f"planning_bias: app={app_name} app_success_rate={app_rate:.2f} "
            f"({app_success}/{app_total}), pattern='{pattern_key}' "
            f"pattern_success_rate={pattern_rate:.2f} ({pattern_success}/{pattern_total}), "
            f"preferred_apps={preferred_apps}"
        )

    def get_profile_snapshot(self) -> Dict[str, Any]:
        return dict(self._profile)

    def recall_memories(self, query: str, num_results: int = MEMORY_RECALL_K) -> List[str]:
        recalled: List[str] = []

        graph_hits = self._graph.search_context(query, limit=max(num_results, 2))
        recalled.extend(graph_hits)

        if self._collection is not None and self._encoder is not None:
            try:
                count = self._collection.count()
                if count > 0:
                    emb = self._encoder.encode(query).tolist()
                    result = self._collection.query(
                        query_embeddings=[emb],
                        n_results=min(max(num_results, 1), count),
                    )
                    docs = result.get("documents", [])
                    if docs and isinstance(docs[0], list):
                        recalled.extend(str(item) for item in docs[0])
            except Exception:
                pass

        if self._history:
            n = max(num_results, 1)
            recalled.extend(self._history[-n:])

        deduped: List[str] = []
        for item in recalled:
            line = str(item).strip()
            if line and line not in deduped:
                deduped.append(line)

        return deduped[: max(num_results, 1) * 3]

    def get_memory_summary(self) -> Dict[str, Any]:
        identity = self._profile.get("identity", {}) if isinstance(self._profile, dict) else {}
        display_name = str(identity.get("display_name", "")).strip()
        graph_status = self._graph.status()
        return {
            "facts_count": len(self._facts),
            "facts_keys": sorted(self._facts.keys()),
            "history_count": len(self._history),
            "semantic_enabled": self._collection is not None and self._encoder is not None,
            "chroma_count": self._collection.count() if self._collection is not None else 0,
            "graph_memory": graph_status,
            "identity": {
                "display_name": display_name,
                "user_id": identity.get("user_id", "local-user"),
            },
            "preferred_apps": self._profile.get("preferences", {}).get("preferred_apps", []),
        }
