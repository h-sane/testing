"""Central runtime settings for SARA.

This module keeps compatibility with the existing Layer 1 execution stack
while exposing broader configuration used by the full demo application.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
	from dotenv import load_dotenv

	load_dotenv()
except Exception:
	pass

# Project paths
ROOT_DIR = Path(__file__).resolve().parents[1]
SARA_MEMORY_DIR = ROOT_DIR / "sara_memory"
FACTS_FILE = SARA_MEMORY_DIR / "facts.json"
CHROMA_DIR = SARA_MEMORY_DIR / "chroma"
PROFILE_FILE = SARA_MEMORY_DIR / "profile.json"

# Execution defaults (existing Layer 1 compatibility)
DEFAULT_USE_VISION = False
MAX_PLAN_STEPS = 12
MAX_REPLAN_ROUNDS = 1
STEP_RETRY_LIMIT = 1
PROTECTED_APPS = {"VSCode"}

# Iterative automation runtime (LLM proposes one action per turn)
ENABLE_ITERATIVE_AUTOMATION = os.getenv("SARA_ENABLE_ITERATIVE_AUTOMATION", "1").strip().lower() in {
	"1",
	"true",
	"yes",
	"on",
}
ITERATIVE_MAX_STEPS = int(os.getenv("SARA_ITERATIVE_MAX_STEPS", "20"))
ITERATIVE_MAX_CONSECUTIVE_FAILURES = int(os.getenv("SARA_ITERATIVE_MAX_CONSECUTIVE_FAILURES", "3"))
ITERATIVE_AX_SNAPSHOT_LIMIT = int(os.getenv("SARA_ITERATIVE_AX_SNAPSHOT_LIMIT", "120"))

# Safety and policy
HIGH_RISK_KEYWORDS = [
	"delete",
	"remove",
	"erase",
	"format",
	"reset",
	"uninstall",
	"install",
	"shutdown",
	"reboot",
	"purchase",
	"payment",
	"transfer",
	"send",
	"submit",
	"overwrite",
]
REQUIRE_APPROVAL_FOR_RISKY = os.getenv("SARA_REQUIRE_APPROVAL_FOR_RISKY", "1").strip().lower() in {
	"1",
	"true",
	"yes",
	"on",
}
AUTOMATION_CONFIDENCE_THRESHOLD = float(
	os.getenv("SARA_AUTOMATION_CONFIDENCE_THRESHOLD", "0.6").strip() or "0.6"
)

# App support
SUPPORTED_APPS = [
	"Notepad",
	"Calculator",
	"Excel",
	"Chrome",
	"Brave",
	"Spotify",
]

# Privacy routing
SENSITIVE_KEYWORDS = [
	"password",
	"bank",
	"medical",
	"confidential",
	"private",
	"ssn",
	"social security",
	"credit card",
	"pin",
	"token",
	"api key",
	"login",
]

# Voice
WAKE_WORD = os.getenv("SARA_WAKE_WORD", "hey sara")
DISABLE_VOICE_INPUT = os.getenv("SARA_DISABLE_VOICE_INPUT", "0").strip().lower() in {
	"1",
	"true",
	"yes",
	"on",
}
# Backward-compatibility alias for legacy imports.
VOICE_TEXT_MODE = DISABLE_VOICE_INPUT
ENABLE_WAKE_LOOP = os.getenv("SARA_ENABLE_WAKE_LOOP", "1").strip().lower() in {
	"1",
	"true",
	"yes",
	"on",
}
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "").strip()
DEEPGRAM_STT_MODEL = os.getenv("SARA_DEEPGRAM_STT_MODEL", "nova-2")
DEEPGRAM_STT_LANGUAGE = os.getenv("SARA_DEEPGRAM_STT_LANGUAGE", "en")
DEEPGRAM_TTS_MODEL = os.getenv("SARA_DEEPGRAM_TTS_MODEL", "aura-2-thalia-en")
DEEPGRAM_TTS_SAMPLE_RATE = int(os.getenv("SARA_DEEPGRAM_TTS_SAMPLE_RATE", "48000"))
SARA_FORCE_FEMALE_TTS = os.getenv("SARA_FORCE_FEMALE_TTS", "1").strip().lower() in {
	"1",
	"true",
	"yes",
	"on",
}
SARA_FEMALE_TTS_MODEL = os.getenv("SARA_FEMALE_TTS_MODEL", "aura-2-thalia-en").strip()
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "").strip()
SARA_WAKE_WORD_PATH = os.getenv(
	"SARA_WAKE_WORD_PATH",
	str(ROOT_DIR / "Hey-SARA_en_windows_v3_0_0.ppn"),
).strip()
SARA_WAKE_SENSITIVITY = float(os.getenv("SARA_WAKE_SENSITIVITY", "0.6").strip() or "0.6")
SARA_VOICE_LISTEN_TIMEOUT_SEC = float(os.getenv("SARA_VOICE_LISTEN_TIMEOUT_SEC", "6.0").strip() or "6.0")
SARA_VOICE_PHRASE_TIME_LIMIT_SEC = float(
	os.getenv("SARA_VOICE_PHRASE_TIME_LIMIT_SEC", "12.0").strip() or "12.0"
)

# Local API
LOCAL_API_HOST = os.getenv("SARA_LOCAL_API_HOST", "127.0.0.1")
LOCAL_API_PORT = int(os.getenv("SARA_LOCAL_API_PORT", "8765"))

# Memory
MEMORY_RECALL_K = int(os.getenv("SARA_MEMORY_RECALL_K", "2"))
SARA_ENABLE_GRAPH_MEMORY = os.getenv("SARA_ENABLE_GRAPH_MEMORY", "1").strip().lower() in {
	"1",
	"true",
	"yes",
	"on",
}
SARA_NEO4J_URI = os.getenv("SARA_NEO4J_URI", "").strip()
SARA_NEO4J_USER = os.getenv("SARA_NEO4J_USER", "neo4j").strip()
SARA_NEO4J_PASSWORD = os.getenv("SARA_NEO4J_PASSWORD", "").strip()
SARA_NEO4J_DATABASE = os.getenv("SARA_NEO4J_DATABASE", "neo4j").strip()
SARA_MEMORY_USER_ID = os.getenv("SARA_MEMORY_USER_ID", "local-user").strip() or "local-user"


def validate_config() -> dict:
	"""Return quick runtime config status used by CLI/UI status panels."""
	return {
		"root": str(ROOT_DIR),
		"facts_file": str(FACTS_FILE),
		"chroma_dir": str(CHROMA_DIR),
		"profile_file": str(PROFILE_FILE),
		"default_use_vision": DEFAULT_USE_VISION,
		"enable_iterative_automation": ENABLE_ITERATIVE_AUTOMATION,
		"iterative_max_steps": ITERATIVE_MAX_STEPS,
		"iterative_max_consecutive_failures": ITERATIVE_MAX_CONSECUTIVE_FAILURES,
		"iterative_ax_snapshot_limit": ITERATIVE_AX_SNAPSHOT_LIMIT,
		"wake_word": WAKE_WORD,
		"disable_voice_input": DISABLE_VOICE_INPUT,
		"deepgram_configured": bool(DEEPGRAM_API_KEY),
		"deepgram_stt_model": DEEPGRAM_STT_MODEL,
		"deepgram_tts_model": DEEPGRAM_TTS_MODEL,
		"deepgram_tts_sample_rate": DEEPGRAM_TTS_SAMPLE_RATE,
		"force_female_tts": SARA_FORCE_FEMALE_TTS,
		"female_tts_model": SARA_FEMALE_TTS_MODEL,
		"wake_word_path": SARA_WAKE_WORD_PATH,
		"picovoice_configured": bool(PICOVOICE_ACCESS_KEY),
		"require_approval_for_risky": REQUIRE_APPROVAL_FOR_RISKY,
		"automation_confidence_threshold": AUTOMATION_CONFIDENCE_THRESHOLD,
		"enable_wake_loop": ENABLE_WAKE_LOOP,
		"local_api_host": LOCAL_API_HOST,
		"local_api_port": LOCAL_API_PORT,
		"graph_memory_enabled": SARA_ENABLE_GRAPH_MEMORY,
		"neo4j_uri_set": bool(SARA_NEO4J_URI),
		"neo4j_user_set": bool(SARA_NEO4J_USER),
		"neo4j_password_set": bool(SARA_NEO4J_PASSWORD),
		"neo4j_database": SARA_NEO4J_DATABASE,
		"memory_user_id": SARA_MEMORY_USER_ID,
	}
