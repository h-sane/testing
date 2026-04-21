"""Sensitive-data sanitizer for cloud LLM prompts.

This module provides a cloud-safe sanitization layer that can run with:
- Microsoft Presidio (when installed), and
- deterministic regex fallback for must-catch patterns.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger("sara.privacy.sanitizer")


@dataclass
class SensitiveSpan:
    start: int
    end: int
    entity: str
    value: str


@dataclass
class SanitizationResult:
    sanitized_text: str
    token_map: Dict[str, str]
    redaction_count: int
    used_presidio: bool


class SensitiveDataSanitizer:
    """Detect and redact/tokenize sensitive values before cloud calls."""

    _SECRET_ENTITIES = {
        "PASSWORD",
        "API_KEY",
        "TOKEN",
        "SECRET",
        "ACCESS_KEY",
    }

    def __init__(self) -> None:
        self.enabled = os.getenv("SARA_PRIVACY_SANITIZER_ENABLED", "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.enable_presidio = os.getenv("SARA_PRIVACY_USE_PRESIDIO", "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._presidio_analyzer = None
        self._presidio_initialized = False

        # Regexes provide deterministic defense for common sensitive patterns.
        self._regex_patterns = [
            ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
            ("PHONE", re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b")),
            ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
            ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
            ("ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
            ("TOKEN", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
            # Capture just the secret value where possible.
            (
                "PASSWORD",
                re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*([^\s,;]+)"),
            ),
            (
                "API_KEY",
                re.compile(r"(?i)\b(?:api[_\s-]?key|secret[_\s-]?key)\s*[:=]\s*([^\s,;]+)"),
            ),
            (
                "TOKEN",
                re.compile(r"(?i)\b(?:access[_\s-]?token|refresh[_\s-]?token|bearer)\s*[:=]\s*([^\s,;]+)"),
            ),
        ]

    def sanitize(self, text: str) -> SanitizationResult:
        raw_text = str(text or "")
        if not self.enabled or not raw_text:
            return SanitizationResult(
                sanitized_text=raw_text,
                token_map={},
                redaction_count=0,
                used_presidio=False,
            )

        spans: List[SensitiveSpan] = []
        used_presidio = False

        presidio_spans = self._detect_with_presidio(raw_text)
        if presidio_spans:
            used_presidio = True
            spans.extend(presidio_spans)

        spans.extend(self._detect_with_regex(raw_text))
        spans = self._dedupe_overlaps(spans)

        if not spans:
            return SanitizationResult(
                sanitized_text=raw_text,
                token_map={},
                redaction_count=0,
                used_presidio=used_presidio,
            )

        token_map: Dict[str, str] = {}
        decorated: List[tuple[SensitiveSpan, str, str]] = []
        for idx, span in enumerate(spans, start=1):
            token = self._token_for(span.entity, idx)
            if span.entity in self._SECRET_ENTITIES:
                replacement = "[REDACTED_SECRET]"
            else:
                replacement = token
                token_map[token] = span.value
            decorated.append((span, replacement, token))

        sanitized = raw_text
        for span, replacement, _ in sorted(decorated, key=lambda item: item[0].start, reverse=True):
            sanitized = sanitized[: span.start] + replacement + sanitized[span.end :]

        return SanitizationResult(
            sanitized_text=sanitized,
            token_map=token_map,
            redaction_count=len(spans),
            used_presidio=used_presidio,
        )

    def _token_for(self, entity: str, index: int) -> str:
        cleaned = re.sub(r"[^A-Z0-9]+", "_", entity.upper()).strip("_") or "SENSITIVE"
        return f"[REDACTED_{cleaned}_{index}]"

    def _detect_with_regex(self, text: str) -> List[SensitiveSpan]:
        spans: List[SensitiveSpan] = []
        for entity, pattern in self._regex_patterns:
            for match in pattern.finditer(text):
                if match.groups():
                    start, end = match.span(1)
                else:
                    start, end = match.span(0)
                value = text[start:end]
                if not value:
                    continue
                spans.append(SensitiveSpan(start=start, end=end, entity=entity, value=value))
        return spans

    def _detect_with_presidio(self, text: str) -> List[SensitiveSpan]:
        analyzer = self._get_presidio_analyzer()
        if analyzer is None:
            return []

        try:
            entities = [
                "EMAIL_ADDRESS",
                "PHONE_NUMBER",
                "CREDIT_CARD",
                "US_SSN",
                "IBAN_CODE",
                "IP_ADDRESS",
            ]
            threshold = float(os.getenv("SARA_PRESIDIO_SCORE_THRESHOLD", "0.45"))
            results = analyzer.analyze(
                text=text,
                entities=entities,
                language="en",
                score_threshold=threshold,
            )
        except Exception as exc:
            logger.warning("Presidio analysis failed, using regex fallback only: %s", exc)
            return []

        mapping = {
            "EMAIL_ADDRESS": "EMAIL",
            "PHONE_NUMBER": "PHONE",
            "CREDIT_CARD": "CREDIT_CARD",
            "US_SSN": "SSN",
            "IBAN_CODE": "BANK_ACCOUNT",
            "IP_ADDRESS": "IP_ADDRESS",
        }

        spans: List[SensitiveSpan] = []
        for item in results:
            start = int(getattr(item, "start", -1))
            end = int(getattr(item, "end", -1))
            if start < 0 or end <= start or end > len(text):
                continue
            entity = mapping.get(getattr(item, "entity_type", ""), "SENSITIVE")
            value = text[start:end]
            spans.append(SensitiveSpan(start=start, end=end, entity=entity, value=value))
        return spans

    def _get_presidio_analyzer(self):
        if self._presidio_initialized:
            return self._presidio_analyzer

        self._presidio_initialized = True
        if not self.enable_presidio:
            return None

        try:
            from presidio_analyzer import AnalyzerEngine

            self._presidio_analyzer = AnalyzerEngine()
            logger.info("Privacy sanitizer initialized with Microsoft Presidio")
        except Exception:
            self._presidio_analyzer = None
            logger.info("Presidio not available; privacy sanitizer using regex fallback")

        return self._presidio_analyzer

    def _dedupe_overlaps(self, spans: List[SensitiveSpan]) -> List[SensitiveSpan]:
        if not spans:
            return []

        selected: List[SensitiveSpan] = []
        # Prefer longer spans first, then earlier starts.
        for span in sorted(spans, key=lambda s: (-(s.end - s.start), s.start)):
            overlap = False
            for existing in selected:
                if not (span.end <= existing.start or span.start >= existing.end):
                    overlap = True
                    break
            if not overlap:
                selected.append(span)

        return sorted(selected, key=lambda s: s.start)


_sanitizer = SensitiveDataSanitizer()


def sanitize_sensitive_text(text: str) -> SanitizationResult:
    """Sanitize one text payload before sending it to a cloud provider."""
    return _sanitizer.sanitize(text)
