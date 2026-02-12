# src/llm/llm_client.py
"""
LLM Client with multi-provider key rotation.
Supports Gemini (google-genai) and Claude (anthropic) with automatic fallback.

Model identifiers (as of Feb 2026):
  Gemini:  gemini-2.5-flash, gemini-2.0-flash
  Claude:  claude-sonnet-4-20250514, claude-3-5-sonnet-20241022
"""

import os
import sys
import time
import json
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path

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
    provider: str  # "gemini" or "claude"
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
        self._gemini_idx = 0
        self._claude_idx = 0
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
        
        logger.info(f"Key pool: {len(self.gemini_keys)} Gemini, {len(self.claude_keys)} Claude keys loaded")
    
    def next_gemini(self) -> Optional[KeySlot]:
        """Get next available Gemini key (round-robin)."""
        return self._next(self.gemini_keys, "_gemini_idx")
    
    def next_claude(self) -> Optional[KeySlot]:
        """Get next available Claude key (round-robin)."""
        return self._next(self.claude_keys, "_claude_idx")
    
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
    
    def mark_failure(self, slot: KeySlot, is_rate_limit: bool = False):
        slot.consecutive_failures += 1
        if is_rate_limit:
            slot.cooldown_until = time.time() + 60  # 60s cooldown on rate limit


# =============================================================================
# LLM CLIENT
# =============================================================================

# Gemini models in priority order
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]
# Claude models in priority order
CLAUDE_MODELS = ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022"]


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
    
    Priority: Gemini -> Claude (Gemini is cheaper and faster for planning).
    Falls back across providers when rate-limited.
    """
    
    def __init__(self):
        self.pool = KeyPool()
        self._gemini_client = None
        self._claude_client = None
    
    def call(
        self, 
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        prefer_provider: str = "gemini"
    ) -> LLMResponse:
        """
        Call LLM with automatic provider rotation.
        Tries preferred provider first, falls back to alternate.
        
        Args:
            prompt: User prompt
            system: System prompt
            max_tokens: Max output tokens
            temperature: Sampling temperature
            prefer_provider: "gemini" or "claude"
        
        Returns:
            LLMResponse with text and metadata
        """
        # Build provider order
        if prefer_provider == "claude":
            providers = [
                ("claude", self._call_claude),
                ("gemini", self._call_gemini),
            ]
        else:
            providers = [
                ("gemini", self._call_gemini),
                ("claude", self._call_claude),
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
        slot = self.pool.next_gemini()
        if not slot:
            logger.warning("[llm_client] No available Gemini keys")
            return None
        
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
                    
                    logger.info(f"[llm_client] Gemini/{model_name} OK ({latency}ms, {len(text)} chars)")
                    
                    return LLMResponse(
                        text=text,
                        provider="gemini",
                        model=model_name,
                        latency_ms=latency,
                    )
                    
                except Exception as e:
                    err_str = str(e).lower()
                    if "429" in err_str or "quota" in err_str or "rate" in err_str:
                        self.pool.mark_failure(slot, is_rate_limit=True)
                        logger.warning(f"[llm_client] Gemini/{model_name} rate-limited")
                        break  # Try next provider, don't try next model
                    logger.warning(f"[llm_client] Gemini/{model_name} error: {e}")
                    continue  # Try next model
            
        except ImportError:
            logger.error("[llm_client] google-genai not installed")
        except Exception as e:
            self.pool.mark_failure(slot)
            logger.error(f"[llm_client] Gemini error: {e}")
        
        return None
    
    def _call_claude(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> Optional[LLMResponse]:
        """Call Claude API with key rotation."""
        slot = self.pool.next_claude()
        if not slot:
            logger.warning("[llm_client] No available Claude keys")
            return None
        
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=slot.key)
            
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
                    
                    logger.info(f"[llm_client] Claude/{model_name} OK ({latency}ms, {input_tok}+{output_tok} tokens)")
                    
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
                    if "429" in err_str or "rate" in err_str:
                        self.pool.mark_failure(slot, is_rate_limit=True)
                        logger.warning(f"[llm_client] Claude/{model_name} rate-limited")
                        break
                    logger.warning(f"[llm_client] Claude/{model_name} error: {e}")
                    continue
            
        except ImportError:
            logger.error("[llm_client] anthropic not installed")
        except Exception as e:
            self.pool.mark_failure(slot)
            logger.error(f"[llm_client] Claude error: {e}")
        
        return None
    
    def health_check(self) -> Dict[str, Any]:
        """Report key pool status."""
        return {
            "gemini_keys": len(self.pool.gemini_keys),
            "gemini_available": sum(1 for k in self.pool.gemini_keys if k.is_available),
            "claude_keys": len(self.pool.claude_keys),
            "claude_available": sum(1 for k in self.pool.claude_keys if k.is_available),
        }


# Module-level singleton
_client = None

def get_client() -> LLMClient:
    """Get or create the singleton LLM client."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
