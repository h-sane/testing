# src/llm/llm_client.py
"""
LLM Client with multi-provider key rotation.
Supports Gemini (google-genai), Claude (anthropic), NVIDIA NIM,
and AWS Bedrock (bearer-auth converse API)
OpenAI-compatible chat completions with automatic fallback.

Model identifiers (as of Feb 2026):
  Gemini:  gemini-2.5-flash, gemini-2.0-flash
  Claude:  claude-sonnet-4-20250514, claude-3-5-sonnet-20241022
    NVIDIA:  google/gemma-4-31b-it
    Bedrock: us.anthropic.claude-sonnet-4-6 (complex), amazon.nova-micro-v1:0 (simple)
"""

import os
import sys
import time
import json
import logging
import importlib
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger("llm_client")

# =============================================================================
# KEY POOL
# =============================================================================

@dataclass
class KeySlot:
    """Tracks a single API key's health and rate-limit state."""
    key: str
    provider: str  # "gemini", "claude", "nvidia", or "bedrock"
    calls_made: int = 0
    last_call_ts: float = 0.0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    
    @property
    def is_available(self) -> bool:
        return time.time() >= self.cooldown_until and self.consecutive_failures < 5


class KeyPool:
    """Round-robin key pool with rate-limit awareness."""
    
    def __init__(self):
        self.gemini_keys: List[KeySlot] = []
        self.claude_keys: List[KeySlot] = []
        self.nvidia_keys: List[KeySlot] = []
        self.bedrock_keys: List[KeySlot] = []
        self._gemini_idx = 0
        self._claude_idx = 0
        self._nvidia_idx = 0
        self._bedrock_idx = 0
        self._load_keys()
    
    def _load_keys(self):
        """Load keys from env vars."""
        # Gemini keys
        for i in range(1, 4):
            key = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
            if key:
                self.gemini_keys.append(KeySlot(key=key, provider="gemini"))
        
        # Fallback to single legacy key
        if not self.gemini_keys:
            legacy = os.getenv("GEMINI_API_KEY", "").strip()
            if legacy:
                self.gemini_keys.append(KeySlot(key=legacy, provider="gemini"))
        
        # Claude keys
        for i in range(1, 4):
            key = os.getenv(f"CLAUDE_API_KEY_{i}", "").strip()
            if key:
                self.claude_keys.append(KeySlot(key=key, provider="claude"))

        # NVIDIA keys
        nvidia_key_names = [
            "NVIDIA_API_KEY_1",
            "NVIDIA_API_KEY_2",
            "NVIDIA_API_KEY_3",
            "NVIDIA_API_KEY",
            "NVAPI_KEY",
        ]
        seen_nvidia = set()
        for key_name in nvidia_key_names:
            key = os.getenv(key_name, "").strip()
            if key and key not in seen_nvidia:
                self.nvidia_keys.append(KeySlot(key=key, provider="nvidia"))
                seen_nvidia.add(key)

        # Bedrock bearer tokens
        bedrock_token_names = [
            "AWS_BEARER_TOKEN_BEDROCK_1",
            "AWS_BEARER_TOKEN_BEDROCK_2",
            "AWS_BEARER_TOKEN_BEDROCK_3",
            "AWS_BEARER_TOKEN_BEDROCK",
        ]
        seen_bedrock = set()
        for key_name in bedrock_token_names:
            key = os.getenv(key_name, "").strip()
            if key and key not in seen_bedrock:
                self.bedrock_keys.append(KeySlot(key=key, provider="bedrock"))
                seen_bedrock.add(key)
        
        logger.info(
            f"Key pool: {len(self.gemini_keys)} Gemini, "
            f"{len(self.claude_keys)} Claude, "
            f"{len(self.nvidia_keys)} NVIDIA, "
            f"{len(self.bedrock_keys)} Bedrock keys loaded"
        )
    
    def next_gemini(self) -> Optional[KeySlot]:
        """Get next available Gemini key (round-robin)."""
        return self._next(self.gemini_keys, "_gemini_idx")
    
    def next_claude(self) -> Optional[KeySlot]:
        """Get next available Claude key (round-robin)."""
        return self._next(self.claude_keys, "_claude_idx")

    def next_nvidia(self) -> Optional[KeySlot]:
        """Get next available NVIDIA key (round-robin)."""
        return self._next(self.nvidia_keys, "_nvidia_idx")

    def next_bedrock(self) -> Optional[KeySlot]:
        """Get next available Bedrock bearer token (round-robin)."""
        return self._next(self.bedrock_keys, "_bedrock_idx")
    
    def _next(self, keys: List[KeySlot], idx_attr: str) -> Optional[KeySlot]:
        if not keys:
            return None
        start = getattr(self, idx_attr)
        for i in range(len(keys)):
            slot = keys[(start + i) % len(keys)]
            if slot.is_available:
                setattr(self, idx_attr, (start + i + 1) % len(keys))
                return slot
        return None
    
    def mark_success(self, slot: KeySlot):
        slot.calls_made += 1
        slot.last_call_ts = time.time()
        slot.consecutive_failures = 0
    
    def mark_failure(
        self,
        slot: KeySlot,
        is_rate_limit: bool = False,
        cooldown_seconds: Optional[int] = None,
    ):
        slot.consecutive_failures += 1
        if cooldown_seconds is not None and cooldown_seconds > 0:
            slot.cooldown_until = time.time() + cooldown_seconds
        elif is_rate_limit:
            slot.cooldown_until = time.time() + 60  # 60s cooldown on rate limit


