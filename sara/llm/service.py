"""LLM service helpers for intent, planning, facts, and conversation."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from sara.llm.prompts import (
    SYSTEM_PROMPT_COMMAND_UNDERSTANDING,
    SYSTEM_PROMPT_CONVERSATION,
    SYSTEM_PROMPT_FACTS,
    SYSTEM_PROMPT_GRAPH_MEMORY,
    SYSTEM_PROMPT_ITERATIVE_ACTION,
    SYSTEM_PROMPT_PLAN,
    build_command_understanding_prompt,
    build_conversation_prompt,
    build_facts_prompt,
    build_graph_memory_prompt,
    build_iterative_action_prompt,
    build_plan_prompt,
)
from sara.workflow_policy import (
    build_save_as_steps,
    extract_save_as_filename as _global_extract_save_as_filename,
    extract_write_payload as _global_extract_write_payload,
    is_save_as_intent,
    looks_like_text_entry_intent,
)
from src.llm.llm_client import get_client


logger = logging.getLogger("sara.llm.service")


LLM_SIMPLE_PROVIDER = os.getenv("SARA_LLM_SIMPLE_PROVIDER", "bedrock").strip().lower() or "bedrock"
LLM_COMPLEX_PROVIDER = os.getenv("SARA_LLM_COMPLEX_PROVIDER", "bedrock").strip().lower() or "bedrock"

_ALLOWED_INTENTS = {"automation", "remember", "screen_read", "conversation"}
_ALLOWED_ACTION_TYPES = {
    "automation",
    "memory_write",
    "memory_update",
    "memory_delete",
    "memory_read",
    "qa",
    "conversation",
}
_ALLOWED_ITERATIVE_ACTIONS = {"CLICK", "TYPE", "HOTKEY", "WAIT", "DONE", "FAIL"}
_ROLE_FACT_KEYS = {
    "teacher_name",
    "manager_name",
    "boss_name",
    "doctor_name",
    "friend_name",
    "mentor_name",
    "parent_name",
    "spouse_name",
    "sibling_name",
}
_ALLOWED_FACT_KEYS = {
    "name",
    "organization",
    "company",
    "location",
    "education",
    "education_level",
}
_ALLOWED_RELATIONS = {
    "teacher",
    "manager",
    "boss",
    "friend",
    "doctor",
    "mentor",
    "parent",
    "spouse",
    "sibling",
    "works_at",
    "lives_in",
    "student",
}
_MEMORY_ROLE_ALIASES = {
    "teacher": ["teacher", "mentor", "professor"],
    "manager": ["manager", "boss", "lead"],
    "doctor": ["doctor", "physician"],
    "friend": ["friend"],
    "parent": ["parent", "father", "mother", "dad", "mom"],
    "spouse": ["spouse", "wife", "husband", "partner"],
    "sibling": ["sibling", "brother", "sister"],
}


def _normalize_match_text(value: str) -> str:
    lowered = str(value or "").lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _value_present_in_text(value: Any, text: str) -> bool:
    needle = _normalize_match_text(str(value or ""))
    hay = _normalize_match_text(text)
    return bool(needle) and bool(hay) and needle in hay


def _clean_person_fragment(value: str) -> str:
    candidate = str(value or "").strip()
    candidate = re.split(r"[,;.]", candidate, maxsplit=1)[0]
    candidate = re.split(r"\b(?:and|but)\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
    candidate = re.sub(r"\s+", " ", candidate).strip(" '\"")
    return candidate


def _extract_explicit_user_name(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""

    explicit = ""

    match = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{0,80})", text, flags=re.IGNORECASE)
    if match:
        explicit = _clean_person_fragment(match.group(1))

    match = re.search(r"\bi am\s+([A-Za-z][A-Za-z .'-]{0,80})", text, flags=re.IGNORECASE)
    if match:
        candidate = _clean_person_fragment(match.group(1))
        tokens = [tok for tok in candidate.lower().split() if tok]
        role_like = {
            "a",
            "an",
            "the",
            "final",
            "first",
            "second",
            "third",
            "fourth",
            "year",
            "student",
            "engineer",
            "developer",
            "intern",
            "b",
            "btech",
            "cse",
        }
        if tokens and tokens[0] not in role_like and not any(tok in role_like for tok in tokens[1:]):
            explicit = candidate

    # Parse user-identity statements per clause to avoid cross-sentence greedy captures.
    clauses = [part.strip() for part in re.split(r"[.;\n]+", text) if part and part.strip()]
    for clause in clauses:
        relation_match = re.match(
            r"^([A-Za-z][A-Za-z .'-]{0,80}?)\s+is\s+(not\s+)?the\s+user$",
            clause,
            flags=re.IGNORECASE,
        )
        if not relation_match:
            continue

        is_negative = bool(relation_match.group(2))
        candidate = _clean_person_fragment(relation_match.group(1))
        if candidate and not is_negative:
            explicit = candidate

    return explicit


def _is_allowed_fact_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if not lowered:
        return False
    if lowered in _ALLOWED_FACT_KEYS:
        return True
    if lowered in _ROLE_FACT_KEYS:
        return True
    if lowered.startswith("preference_"):
        return True
    return False


def _looks_like_memory_write_command(command: str) -> bool:
    text = (command or "").strip().lower()
    if not text:
        return False

    if _is_memory_recall_query(text):
        return False

    if any(
        marker in text
        for marker in ["remember", "my name is", "i work at", "i work for", "i live in", "i am from", "note that"]
    ):
        return True

    relation_markers = [
        r"\bmy teacher is\b",
        r"\bmy teacher'?s name is\b",
        r"\bmy manager is\b",
        r"\bmy boss is\b",
        r"\bmy doctor is\b",
        r"\bmy friend is\b",
        r"\bis\s+(not\s+)?the\s+user\b",
    ]
    return any(re.search(pattern, text) for pattern in relation_markers)


def _contains_memory_target(command: str) -> bool:
    text = (command or "").strip().lower()
    markers = [
        "my name",
        "my teacher",
        "my manager",
        "my boss",
        "my doctor",
        "my friend",
        "my mentor",
        "my parent",
        "my spouse",
        "my sibling",
        "where i live",
        "my location",
        "where i work",
        "my company",
        "my organization",
        "about me",
        "from memory",
        "remember",
    ]
    return any(marker in text for marker in markers)


def _looks_like_memory_delete_command(command: str) -> bool:
    text = (command or "").strip().lower()
    if not text or _is_memory_recall_query(text):
        return False

    delete_markers = ["forget", "remove", "delete", "erase", "clear", "don't remember", "do not remember", "dont remember"]
    if not any(marker in text for marker in delete_markers):
        return False

    if "memory" in text:
        return True

    return _contains_memory_target(text)


def _looks_like_memory_update_command(command: str) -> bool:
    text = (command or "").strip().lower()
    if not text or _is_memory_recall_query(text):
        return False

    if _looks_like_memory_delete_command(text):
        return False

    if "update" in text and _contains_memory_target(text):
        return True

    explicit_name = _extract_explicit_user_name(command)
    if explicit_name and any(marker in text for marker in ["not ", "actually", "instead", "correction", "i am", "my name is"]):
        return True

    relation_corrections = [
        r"\bmy teacher is\b",
        r"\bmy manager is\b",
        r"\bmy boss is\b",
        r"\bmy doctor is\b",
        r"\bmy friend is\b",
        r"\bi work at\b",
        r"\bi work for\b",
        r"\bi live in\b",
        r"\bi am from\b",
    ]
    if any(re.search(pattern, text) for pattern in relation_corrections):
        return True

    return False


def _memory_action_type(command: str) -> str:
    if _looks_like_memory_delete_command(command):
        return "memory_delete"
    if _looks_like_memory_update_command(command):
        return "memory_update"
    if _looks_like_memory_write_command(command):
        return "memory_write"
    return ""


def _extract_negated_user_names(command: str) -> List[str]:
    text = str(command or "").strip()
    if not text:
        return []

    names: List[str] = []
    for match in re.finditer(r"\b([A-Za-z][A-Za-z .'-]{0,80}?)\s+is\s+not\s+the\s+user\b", text, flags=re.IGNORECASE):
        candidate = _clean_person_fragment(match.group(1))
        if candidate:
            names.append(candidate)

    for match in re.finditer(r"\bnot\s+([A-Za-z][A-Za-z .'-]{0,80}?)\s*,?\s*i\s+am\b", text, flags=re.IGNORECASE):
        candidate = _clean_person_fragment(match.group(1))
        if candidate:
            names.append(candidate)

    deduped: List[str] = []
    for name in names:
        lowered = name.lower()
        if lowered not in [item.lower() for item in deduped]:
            deduped.append(name)
    return deduped


def _dedupe_non_empty(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def extract_memory_operations(command: str) -> Dict[str, List[str]]:
    text = str(command or "").strip()
    low = text.lower()

    operations = {
        "delete_fact_keys": [],
        "delete_relation_roles": [],
        "delete_relation_objects": [],
    }

    if not text:
        return operations

    delete_intent = _looks_like_memory_delete_command(text)
    negated_user_names = _extract_negated_user_names(text)
    if negated_user_names:
        operations["delete_relation_objects"].extend(negated_user_names)

    if delete_intent:
        if any(marker in low for marker in ["my name", "who i am", "identity"]):
            operations["delete_fact_keys"].append("name")

        if any(marker in low for marker in ["where i live", "my location", "my city"]):
            operations["delete_fact_keys"].append("location")
            operations["delete_relation_roles"].append("lives_in")

        if any(marker in low for marker in ["where i work", "my company", "my organization", "work at", "work for"]):
            operations["delete_fact_keys"].extend(["organization", "company"])
            operations["delete_relation_roles"].append("works_at")

        for role, aliases in _MEMORY_ROLE_ALIASES.items():
            if any(f"my {alias}" in low for alias in aliases):
                operations["delete_relation_roles"].append(role)
                operations["delete_fact_keys"].append(f"{role}_name")

        for match in re.finditer(
            r"\b(?:remove|delete|forget|erase)\s+([A-Za-z][A-Za-z .'-]{1,80}?)\s+(?:from|in)\s+memory\b",
            text,
            flags=re.IGNORECASE,
        ):
            candidate = _clean_person_fragment(match.group(1))
            if candidate:
                operations["delete_relation_objects"].append(candidate)

        if any(marker in low for marker in ["everything about me", "all memory about me", "all memories about me"]):
            operations["delete_fact_keys"].extend(sorted(_ALLOWED_FACT_KEYS | _ROLE_FACT_KEYS))
            operations["delete_relation_roles"].extend(sorted(_ALLOWED_RELATIONS))

    operations["delete_fact_keys"] = _dedupe_non_empty(operations["delete_fact_keys"])
    operations["delete_relation_roles"] = _dedupe_non_empty(operations["delete_relation_roles"])
    operations["delete_relation_objects"] = _dedupe_non_empty(operations["delete_relation_objects"])
    return operations


def _looks_like_automation_command(command: str) -> bool:
    text = (command or "").strip().lower()
    if not text:
        return False

    if _is_memory_recall_query(text):
        return False

    if any(
        text.startswith(prefix)
        for prefix in [
            "open ",
            "click ",
            "type ",
            "write ",
            "save ",
            "close ",
            "select ",
            "press ",
            "find ",
            "replace ",
            "new tab",
        ]
    ):
        return True

    if re.search(r"\b(?:in|on)\s+[a-z][a-z0-9 _-]{1,24}$", text):
        return True

    media_followup_markers = (
        "next song",
        "next track",
        "next video",
        "play next",
        "skip song",
        "skip track",
        "skip this",
        "next one",
        "pause",
        "resume",
        "continue playing",
        "resume playback",
    )
    media_hints = ("song", "track", "music", "video", "youtube", "playlist", "playback")
    if any(marker in text for marker in media_followup_markers):
        if any(hint in text for hint in media_hints) or text in {"pause", "resume", "next", "skip", "next one"}:
            return True

    return any(
        phrase in text
        for phrase in [
            "file menu",
            "edit menu",
            "view menu",
            "help menu",
            "save as",
        ]
    )


def _sanitize_steps(raw_steps: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_steps, list):
        return []

    sanitized: List[Dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).strip().upper()
        if action not in {"CLICK", "TYPE", "HOTKEY", "WAIT", "DONE"}:
            continue

        step: Dict[str, Any] = {"action": action}
        if "target" in item:
            step["target"] = str(item.get("target", "")).strip()
        if "text" in item:
            step["text"] = str(item.get("text", ""))
        if "keys" in item:
            step["keys"] = str(item.get("keys", ""))
        if "seconds" in item:
            try:
                step["seconds"] = float(item.get("seconds", 0.2))
            except (TypeError, ValueError):
                step["seconds"] = 0.2

        sanitized.append(step)

    return sanitized


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    codeblock_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if codeblock_match:
        try:
            parsed = json.loads(codeblock_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None

    brace_match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if brace_match:
        try:
            parsed = json.loads(brace_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None

    return None


def _heuristic_plan(command: str) -> List[Dict[str, Any]]:
    command_l = command.lower()

    if is_save_as_intent(command):
        return build_save_as_steps(command, include_payload=True)

    if looks_like_text_entry_intent(command):
        return [
            {"action": "TYPE", "text": _extract_write_payload(command)},
            {"action": "DONE"},
        ]

    if "new tab" in command_l:
        return [{"action": "HOTKEY", "keys": "ctrl+t"}, {"action": "DONE"}]
    if "file menu" in command_l or command_l.strip() == "file":
        return [{"action": "CLICK", "target": "File"}, {"action": "DONE"}]
    if "click one" in command_l:
        return [{"action": "CLICK", "target": "One"}, {"action": "DONE"}]

    return [{"action": "CLICK", "target": command.strip()}, {"action": "DONE"}]


def _extract_write_payload(command: str) -> str:
    return _global_extract_write_payload(command, default="hello from SARA")


def _extract_save_as_filename(command: str) -> str:
    return _global_extract_save_as_filename(command)


def _is_text_entry_command(command: str) -> bool:
    return looks_like_text_entry_intent(command)


def _postprocess_plan(command: str, app_name: str, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not steps:
        return steps

    normalized = [dict(step) for step in steps]

    command_l = (command or "").strip().lower()
    app_l = (app_name or "").strip().lower()

    menu_match = re.search(r"\bopen\s+(file|edit|view|help|format)\s+menu\b", command_l)
    if menu_match:
        menu_name = menu_match.group(1).title()
        logger.info("Plan sanitizer applied standardized menu-open flow menu=%s", menu_name)
        normalized = [
            {"action": "CLICK", "target": menu_name},
            {"action": "DONE"},
        ]

    if _is_text_entry_command(command):
        first_action = str(normalized[0].get("action", "")).strip().upper()
        first_target = str(normalized[0].get("target", "")).strip().lower()
        if first_action == "CLICK" and first_target in {
            "editor",
            "text area",
            "text editor",
            "document area",
            app_l,
            f"{app_l} app",
            f"{app_l} window",
        }:
            logger.info("Plan sanitizer removed brittle leading click target=%s", first_target)
            normalized = normalized[1:]

        has_type = any(str(step.get("action", "")).strip().upper() == "TYPE" for step in normalized)
        if not has_type:
            payload = _extract_write_payload(command)
            normalized.insert(0, {"action": "TYPE", "text": payload})
            logger.info("Plan sanitizer inserted TYPE step for text-entry command")

    if is_save_as_intent(command):
        logger.info("Plan sanitizer applied standardized Save As flow")
        normalized = build_save_as_steps(command, include_payload=True)

    if normalized and str(normalized[-1].get("action", "")).strip().upper() != "DONE":
        normalized.append({"action": "DONE"})

    return normalized


def get_command_understanding(command: str, memory_context: str = "") -> Dict[str, Any]:
    text = (command or "").strip()
    if not text:
        return _heuristic_command_understanding(text)

    try:
        response = get_client().call(
            prompt=build_command_understanding_prompt(text, memory_context),
            system=SYSTEM_PROMPT_COMMAND_UNDERSTANDING,
            temperature=0.0,
            max_tokens=220,
            prefer_provider=LLM_SIMPLE_PROVIDER,
            task_complexity="simple",
        )
        if response and not response.error:
            payload = _extract_json(str(response.text or ""))
            if isinstance(payload, dict):
                normalized = _normalize_command_understanding(payload, text)
                if normalized:
                    return normalized
    except Exception:
        pass

    return _heuristic_command_understanding(text)


def _normalize_command_understanding(payload: Dict[str, Any], command: str) -> Dict[str, Any]:
    intent = str(payload.get("intent", "")).strip().lower()
    if intent not in _ALLOWED_INTENTS:
        return {}

    if _is_memory_recall_query(command):
        intent = "conversation"
        action_type = "memory_read"
        confidence_raw = payload.get("confidence", 0.75)
        try:
            confidence = float(confidence_raw)
        except Exception:
            confidence = 0.75
        confidence = max(0.0, min(1.0, confidence))
        return {
            "intent": intent,
            "action_type": action_type,
            "requires_db_lookup": True,
            "requires_execution": False,
            "confidence": confidence,
        }

    action_type = str(payload.get("action_type", "")).strip().lower()

    # Protect imperative UI commands from LLM misclassification.
    if _looks_like_automation_command(command):
        intent = "automation"
        action_type = "automation"

    # Protect personal-memory mutations from classification drift.
    memory_action = _memory_action_type(command)
    if memory_action:
        intent = "remember"
        action_type = memory_action

    if action_type not in _ALLOWED_ACTION_TYPES:
        action_type = _default_action_type(intent, command)

    confidence_raw = payload.get("confidence", 0.7)
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    requires_db_lookup = payload.get("requires_db_lookup", action_type == "memory_read")
    requires_execution = payload.get("requires_execution", intent == "automation")

    return {
        "intent": intent,
        "action_type": action_type,
        "requires_db_lookup": bool(requires_db_lookup),
        "requires_execution": bool(requires_execution),
        "confidence": confidence,
    }


def _default_action_type(intent: str, command: str) -> str:
    if intent == "automation":
        return "automation"
    if intent == "remember":
        return _memory_action_type(command) or "memory_write"
    if intent == "screen_read":
        return "qa"

    if _is_memory_recall_query(command):
        return "memory_read"

    text = (command or "").lower()
    if any(phrase in text for phrase in ["what did i", "what do you remember", "recall", "from memory"]):
        return "memory_read"
    if "?" in text or text.startswith(("what", "why", "how", "when", "where", "who")):
        return "qa"
    return "conversation"


def get_intent(command: str, memory_context: str = "", use_local: bool = False) -> Dict[str, Any]:
    """Backward-compatible wrapper around unified command understanding."""
    text = (command or "").strip()
    if use_local:
        heuristic = _heuristic_command_understanding(text)
        return {"intent": heuristic["intent"], "confidence": heuristic["confidence"]}

    understanding = get_command_understanding(text, memory_context=memory_context)
    return {
        "intent": understanding.get("intent", "conversation"),
        "confidence": float(understanding.get("confidence", 0.6)),
    }


def _heuristic_command_understanding(command: str) -> Dict[str, Any]:
    c = command.lower()
    if _is_memory_recall_query(c):
        return {
            "intent": "conversation",
            "action_type": "memory_read",
            "requires_db_lookup": True,
            "requires_execution": False,
            "confidence": 0.8,
        }

    memory_action = _memory_action_type(c)
    if memory_action or any(x in c for x in ["i am"]):
        return {
            "intent": "remember",
            "action_type": memory_action or "memory_update",
            "requires_db_lookup": False,
            "requires_execution": False,
            "confidence": 0.85,
        }
    if any(x in c for x in ["screen", "what do you see", "read this"]):
        return {
            "intent": "screen_read",
            "action_type": "qa",
            "requires_db_lookup": False,
            "requires_execution": False,
            "confidence": 0.8,
        }
    if any(x in c for x in ["open", "click", "save", "file", "tab", "menu", "type", "write", "enter"]):
        return {
            "intent": "automation",
            "action_type": "automation",
            "requires_db_lookup": False,
            "requires_execution": True,
            "confidence": 0.8,
        }

    action_type = _default_action_type("conversation", command)
    return {
        "intent": "conversation",
        "action_type": action_type,
        "requires_db_lookup": action_type == "memory_read",
        "requires_execution": False,
        "confidence": 0.6,
    }


def _is_memory_recall_query(command: str) -> bool:
    text = (command or "").strip().lower()
    if not text:
        return False

    recall_markers = [
        "what do you remember",
        "what did i",
        "recall",
        "what do you remember from memory",
        "do you remember me",
        "tell me what you know about me",
        "what is my name",
        "what was my name",
        "who am i",
        "where do i work",
        "where do i live",
        "what is my",
        "what was my",
        "do you know my",
    ]
    return any(marker in text for marker in recall_markers)


def extract_facts(command: str) -> Dict[str, Any]:
    text = (command or "").strip()
    if not text:
        return {}

    heuristic = _heuristic_extract_facts(text)

    try:
        response = get_client().call(
            prompt=build_facts_prompt(text),
            system=SYSTEM_PROMPT_FACTS,
            temperature=0.0,
            max_tokens=200,
            prefer_provider=LLM_SIMPLE_PROVIDER,
            task_complexity="simple",
        )
        if response and not response.error:
            payload = _extract_json(str(response.text or ""))
            if isinstance(payload, dict):
                merged = dict(heuristic)
                for key, value in payload.items():
                    if isinstance(key, str) and key:
                        merged[key] = value
                return _sanitize_extracted_facts(text, merged)
    except Exception:
        pass

    return _sanitize_extracted_facts(text, heuristic)


def _heuristic_extract_facts(command: str) -> Dict[str, Any]:
    text = command.strip()
    low = text.lower()
    facts: Dict[str, Any] = {}

    explicit_user_name = _extract_explicit_user_name(text)
    if explicit_user_name:
        facts["name"] = explicit_user_name

    marker = "my name is "
    if marker in low:
        idx = low.find(marker) + len(marker)
        name = _clean_person_fragment(text[idx:])
        if name:
            facts["name"] = name

    marker = "i work at "
    if marker in low:
        idx = low.find(marker) + len(marker)
        org = text[idx:].strip().strip(".")
        if org:
            facts["organization"] = org

    marker = "i work for "
    if marker in low:
        idx = low.find(marker) + len(marker)
        org = text[idx:].strip().strip(".")
        if org:
            facts["organization"] = org

    marker = "i live in "
    if marker in low:
        idx = low.find(marker) + len(marker)
        location = text[idx:].strip().strip(".")
        if location:
            facts["location"] = location

    marker = "i am from "
    if marker in low:
        idx = low.find(marker) + len(marker)
        location = text[idx:].strip().strip(".")
        if location:
            facts["location"] = location

    return facts


def _sanitize_extracted_facts(command: str, facts: Dict[str, Any]) -> Dict[str, Any]:
    text = (command or "").strip().lower()
    out: Dict[str, Any] = dict(facts or {})

    for key in list(out.keys()):
        if not _is_allowed_fact_key(key):
            out.pop(key, None)

    explicit_user_name = _extract_explicit_user_name(command)
    if explicit_user_name:
        out["name"] = explicit_user_name

    if "name" in out:
        if not explicit_user_name:
            out.pop("name", None)

    if "organization" in out:
        if "i work at" not in text and "i work for" not in text:
            out.pop("organization", None)
        elif not _value_present_in_text(out.get("organization", ""), command):
            out.pop("organization", None)

    if "company" in out:
        if "i work at" not in text and "i work for" not in text:
            out.pop("company", None)
        elif not _value_present_in_text(out.get("company", ""), command):
            out.pop("company", None)

    if "location" in out:
        if "i live in" not in text and "i am from" not in text:
            out.pop("location", None)
        elif not _value_present_in_text(out.get("location", ""), command):
            out.pop("location", None)

    if "education" in out and not _value_present_in_text(out.get("education", ""), command):
        out.pop("education", None)

    if "education_level" in out and not _value_present_in_text(out.get("education_level", ""), command):
        out.pop("education_level", None)

    for key in list(out.keys()):
        if key in _ROLE_FACT_KEYS and not _value_present_in_text(out.get(key, ""), command):
            out.pop(key, None)

    return out


def extract_memory_graph(command: str) -> Dict[str, Any]:
    text = (command or "").strip()
    if not text:
        return {"relations": []}

    heuristic = _heuristic_extract_memory_graph(text)

    try:
        response = get_client().call(
            prompt=build_graph_memory_prompt(text),
            system=SYSTEM_PROMPT_GRAPH_MEMORY,
            temperature=0.0,
            max_tokens=320,
            prefer_provider=LLM_SIMPLE_PROVIDER,
            task_complexity="simple",
        )
        if response and not response.error:
            payload = _extract_json(str(response.text or ""))
            if isinstance(payload, dict):
                relations = payload.get("relations", [])
                if isinstance(relations, list):
                    merged = _merge_relations(heuristic.get("relations", []), relations, source_text=text)
                    return {"relations": merged}
    except Exception:
        pass

    return heuristic


def _heuristic_extract_memory_graph(command: str) -> Dict[str, Any]:
    text = str(command or "").strip()
    low = text.lower()
    relations: List[Dict[str, str]] = []

    patterns = {
        "teacher": [r"\bmy teacher is\s+([A-Za-z][A-Za-z .'-]{1,80})", r"\bmy teacher'?s name is\s+([A-Za-z][A-Za-z .'-]{1,80})"],
        "manager": [r"\bmy manager is\s+([A-Za-z][A-Za-z .'-]{1,80})", r"\bmy boss is\s+([A-Za-z][A-Za-z .'-]{1,80})"],
        "friend": [r"\bmy friend is\s+([A-Za-z][A-Za-z .'-]{1,80})"],
        "doctor": [r"\bmy doctor is\s+([A-Za-z][A-Za-z .'-]{1,80})"],
    }

    for relation, regexes in patterns.items():
        for pattern in regexes:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip().strip(".,")
                if name:
                    relations.append(
                        {
                            "subject": "user",
                            "subject_type": "Person",
                            "relation": relation,
                            "object": name,
                            "object_type": "Person",
                        }
                    )

    works_match = re.search(r"\bi work at\s+(.+)$", text, flags=re.IGNORECASE)
    if works_match:
        org = works_match.group(1).strip().strip(".,")
        if org:
            relations.append(
                {
                    "subject": "user",
                    "subject_type": "Person",
                    "relation": "works_at",
                    "object": org,
                    "object_type": "Org",
                }
            )

    works_for_match = re.search(r"\bi work for\s+(.+)$", text, flags=re.IGNORECASE)
    if works_for_match:
        org = works_for_match.group(1).strip().strip(".,")
        if org:
            relations.append(
                {
                    "subject": "user",
                    "subject_type": "Person",
                    "relation": "works_at",
                    "object": org,
                    "object_type": "Org",
                }
            )

    lives_match = re.search(r"\bi live in\s+(.+)$", text, flags=re.IGNORECASE)
    if lives_match:
        place = lives_match.group(1).strip().strip(".,")
        if place:
            relations.append(
                {
                    "subject": "user",
                    "subject_type": "Person",
                    "relation": "lives_in",
                    "object": place,
                    "object_type": "Place",
                }
            )

    from_match = re.search(r"\bi am from\s+(.+)$", text, flags=re.IGNORECASE)
    if from_match:
        place = from_match.group(1).strip().strip(".,")
        if place:
            relations.append(
                {
                    "subject": "user",
                    "subject_type": "Person",
                    "relation": "lives_in",
                    "object": place,
                    "object_type": "Place",
                }
            )

    if "teacher" in low and "my" in low and not relations:
        # Preserve role cue even if entity is missing in this utterance.
        relations.append(
            {
                "subject": "user",
                "subject_type": "Person",
                "relation": "teacher",
                "object": "",
                "object_type": "Person",
            }
        )

    # Drop incomplete relation placeholders from final output.
    clean = [rel for rel in relations if str(rel.get("object", "")).strip()]
    return {"relations": clean}


def _merge_relations(
    base: List[Dict[str, Any]],
    incoming: List[Dict[str, Any]],
    source_text: str = "",
) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    source_norm = _normalize_match_text(source_text)

    for rel in [*(base or []), *(incoming or [])]:
        if not isinstance(rel, dict):
            continue
        subject_raw = str(rel.get("subject", "user")).strip() or "user"
        subject_l = subject_raw.lower()
        if subject_l in {"user", "me", "myself", "i", "my"}:
            subject = "user"
        else:
            subject = subject_raw
        subject_type = str(rel.get("subject_type", "Person")).strip() or "Person"
        relation = str(rel.get("relation", "")).strip().lower().replace(" ", "_")
        obj = str(rel.get("object", "")).strip()
        object_type = str(rel.get("object_type", "Person")).strip() or "Person"
        if not relation or not obj:
            continue
        if relation not in _ALLOWED_RELATIONS:
            continue
        if obj.lower() == "user":
            continue
        if source_norm and not _value_present_in_text(obj, source_text):
            continue
        if subject != "user" and source_norm and not _value_present_in_text(subject, source_text):
            continue
        normalized = {
            "subject": subject,
            "subject_type": subject_type,
            "relation": relation,
            "object": obj,
            "object_type": object_type,
        }
        if normalized not in merged:
            merged.append(normalized)
    return merged


def get_conversational_response(command: str, context: str = "") -> str:
    try:
        response = get_client().call(
            prompt=build_conversation_prompt(command, context),
            system=SYSTEM_PROMPT_CONVERSATION,
            temperature=0.3,
            max_tokens=400,
            prefer_provider=LLM_SIMPLE_PROVIDER,
            task_complexity="simple",
        )
        if response and not response.error and (response.text or "").strip():
            return str(response.text).strip()
    except Exception:
        pass

    return "I can help automate desktop tasks, remember preferences, and guide app workflows."


def _sanitize_iterative_action_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    action_obj = payload.get("action", payload)
    if not isinstance(action_obj, dict):
        return {}

    action_type = str(action_obj.get("action") or action_obj.get("action_type") or "").strip().upper()
    if action_type not in _ALLOWED_ITERATIVE_ACTIONS:
        return {}

    out: Dict[str, Any] = {"action": action_type}
    thought = str(payload.get("thought", "")).strip()
    if thought:
        out["thought"] = thought

    reason = str(action_obj.get("reason") or payload.get("reason") or "").strip()

    if action_type == "CLICK":
        target = str(action_obj.get("target", "")).strip()
        if not target:
            return {}
        out["target"] = target
    elif action_type == "TYPE":
        text = str(action_obj.get("text", ""))
        if not text:
            return {}
        out["text"] = text
    elif action_type == "HOTKEY":
        keys = str(action_obj.get("keys", "")).strip()
        if not keys:
            return {}
        out["keys"] = keys
    elif action_type == "WAIT":
        seconds_raw = action_obj.get("seconds", 0.5)
        try:
            seconds = float(seconds_raw)
        except (TypeError, ValueError):
            seconds = 0.5
        out["seconds"] = max(0.1, min(3.0, seconds))

    if action_type in {"DONE", "FAIL"} and reason:
        out["reason"] = reason

    return out


def _heuristic_next_action(command: str, app_name: str, step_index: int) -> Dict[str, Any]:
    seed = _postprocess_plan(command, app_name, _heuristic_plan(command))
    idx = max(0, int(step_index) - 1)
    if idx < len(seed):
        return dict(seed[idx])
    return {"action": "DONE", "reason": "Heuristic completion"}


def get_next_automation_action(
    command: str,
    app_name: str,
    ui_summary: str = "",
    runtime_ui_snapshot: str = "",
    memory_context: str = "",
    planning_bias: str = "",
    step_index: int = 1,
    consecutive_failures: int = 0,
    recent_observations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    observations = [str(item).strip() for item in (recent_observations or []) if str(item).strip()]
    obs_text = "\n".join(f"- {item}" for item in observations[-8:])

    try:
        response = get_client().call(
            prompt=build_iterative_action_prompt(
                command=command,
                app_name=app_name,
                ui_summary=ui_summary,
                runtime_ui_snapshot=runtime_ui_snapshot,
                memory_context=memory_context,
                planning_bias=planning_bias,
                step_index=step_index,
                consecutive_failures=consecutive_failures,
                recent_observations=obs_text,
            ),
            system=SYSTEM_PROMPT_ITERATIVE_ACTION,
            temperature=0.1,
            max_tokens=380,
            prefer_provider=LLM_COMPLEX_PROVIDER,
            task_complexity="complex",
        )
        if response and not response.error:
            payload = _extract_json(str(response.text or ""))
            if isinstance(payload, dict):
                action = _sanitize_iterative_action_payload(payload)
                if action:
                    logger.info(
                        "Iterative action generated app=%s step=%s action=%s",
                        app_name,
                        step_index,
                        action.get("action"),
                    )
                    return action
    except Exception:
        pass

    heuristic = _heuristic_next_action(command, app_name, step_index)
    logger.info(
        "Iterative action generated via heuristic app=%s step=%s action=%s",
        app_name,
        step_index,
        heuristic.get("action"),
    )
    return heuristic


def get_automation_plan(
    command: str,
    app_name: str = "Unknown",
    failure_context: str = "",
    active_app: Optional[str] = None,
    ui_summary: str = "",
    context: str = "",
    planning_bias: str = "",
) -> List[Dict[str, Any]]:
    resolved_app = active_app or app_name

    try:
        client = get_client()
        response = client.call(
            prompt=build_plan_prompt(
                command=command,
                app_name=resolved_app,
                ui_summary=ui_summary,
                memory_context=context,
                failure_context=failure_context,
                planning_bias=planning_bias,
            ),
            system=SYSTEM_PROMPT_PLAN,
            temperature=0.1,
            max_tokens=700,
            prefer_provider=LLM_COMPLEX_PROVIDER,
            task_complexity="complex",
        )
        if response and not response.error:
            payload = _extract_json(str(response.text or ""))
            if payload:
                steps = _sanitize_steps(payload.get("steps"))
                if steps:
                    postprocessed = _postprocess_plan(command, resolved_app, steps)
                    logger.info(
                        "Automation plan generated via LLM app=%s steps=%d postprocessed_steps=%d",
                        resolved_app,
                        len(steps),
                        len(postprocessed),
                    )
                    return postprocessed
    except Exception:
        pass

    heuristic = _heuristic_plan(command)
    postprocessed = _postprocess_plan(command, resolved_app, heuristic)
    logger.info(
        "Automation plan generated via heuristic app=%s steps=%d postprocessed_steps=%d",
        resolved_app,
        len(heuristic),
        len(postprocessed),
    )
    return postprocessed
