"""Voice service with Deepgram STT/TTS and optional Porcupine wake-word support."""

from __future__ import annotations

import logging
import json
import io
import struct
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Callable, Optional

from sara.config import (
    DEEPGRAM_API_KEY,
    DEEPGRAM_STT_LANGUAGE,
    DEEPGRAM_STT_MODEL,
    DEEPGRAM_TTS_MODEL,
    DEEPGRAM_TTS_SAMPLE_RATE,
    DISABLE_VOICE_INPUT,
    PICOVOICE_ACCESS_KEY,
    SARA_FEMALE_TTS_MODEL,
    SARA_FORCE_FEMALE_TTS,
    SARA_VOICE_LISTEN_TIMEOUT_SEC,
    SARA_VOICE_PHRASE_TIME_LIMIT_SEC,
    SARA_WAKE_SENSITIVITY,
    SARA_WAKE_WORD_PATH,
    WAKE_WORD,
)

logger = logging.getLogger("sara.voice")


class VoiceService:
    """Voice I/O wrapper with Deepgram defaults and robust runtime fallbacks."""

    def __init__(self, text_mode: Optional[bool] = None):
        # Text input is always available in UI/CLI. Voice input is auto-enabled by default
        # and only disabled when explicitly requested.
        self.text_mode = bool(DISABLE_VOICE_INPUT if text_mode is None else text_mode)
        self.wake_word = WAKE_WORD
        self.deepgram_api_key = DEEPGRAM_API_KEY
        self.deepgram_stt_model = DEEPGRAM_STT_MODEL
        self.deepgram_stt_language = DEEPGRAM_STT_LANGUAGE
        self.deepgram_tts_model = self._resolve_tts_model(DEEPGRAM_TTS_MODEL)
        self.deepgram_tts_sample_rate = max(16000, int(DEEPGRAM_TTS_SAMPLE_RATE))
        self.picovoice_access_key = PICOVOICE_ACCESS_KEY
        self.wake_word_path = Path(SARA_WAKE_WORD_PATH)
        self.wake_sensitivity = max(0.0, min(1.0, float(SARA_WAKE_SENSITIVITY)))
        self.listen_timeout_sec = max(1.0, float(SARA_VOICE_LISTEN_TIMEOUT_SEC))
        self.phrase_time_limit_sec = max(2.0, float(SARA_VOICE_PHRASE_TIME_LIMIT_SEC))

        self._listening = False
        self._listen_thread: Optional[threading.Thread] = None
        self._on_command: Optional[Callable[[str], None]] = None
        self._on_state_change: Optional[Callable[[str], None]] = None
        self._wake_controller = None

        self._recognizer = None
        self._porcupine = None
        self._pa = None
        self._wake_stream = None
        self._wake_engine_enabled = False
        self._temp_tts_file: Optional[Path] = None
        self._tts_engine = None
        self._tts_lock = threading.Lock()
        self._last_tts_backend = "none"
        self._last_tts_error = ""

        if not self.text_mode:
            self._init_voice_pipeline()

    def start_listening(
        self,
        on_command: Callable[[str], None],
        wake_controller=None,
        on_state_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Start background listening.

        In text mode, this keeps lifecycle status but does not open a microphone loop.
        """
        self._on_command = on_command
        self._wake_controller = wake_controller
        self._on_state_change = on_state_change
        self._listening = True
        self._emit_state("wake_enabled")

        if self.text_mode:
            logger.info("VoiceService in text mode: background listen is no-op")
            self._emit_state("text_mode")
            return

        if self._recognizer is None:
            logger.warning("Voice recognizer unavailable; falling back to text mode")
            self.text_mode = True
            self._emit_state("text_mode")
            return

        if self._listen_thread and self._listen_thread.is_alive():
            return

        self._listen_thread = threading.Thread(target=self._listen_loop, name="sara-voice-loop", daemon=True)
        self._listen_thread.start()

    def stop_listening(self) -> None:
        self._listening = False
        thread = self._listen_thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=0.25)
        self._close_wake_stream()
        self._emit_state("wake_stopped")

    def listen(self) -> Optional[str]:
        """Capture and transcribe one spoken command."""
        if self.text_mode:
            return None

        if self._recognizer is None:
            return None

        try:
            import speech_recognition as sr

            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.35)
                audio = self._recognizer.listen(
                    source,
                    timeout=self.listen_timeout_sec,
                    phrase_time_limit=self.phrase_time_limit_sec,
                )

            transcript = self._deepgram_transcribe_wav(audio.get_wav_data())
            if transcript:
                logger.info("Deepgram STT transcript=%r", transcript)
                return transcript

            # Fallback for resilience when Deepgram is unavailable.
            fallback = self._recognizer.recognize_google(audio)
            logger.info("Google fallback STT transcript=%r", fallback)
            return fallback
        except Exception as exc:
            logger.warning("Voice listen failed: %s", exc)
            return None

    def speak(self, text: str) -> None:
        """Synthesize output speech using Deepgram Aura, then local fallback."""
        if self.text_mode:
            logger.info("SARA: %s", text)
            return

        if not text:
            return

        played = False
        try:
            wav_path = self._deepgram_synthesize_wav(text)
            if wav_path is not None and self._is_valid_wav_file(wav_path):
                try:
                    import winsound

                    # SND_NODEFAULT prevents Windows from emitting a generic notification beep
                    # when a file is invalid or unplayable.
                    winsound.PlaySound(str(wav_path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
                    played = True
                    self._last_tts_backend = "deepgram"
                    self._last_tts_error = ""
                except Exception as exc:
                    logger.warning("Deepgram audio playback failed: %s", exc)
                    self._last_tts_error = str(exc)
            else:
                logger.warning("Deepgram TTS audio unavailable or invalid WAV; using local fallback")
                self._last_tts_error = "invalid_or_unavailable_deepgram_wav"
        except Exception as exc:
            logger.warning("Deepgram TTS failed: %s", exc)
            self._last_tts_error = str(exc)

        if played:
            return

        self._speak_local(text)

    def _speak_local(self, text: str) -> None:
        try:
            import pyttsx3  # type: ignore

            with self._tts_lock:
                if self._tts_engine is None:
                    self._tts_engine = pyttsx3.init()
                self._tts_engine.say(text)
                self._tts_engine.runAndWait()
            self._last_tts_backend = "pyttsx3_fallback"
        except Exception as exc:
            logger.warning("TTS fallback to log: %s", exc)
            logger.info("SARA: %s", text)
            self._last_tts_backend = "none"
            self._last_tts_error = str(exc)

    def _is_valid_wav_file(self, file_path: Path) -> bool:
        try:
            raw = file_path.read_bytes()
            if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
                return False

            with wave.open(str(file_path), "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                rate = wav_file.getframerate()
                frames = wav_file.getnframes()
                if channels <= 0 or sample_width <= 0 or frames <= 0 or rate <= 0:
                    return False

                # Guard against malformed/placeholder WAV headers where nframes does not
                # match file payload length (observed on some streamed responses).
                payload_bytes = len(raw) - 44
                bytes_per_frame = channels * sample_width
                frames_by_size = payload_bytes // bytes_per_frame if bytes_per_frame > 0 else 0
                if frames_by_size <= 0:
                    return False

                mismatch = abs(frames - frames_by_size)
                if mismatch > max(64, int(frames_by_size * 0.1)):
                    return False

                duration_sec = frames / float(rate)
                # Filter out extremely short files that are typically invalid responses.
                return duration_sec >= 0.2
        except Exception:
            return False

    def _canonicalize_wav_bytes(self, audio_bytes: bytes) -> bytes:
        """Rebuild WAV header from actual frame payload for reliable playback."""
        if not audio_bytes:
            return audio_bytes

        try:
            with io.BytesIO(audio_bytes) as source:
                with wave.open(source, "rb") as wav_in:
                    channels = wav_in.getnchannels()
                    sample_width = wav_in.getsampwidth()
                    rate = wav_in.getframerate()
                    frames = wav_in.readframes(wav_in.getnframes())

            if not frames:
                return audio_bytes

            with io.BytesIO() as output:
                with wave.open(output, "wb") as wav_out:
                    wav_out.setnchannels(channels)
                    wav_out.setsampwidth(sample_width)
                    wav_out.setframerate(rate)
                    wav_out.writeframes(frames)
                return output.getvalue()
        except Exception as exc:
            logger.warning("WAV canonicalization skipped: %s", exc)
            return audio_bytes

    def get_pipeline_status(self) -> dict:
        return {
            "mode": "TEXT" if self.text_mode else "VOICE",
            "wake_word": self.wake_word,
            "wake_engine": "porcupine" if self._wake_engine_enabled else "transcript",
            "wake_word_path": str(self.wake_word_path),
            "wake_word_file_exists": self.wake_word_path.exists(),
            "stt_backend": "Deepgram (Google fallback)",
            "stt_model": self.deepgram_stt_model,
            "tts_backend": "Deepgram Aura (pyttsx3 fallback)",
            "tts_model": self.deepgram_tts_model,
            "tts_sample_rate": self.deepgram_tts_sample_rate,
            "last_tts_backend": self._last_tts_backend,
            "last_tts_error": self._last_tts_error,
            "deepgram_configured": bool(self.deepgram_api_key),
            "picovoice_configured": bool(self.picovoice_access_key),
            "listening": self._listening,
            "thread_alive": bool(self._listen_thread and self._listen_thread.is_alive()),
        }

    def _resolve_tts_model(self, configured_model: str) -> str:
        model = (configured_model or "").strip() or "aura-2-thalia-en"
        if not SARA_FORCE_FEMALE_TTS:
            return model

        model_l = model.lower()
        female_tokens = {"thalia", "asteria", "luna", "stella", "athena", "hera"}
        if any(token in model_l for token in female_tokens):
            return model

        fallback_model = (SARA_FEMALE_TTS_MODEL or "aura-2-thalia-en").strip()
        logger.info("Overriding TTS model to female voice: %s", fallback_model)
        return fallback_model

    def _emit_state(self, state: str) -> None:
        callback = self._on_state_change
        if callback is None:
            return
        try:
            callback(state)
        except Exception as exc:
            logger.debug("State callback failed: %s", exc)

    def _dispatch_command(self, command: str) -> None:
        callback = self._on_command
        if callback is None:
            return
        cmd = (command or "").strip()
        if not cmd:
            return
        try:
            callback(cmd)
        except Exception as exc:
            logger.warning("Voice command callback failed: %s", exc)

    def _listen_loop(self) -> None:
        if self._wake_engine_enabled:
            self._listen_loop_with_porcupine()
            return

        self._emit_state("wake_idle")
        while self._listening:
            self._emit_state("wake_listening")
            transcript = self.listen()

            if not self._listening:
                break
            if not transcript:
                self._emit_state("wake_idle")
                continue

            self._emit_state("wake_detected")
            handled = False
            if self._wake_controller is not None:
                try:
                    handled = bool(self._wake_controller.handle_transcript(transcript, self._dispatch_command))
                except Exception as exc:
                    logger.warning("Wake controller failed: %s", exc)
                    self._emit_state("wake_error")
            else:
                self._dispatch_command(transcript)
                handled = True

            self._emit_state("wake_processing" if handled else "wake_idle")

        self._emit_state("wake_stopped")

    def _init_voice_pipeline(self) -> None:
        self._init_speech_recognizer()
        self._init_porcupine_wake_engine()

    def _init_speech_recognizer(self) -> None:
        try:
            import speech_recognition as sr

            self._recognizer = sr.Recognizer()
        except Exception as exc:
            logger.warning("speech_recognition unavailable: %s", exc)
            self._recognizer = None

    def _init_porcupine_wake_engine(self) -> None:
        self._wake_engine_enabled = False

        if not self.picovoice_access_key:
            logger.info("Picovoice access key missing; using transcript wake mode")
            return
        if not self.wake_word_path.exists():
            logger.info("Wake word file missing at %s; using transcript wake mode", self.wake_word_path)
            return

        try:
            import pvporcupine  # type: ignore
            import pyaudio  # type: ignore

            self._porcupine = pvporcupine.create(
                access_key=self.picovoice_access_key,
                keyword_paths=[str(self.wake_word_path)],
                sensitivities=[self.wake_sensitivity],
            )
            self._pa = pyaudio.PyAudio()
            self._open_wake_stream()
            self._wake_engine_enabled = self._wake_stream is not None
            if self._wake_engine_enabled:
                logger.info("Porcupine wake engine enabled using %s", self.wake_word_path)
        except Exception as exc:
            logger.warning("Porcupine wake engine unavailable: %s", exc)
            self._wake_engine_enabled = False
            self._close_wake_stream()

    def _open_wake_stream(self) -> None:
        if self._porcupine is None or self._pa is None or self._wake_stream is not None:
            return

        try:
            import pyaudio  # type: ignore

            self._wake_stream = self._pa.open(
                rate=self._porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self._porcupine.frame_length,
            )
        except Exception as exc:
            logger.warning("Failed to open wake audio stream: %s", exc)
            self._wake_stream = None

    def _close_wake_stream(self) -> None:
        stream = self._wake_stream
        self._wake_stream = None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def _listen_loop_with_porcupine(self) -> None:
        if self._porcupine is None:
            self._listen_loop()
            return

        self._emit_state("wake_idle")
        while self._listening:
            self._emit_state("wake_listening")

            if self._wake_stream is None:
                self._open_wake_stream()
                if self._wake_stream is None:
                    time.sleep(0.1)
                    continue

            try:
                pcm = self._wake_stream.read(self._porcupine.frame_length, exception_on_overflow=False)
                frame = struct.unpack_from("h" * self._porcupine.frame_length, pcm)
                keyword_index = self._porcupine.process(frame)
            except Exception as exc:
                logger.debug("Wake frame read failed: %s", exc)
                time.sleep(0.05)
                continue

            if keyword_index < 0:
                continue

            self._emit_state("wake_detected")

            # Temporarily release raw stream before phrase capture.
            self._close_wake_stream()
            transcript = self.listen()

            if transcript:
                self._dispatch_command(transcript)
                self._emit_state("wake_processing")
            else:
                self._emit_state("wake_idle")

            if self._listening:
                self._open_wake_stream()

        self._emit_state("wake_stopped")

    def _deepgram_transcribe_wav(self, wav_bytes: bytes) -> Optional[str]:
        if not wav_bytes or not self.deepgram_api_key:
            return None

        params = urllib.parse.urlencode(
            {
                "model": self.deepgram_stt_model,
                "language": self.deepgram_stt_language,
                "smart_format": "true",
                "punctuate": "true",
            }
        )
        url = f"https://api.deepgram.com/v1/listen?{params}"
        req = urllib.request.Request(
            url=url,
            data=wav_bytes,
            method="POST",
            headers={
                "Authorization": f"Token {self.deepgram_api_key}",
                "Content-Type": "audio/wav",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            logger.warning("Deepgram STT HTTP error: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Deepgram STT request failed: %s", exc)
            return None

        try:
            alternatives = payload["results"]["channels"][0]["alternatives"]
            transcript = str(alternatives[0].get("transcript", "")).strip()
            return transcript or None
        except Exception:
            logger.debug("Deepgram STT payload parse failed")
            return None

    def _deepgram_synthesize_wav(self, text: str) -> Optional[Path]:
        if not text or not self.deepgram_api_key:
            return None

        params = urllib.parse.urlencode(
            {
                "model": self.deepgram_tts_model,
                "encoding": "linear16",
                "container": "wav",
                "sample_rate": str(self.deepgram_tts_sample_rate),
            }
        )
        url = f"https://api.deepgram.com/v1/speak?{params}"
        body = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Token {self.deepgram_api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                audio_bytes = response.read()
        except urllib.error.HTTPError as exc:
            logger.warning("Deepgram TTS HTTP error: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Deepgram TTS request failed: %s", exc)
            return None

        if not audio_bytes:
            return None

        audio_bytes = self._canonicalize_wav_bytes(audio_bytes)

        if self._temp_tts_file and self._temp_tts_file.exists():
            try:
                self._temp_tts_file.unlink(missing_ok=True)
            except Exception:
                pass

        with tempfile.NamedTemporaryFile(prefix="sara_tts_", suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            self._temp_tts_file = Path(f.name)
        return self._temp_tts_file