# =============================================================================
# LLM CLIENT
# =============================================================================

# Gemini models in priority order
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]
# Claude models in priority order
CLAUDE_MODELS = ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022"]
# NVIDIA models in priority order (OpenAI-compatible NIM endpoint)
NVIDIA_MODELS = [os.getenv("NVIDIA_MODEL", "google/gemma-4-31b-it").strip() or "google/gemma-4-31b-it"]


def _dedupe_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        value = (item or "").strip()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _parse_env_model_list(var_name: str) -> List[str]:
    raw = os.getenv(var_name, "").strip()
    if not raw:
        return []
    return _dedupe_keep_order([part.strip() for part in raw.split(",") if part.strip()])


BEDROCK_REGION = os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1"
BEDROCK_COMPLEX_MODELS = _parse_env_model_list("BEDROCK_COMPLEX_MODELS")
if not BEDROCK_COMPLEX_MODELS:
    BEDROCK_COMPLEX_MODELS = _dedupe_keep_order(
        [
            os.getenv("BEDROCK_MODEL_COMPLEX", "").strip() or "amazon.nova-lite-v1:0",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "amazon.nova-pro-v1:0",
        ]
    )

BEDROCK_SIMPLE_MODELS = _parse_env_model_list("BEDROCK_SIMPLE_MODELS")
if not BEDROCK_SIMPLE_MODELS:
    BEDROCK_SIMPLE_MODELS = _dedupe_keep_order(
        [
            os.getenv("BEDROCK_MODEL_SIMPLE", "").strip() or "amazon.nova-lite-v1:0",
            "amazon.nova-micro-v1:0",
            "amazon.nova-pro-v1:0",
        ]
    )


@dataclass
class LLMResponse:
    """Structured response from LLM."""
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None


class LLMClient:
    """
    Multi-provider LLM client with automatic rotation and fallback.
    
    Priority: Bedrock -> Gemini -> Claude -> NVIDIA.
    Falls back across providers when rate-limited.
    """
    
    def __init__(self):
        self.pool = KeyPool()
        self._gemini_client = None
        self._claude_client = None
        self._anthropic_module = None
        self._anthropic_import_checked = False
        self._anthropic_available = False
        self._claude_billing_blocked_until = 0.0
        self._bedrock_model_blocked_until: Dict[str, float] = {}
        self.strict_preferred_default = (
            os.getenv("LLM_STRICT_PREFERRED_PROVIDER", "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )

    def _sanitize_prompt_payloads(self, prompt: str, system: str) -> tuple[str, str]:
        """Sanitize prompt/system text before any cloud-provider call."""
        try:
            from sara.privacy import sanitize_sensitive_text

            prompt_result = sanitize_sensitive_text(prompt)
            system_result = sanitize_sensitive_text(system) if system else None

            total_redactions = prompt_result.redaction_count + (
                system_result.redaction_count if system_result else 0
            )
            if total_redactions > 0:
                logger.info(
                    "[llm_client] Privacy sanitizer redacted %s sensitive span(s) before cloud call",
                    total_redactions,
                )

            return (
                prompt_result.sanitized_text,
                system_result.sanitized_text if system_result else system,
            )
        except Exception as exc:
            logger.warning("[llm_client] Privacy sanitizer unavailable, using original payloads: %s", exc)
            return prompt, system

    def _ensure_anthropic(self) -> bool:
        if self._anthropic_import_checked:
            return self._anthropic_available

        self._anthropic_import_checked = True
        try:
            self._anthropic_module = importlib.import_module("anthropic")
            self._anthropic_available = True
        except Exception:
            self._anthropic_available = False
            logger.info("[llm_client] anthropic package unavailable; Claude provider disabled")

        return self._anthropic_available
    
    def call(
        self, 
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        prefer_provider: str = "bedrock",
        strict_preferred: Optional[bool] = None,
        task_complexity: str = "auto",
    ) -> LLMResponse:
        """
        Call LLM with automatic provider rotation.
        Tries preferred provider first, falls back to alternate.
        
        Args:
            prompt: User prompt
            system: System prompt
            max_tokens: Max output tokens
            temperature: Sampling temperature
            prefer_provider: "bedrock", "gemini", "claude", or "nvidia"
            strict_preferred: If True, only the preferred provider is allowed;
                no fallback to other providers.
            task_complexity: "simple", "complex", or "auto". Used by Bedrock
                routing to choose cost-effective vs heavyweight models.
        
        Returns:
            LLMResponse with text and metadata
        """
        prompt = str(prompt or "")
        system = str(system or "")
        prompt, system = self._sanitize_prompt_payloads(prompt, system)

        prefer_provider = (prefer_provider or "bedrock").strip().lower()
        complexity = (task_complexity or "auto").strip().lower()
        if complexity not in {"auto", "simple", "complex"}:
            complexity = "auto"

        provider_map = {
            "bedrock": lambda p, s, m, t: self._call_bedrock(p, s, m, t, complexity),
            "gemini": self._call_gemini,
            "claude": self._call_claude,
            "nvidia": self._call_nvidia,
        }
        if prefer_provider not in provider_map:
            logger.warning(f"[llm_client] Unknown prefer_provider='{prefer_provider}', defaulting to bedrock")
            prefer_provider = "bedrock"

        strict_only = self.strict_preferred_default if strict_preferred is None else bool(strict_preferred)

        # Build provider order
        if strict_only:
            providers = [(prefer_provider, provider_map[prefer_provider])]
        elif prefer_provider == "bedrock":
            providers = [
                ("bedrock", provider_map["bedrock"]),
                ("gemini", self._call_gemini),
                ("claude", self._call_claude),
                ("nvidia", self._call_nvidia),
            ]
        elif prefer_provider == "claude":
            providers = [
                ("claude", self._call_claude),
                ("bedrock", provider_map["bedrock"]),
                ("gemini", self._call_gemini),
                ("nvidia", self._call_nvidia),
            ]
        elif prefer_provider == "nvidia":
            providers = [
                ("nvidia", self._call_nvidia),
                ("bedrock", provider_map["bedrock"]),
                ("gemini", self._call_gemini),
                ("claude", self._call_claude),
            ]
        else:
            providers = [
                ("gemini", self._call_gemini),
                ("bedrock", provider_map["bedrock"]),
                ("claude", self._call_claude),
                ("nvidia", self._call_nvidia),
            ]
        
        last_error = None
        for provider_name, call_fn in providers:
            try:
                result = call_fn(prompt, system, max_tokens, temperature)
                if result and not result.error:
                    return result
                last_error = result.error if result else "No response"
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[llm_client] {provider_name} failed: {e}")

        if strict_only:
            return LLMResponse(
                text="",
                provider="none",
                model="none",
                error=(
                    f"Preferred provider '{prefer_provider}' failed"
                    + (f". Last error: {last_error}" if last_error else "")
                ),
            )
        
        return LLMResponse(
            text="",
            provider="none",
            model="none",
            error=f"All providers failed. Last error: {last_error}"
        )
    
    def _call_gemini(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> Optional[LLMResponse]:
        """Call Gemini API with key rotation."""
        total_keys = len(self.pool.gemini_keys)
        if total_keys == 0:
            logger.warning("[llm_client] No available Gemini keys")
            return None

        last_error = None
        keys_tried = 0

        while keys_tried < total_keys:
            slot = self.pool.next_gemini()
            if not slot:
                break
            keys_tried += 1

            try:
                from google import genai

                client = genai.Client(api_key=slot.key)

                for model_name in GEMINI_MODELS:
                    try:
                        start = time.time()

                        config = genai.types.GenerateContentConfig(
                            temperature=temperature,
                            max_output_tokens=max_tokens,
                        )
                        if system:
                            config.system_instruction = system

                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=config,
                        )

                        latency = int((time.time() - start) * 1000)
                        text = response.text or ""

                        self.pool.mark_success(slot)

                        logger.info(f"[llm_client] Gemini/{model_name} OK ({latency}ms, {len(text)} chars) using key idx={keys_tried}")

                        return LLMResponse(
                            text=text,
                            provider="gemini",
                            model=model_name,
                            latency_ms=latency,
                        )

                    except Exception as e:
                        err_str = str(e).lower()
                        if "429" in err_str or "quota" in err_str or "rate" in err_str:
                            # Rate limited: mark and immediately try next key (same provider)
                            self.pool.mark_failure(slot, is_rate_limit=True)
                            last_error = f"Gemini/{model_name} rate-limited"
                            logger.warning(f"[llm_client] {last_error} (key idx {keys_tried})")
                            break  # Break model loop to switch key
                        # Non-rate errors: mark failure and continue models
                        self.pool.mark_failure(slot)
                        last_error = str(e)
                        logger.warning(f"[llm_client] Gemini/{model_name} error (key idx {keys_tried}): {e}")
                        continue

            except ImportError:
                logger.error("[llm_client] google-genai not installed")
                return None
            except Exception as e:
                self.pool.mark_failure(slot)
                last_error = str(e)
                logger.error(f"[llm_client] Gemini error (key idx {keys_tried}): {e}")

        if last_error:
            logger.warning(f"[llm_client] Gemini exhausted keys. Last error: {last_error}")
            return LLMResponse(
                text="",
                provider="gemini",
                model="none",
                error=str(last_error),
            )
        return None
    
    def _call_claude(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> Optional[LLMResponse]:
        """Call Claude API with key rotation."""
        if not self._ensure_anthropic():
            return LLMResponse(
                text="",
                provider="claude",
                model="none",
                error="anthropic package not installed",
            )

        if time.time() < self._claude_billing_blocked_until:
            remaining = int(self._claude_billing_blocked_until - time.time())
            return LLMResponse(
                text="",
                provider="claude",
                model="none",
                error=f"Claude temporarily disabled due to billing state ({remaining}s remaining)",
            )

        total_keys = len(self.pool.claude_keys)
        if total_keys == 0:
            logger.warning("[llm_client] No available Claude keys")
            return None

        last_error = None
        keys_tried = 0
        billing_blocked = False

        while keys_tried < total_keys:
            slot = self.pool.next_claude()
            if not slot:
                break
            keys_tried += 1

            try:
                client = self._anthropic_module.Anthropic(api_key=slot.key)

                for model_name in CLAUDE_MODELS:
                    try:
                        start = time.time()

                        kwargs = {
                            "model": model_name,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "messages": [{"role": "user", "content": prompt}],
                        }
                        if system:
                            kwargs["system"] = system

                        response = client.messages.create(**kwargs)

                        latency = int((time.time() - start) * 1000)
                        text = response.content[0].text if response.content else ""

                        self.pool.mark_success(slot)

                        input_tok = getattr(response.usage, "input_tokens", 0)
                        output_tok = getattr(response.usage, "output_tokens", 0)

                        logger.info(f"[llm_client] Claude/{model_name} OK ({latency}ms, {input_tok}+{output_tok} tokens) using key idx={keys_tried}")

                        return LLMResponse(
                            text=text,
                            provider="claude",
                            model=model_name,
                            input_tokens=input_tok,
                            output_tokens=output_tok,
                            latency_ms=latency,
                        )

                    except Exception as e:
                        err_str = str(e).lower()
                        if "credit balance is too low" in err_str or "plans & billing" in err_str:
                            cooldown_seconds = int(
                                os.getenv("CLAUDE_BILLING_COOLDOWN_SECONDS", "3600").strip() or "3600"
                            )
                            self._claude_billing_blocked_until = time.time() + max(cooldown_seconds, 300)
                            for s in self.pool.claude_keys:
                                self.pool.mark_failure(s, cooldown_seconds=max(cooldown_seconds, 300))
                                s.consecutive_failures = max(s.consecutive_failures, 5)

                            billing_blocked = True
                            last_error = (
                                "Claude billing blocked: credit balance too low; "
                                f"cooldown {max(cooldown_seconds, 300)}s"
                            )
                            logger.warning("[llm_client] %s", last_error)
                            break

                        if "429" in err_str or "rate" in err_str:
                            self.pool.mark_failure(slot, is_rate_limit=True)
                            last_error = f"Claude/{model_name} rate-limited"
                            logger.warning(f"[llm_client] {last_error} (key idx {keys_tried})")
                            break
                        self.pool.mark_failure(slot)
                        last_error = str(e)
                        logger.warning(f"[llm_client] Claude/{model_name} error (key idx {keys_tried}): {e}")
                        continue

                if billing_blocked:
                    break

            except Exception as e:
                self.pool.mark_failure(slot)
                last_error = str(e)
                logger.error(f"[llm_client] Claude error (key idx {keys_tried}): {e}")

            if billing_blocked:
                break

        if last_error:
            logger.warning(f"[llm_client] Claude exhausted keys. Last error: {last_error}")
            return LLMResponse(
                text="",
                provider="claude",
                model="none",
                error=str(last_error),
            )
        return None

    def _call_nvidia(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> Optional[LLMResponse]:
        """Call NVIDIA OpenAI-compatible chat completions API with key rotation."""
        total_keys = len(self.pool.nvidia_keys)
        if total_keys == 0:
            logger.warning("[llm_client] No available NVIDIA keys")
            return None

        endpoint = os.getenv(
            "NVIDIA_CHAT_COMPLETIONS_URL",
            "https://integrate.api.nvidia.com/v1/chat/completions",
        ).strip()

        last_error = None
        keys_tried = 0

        while keys_tried < total_keys:
            slot = self.pool.next_nvidia()
            if not slot:
                break
            keys_tried += 1

            try:
                import requests

                for model_name in NVIDIA_MODELS:
                    try:
                        start = time.time()

                        headers = {
                            "Authorization": f"Bearer {slot.key}",
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        }

                        messages = []
                        if system:
                            messages.append({"role": "system", "content": system})
                        messages.append({"role": "user", "content": prompt})

                        payload = {
                            "model": model_name,
                            "messages": messages,
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                            "top_p": 0.95,
                            "stream": False,
                        }

                        response = requests.post(
                            endpoint,
                            headers=headers,
                            json=payload,
                            timeout=90,
                        )

                        latency = int((time.time() - start) * 1000)

                        if response.status_code == 429:
                            self.pool.mark_failure(slot, is_rate_limit=True)
                            last_error = f"NVIDIA/{model_name} rate-limited"
                            logger.warning(f"[llm_client] {last_error} (key idx {keys_tried})")
                            break  # switch key

                        if response.status_code in {401, 403}:
                            self.pool.mark_failure(slot, cooldown_seconds=3600)
                            slot.consecutive_failures = max(slot.consecutive_failures, 5)
                            body_preview = response.text[:250]
                            last_error = f"NVIDIA/{model_name} HTTP {response.status_code}: {body_preview}"
                            logger.warning(
                                f"[llm_client] NVIDIA/{model_name} auth failure (key idx {keys_tried}): "
                                f"HTTP {response.status_code}"
                            )
                            break  # this key is not usable right now

                        if response.status_code >= 400:
                            self.pool.mark_failure(slot)
                            body_preview = response.text[:250]
                            last_error = f"NVIDIA/{model_name} HTTP {response.status_code}: {body_preview}"
                            logger.warning(
                                f"[llm_client] NVIDIA/{model_name} error (key idx {keys_tried}): "
                                f"HTTP {response.status_code}"
                            )
                            continue

                        try:
                            data = response.json()
                        except Exception as e:
                            self.pool.mark_failure(slot)
                            last_error = f"Invalid NVIDIA JSON response: {e}"
                            logger.warning(
                                f"[llm_client] NVIDIA/{model_name} invalid JSON (key idx {keys_tried}): {e}"
                            )
                            continue

                        choices = data.get("choices", [])
                        if not choices:
                            self.pool.mark_failure(slot)
                            last_error = "NVIDIA response missing choices"
                            logger.warning(
                                f"[llm_client] NVIDIA/{model_name} response missing choices (key idx {keys_tried})"
                            )
                            continue

                        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                        text = message.get("content", "")

                        if isinstance(text, list):
                            text = "".join(
                                part.get("text", "") if isinstance(part, dict) else str(part)
                                for part in text
                            )

                        text = str(text or "").strip()
                        if not text:
                            self.pool.mark_failure(slot)
                            last_error = "NVIDIA returned empty content"
                            logger.warning(
                                f"[llm_client] NVIDIA/{model_name} empty content (key idx {keys_tried})"
                            )
                            continue

                        usage = data.get("usage", {}) if isinstance(data.get("usage", {}), dict) else {}
                        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                        completion_tokens = int(usage.get("completion_tokens", 0) or 0)

                        self.pool.mark_success(slot)

                        logger.info(
                            f"[llm_client] NVIDIA/{model_name} OK "
                            f"({latency}ms, {prompt_tokens}+{completion_tokens} tokens) "
                            f"using key idx={keys_tried}"
                        )

                        return LLMResponse(
                            text=text,
                            provider="nvidia",
                            model=model_name,
                            input_tokens=prompt_tokens,
                            output_tokens=completion_tokens,
                            latency_ms=latency,
                        )

                    except Exception as e:
                        err_str = str(e).lower()
                        if "429" in err_str or "quota" in err_str or "rate" in err_str:
                            self.pool.mark_failure(slot, is_rate_limit=True)
                            last_error = f"NVIDIA/{model_name} rate-limited"
                            logger.warning(f"[llm_client] {last_error} (key idx {keys_tried})")
                            break

                        self.pool.mark_failure(slot)
                        last_error = str(e)
                        logger.warning(
                            f"[llm_client] NVIDIA/{model_name} error (key idx {keys_tried}): {e}"
                        )
                        continue

            except ImportError:
                logger.error("[llm_client] requests not installed")
                return None
            except Exception as e:
                self.pool.mark_failure(slot)
                last_error = str(e)
                logger.error(f"[llm_client] NVIDIA error (key idx {keys_tried}): {e}")

        if last_error:
            logger.warning(f"[llm_client] NVIDIA exhausted keys. Last error: {last_error}")
            return LLMResponse(
                text="",
                provider="nvidia",
                model="none",
                error=str(last_error),
            )
        return None

    def _call_bedrock(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
        task_complexity: str = "auto",
    ) -> Optional[LLMResponse]:
        """Call Bedrock converse API using bearer-token auth with model-tier routing."""
        total_keys = len(self.pool.bedrock_keys)
        if total_keys == 0:
            logger.warning("[llm_client] No available Bedrock bearer token")
            return None

        region = os.getenv("AWS_REGION", BEDROCK_REGION).strip() or BEDROCK_REGION

        complexity = (task_complexity or "auto").strip().lower()
        if complexity == "simple":
            model_list = BEDROCK_SIMPLE_MODELS
        elif complexity == "complex":
            model_list = BEDROCK_COMPLEX_MODELS
        else:
            model_list = _dedupe_keep_order(BEDROCK_COMPLEX_MODELS + BEDROCK_SIMPLE_MODELS)

        if not model_list:
            return LLMResponse(
                text="",
                provider="bedrock",
                model="none",
                error="No Bedrock models configured",
            )

        last_error = None
        keys_tried = 0

        while keys_tried < total_keys:
            slot = self.pool.next_bedrock()
            if not slot:
                break
            keys_tried += 1

            try:
                import requests

                for model_name in model_list:
                    try:
                        blocked_until = self._bedrock_model_blocked_until.get(model_name, 0.0)
                        if blocked_until and time.time() < blocked_until:
                            continue

                        start = time.time()

                        endpoint = (
                            f"https://bedrock-runtime.{region}.amazonaws.com/model/"
                            f"{quote(model_name, safe='')}/converse"
                        )
                        headers = {
                            "Authorization": f"Bearer {slot.key}",
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        }

                        body = {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [{"text": prompt}],
                                }
                            ],
                            "inferenceConfig": {
                                "maxTokens": max_tokens,
                                "temperature": temperature,
                            },
                        }
                        if system:
                            body["system"] = [{"text": system}]

                        response = requests.post(
                            endpoint,
                            headers=headers,
                            json=body,
                            timeout=90,
                        )
                        latency = int((time.time() - start) * 1000)

                        if response.status_code in {429, 503}:
                            self.pool.mark_failure(slot, is_rate_limit=True)
                            last_error = f"Bedrock/{model_name} rate-limited (HTTP {response.status_code})"
                            logger.warning(f"[llm_client] {last_error} (key idx {keys_tried})")
                            break

                        if response.status_code == 401:
                            self.pool.mark_failure(slot, cooldown_seconds=3600)
                            slot.consecutive_failures = max(slot.consecutive_failures, 5)
                            body_preview = response.text[:280]
                            last_error = f"Bedrock/{model_name} HTTP 401: {body_preview}"
                            logger.warning(
                                f"[llm_client] Bedrock/{model_name} auth failure (key idx {keys_tried}): "
                                "HTTP 401"
                            )
                            break

                        if response.status_code == 403:
                            body_preview = response.text[:320]
                            msg = body_preview.lower()
                            # Model-level access issues should fall through to the next configured model,
                            # not permanently disable the bearer token.
                            if (
                                "invalid_payment_instrument" in msg
                                or "model access is denied" in msg
                                or "not authorized to invoke this model" in msg
                                or "use case details" in msg
                            ):
                                cooldown = int(
                                    os.getenv("BEDROCK_MODEL_UNAVAILABLE_COOLDOWN_SECONDS", "1800").strip() or "1800"
                                )
                                self._bedrock_model_blocked_until[model_name] = time.time() + max(cooldown, 300)
                                last_error = f"Bedrock/{model_name} HTTP 403 model access denied"
                                logger.info(
                                    f"[llm_client] Bedrock/{model_name} denied (HTTP 403); trying next Bedrock model"
                                )
                                continue

                            # Unknown 403 is treated as token/account auth failure.
                            self.pool.mark_failure(slot, cooldown_seconds=3600)
                            slot.consecutive_failures = max(slot.consecutive_failures, 5)
                            last_error = f"Bedrock/{model_name} HTTP 403: {body_preview}"
                            logger.warning(
                                f"[llm_client] Bedrock/{model_name} auth failure (key idx {keys_tried}): HTTP 403"
                            )
                            break

                        if response.status_code >= 400:
                            body_preview = response.text[:320]
                            msg = body_preview.lower()
                            if "use case details" in msg:
                                cooldown = int(
                                    os.getenv("BEDROCK_MODEL_UNAVAILABLE_COOLDOWN_SECONDS", "1800").strip() or "1800"
                                )
                                self._bedrock_model_blocked_until[model_name] = time.time() + max(cooldown, 300)
                                last_error = f"Bedrock/{model_name} unavailable until use-case access is enabled"
                                logger.info(f"[llm_client] {last_error}; trying next Bedrock model")
                                continue

                            if (
                                "on-demand throughput" in msg
                                or "retry your request with the id or arn of an inference profile" in msg
                            ):
                                cooldown = int(
                                    os.getenv("BEDROCK_PROFILE_HINT_COOLDOWN_SECONDS", "900").strip() or "900"
                                )
                                self._bedrock_model_blocked_until[model_name] = time.time() + max(cooldown, 300)
                                last_error = f"Bedrock/{model_name} unavailable for current throughput mode"
                                logger.info(f"[llm_client] {last_error}; trying next Bedrock model")
                                continue

                            self.pool.mark_failure(slot)
                            last_error = f"Bedrock/{model_name} HTTP {response.status_code}: {body_preview}"
                            logger.warning(
                                f"[llm_client] Bedrock/{model_name} error (key idx {keys_tried}): "
                                f"HTTP {response.status_code}"
                            )
                            continue

                        try:
                            data = response.json()
                        except Exception as e:
                            self.pool.mark_failure(slot)
                            last_error = f"Invalid Bedrock JSON response: {e}"
                            logger.warning(
                                f"[llm_client] Bedrock/{model_name} invalid JSON (key idx {keys_tried}): {e}"
                            )
                            continue

                        content = (
                            data.get("output", {})
                            .get("message", {})
                            .get("content", [])
                        )
                        text = ""
                        if isinstance(content, list):
                            chunks = []
                            for part in content:
                                if isinstance(part, dict):
                                    chunks.append(str(part.get("text", "")))
                                else:
                                    chunks.append(str(part))
                            text = "".join(chunks).strip()

                        if not text:
                            self.pool.mark_failure(slot)
                            last_error = "Bedrock returned empty content"
                            logger.warning(
                                f"[llm_client] Bedrock/{model_name} empty content (key idx {keys_tried})"
                            )
                            continue

                        usage = data.get("usage", {}) if isinstance(data.get("usage", {}), dict) else {}
                        input_tok = int(
                            usage.get("inputTokens", usage.get("input_tokens", 0)) or 0
                        )
                        output_tok = int(
                            usage.get("outputTokens", usage.get("output_tokens", 0)) or 0
                        )

                        self.pool.mark_success(slot)

                        logger.info(
                            f"[llm_client] Bedrock/{model_name} OK "
                            f"({latency}ms, {input_tok}+{output_tok} tokens) using key idx={keys_tried}"
                        )

                        return LLMResponse(
                            text=text,
                            provider="bedrock",
                            model=model_name,
                            input_tokens=input_tok,
                            output_tokens=output_tok,
                            latency_ms=latency,
                        )

                    except Exception as e:
                        err_str = str(e).lower()
                        if "429" in err_str or "rate" in err_str or "throttl" in err_str:
                            self.pool.mark_failure(slot, is_rate_limit=True)
                            last_error = f"Bedrock/{model_name} rate-limited"
                            logger.warning(f"[llm_client] {last_error} (key idx {keys_tried})")
                            break

                        self.pool.mark_failure(slot)
                        last_error = str(e)
                        logger.warning(
                            f"[llm_client] Bedrock/{model_name} error (key idx {keys_tried}): {e}"
                        )
                        continue

            except ImportError:
                logger.error("[llm_client] requests not installed")
                return None
            except Exception as e:
                self.pool.mark_failure(slot)
                last_error = str(e)
                logger.error(f"[llm_client] Bedrock error (key idx {keys_tried}): {e}")

        if last_error:
            logger.warning(f"[llm_client] Bedrock exhausted keys. Last error: {last_error}")
            return LLMResponse(
                text="",
                provider="bedrock",
                model="none",
                error=str(last_error),
            )
        return None
    
    def health_check(self) -> Dict[str, Any]:
        """Report key pool status."""
        return {
            "gemini_keys": len(self.pool.gemini_keys),
            "gemini_available": sum(1 for k in self.pool.gemini_keys if k.is_available),
            "claude_keys": len(self.pool.claude_keys),
            "claude_available": sum(1 for k in self.pool.claude_keys if k.is_available),
            "nvidia_keys": len(self.pool.nvidia_keys),
            "nvidia_available": sum(1 for k in self.pool.nvidia_keys if k.is_available),
            "bedrock_keys": len(self.pool.bedrock_keys),
            "bedrock_available": sum(1 for k in self.pool.bedrock_keys if k.is_available),
        }


# Module-level singleton
_client = None

def get_client() -> LLMClient:
    """Get or create the singleton LLM client."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
