"""Compact always-on-top widget for quick SARA interactions."""

from __future__ import annotations

import logging
import sys

from sara.config import ENABLE_WAKE_LOOP
from sara.ui.styles import DARK
from sara.voice.wake_controller import WakeController


try:
    from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except Exception as exc:
    raise ImportError("PyQt5 is required for widget mode") from exc


logger = logging.getLogger("sara.ui.widget")


class _CommandWorker(QObject):
    done = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, agent, command: str):
        super().__init__()
        self._agent = agent
        self._command = command

    def _format_progress_event(self, event: dict) -> str:
        step_index = int(event.get("step_index", 0) or 0)
        action = event.get("action", {}) if isinstance(event.get("action", {}), dict) else {}
        action_type = str(action.get("action") or action.get("action_type") or "").strip().upper()

        target = ""
        if "target" in action:
            target = str(action.get("target", "")).strip()
        elif "keys" in action:
            target = str(action.get("keys", "")).strip()
        elif "text" in action:
            target = f"text_len={len(str(action.get('text', '')))}"

        status = "ok" if bool(event.get("success")) else "failed"
        label = f"{step_index}. {action_type}"
        if target:
            label += f" {target}"
        label += f" -> {status}"
        return label

    def run(self):
        try:
            def _on_progress(event):
                if not isinstance(event, dict):
                    return
                self.progress.emit(self._format_progress_event(event))

            self.done.emit(self._agent.process_command(self._command, progress_callback=_on_progress))
        except Exception as exc:
            self.error.emit(str(exc))


class _ListenOnceWorker(QObject):
    done = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, voice_service):
        super().__init__()
        self._voice_service = voice_service

    def run(self):
        try:
            command = self._voice_service.listen() or ""
            self.done.emit(command)
        except Exception as exc:
            self.error.emit(str(exc))


class SaraWidget(QWidget):
    voice_state_changed = pyqtSignal(str)
    wake_command_detected = pyqtSignal(str)

    def __init__(self, host_agent, voice_service=None):
        super().__init__()
        self.agent = host_agent
        self.voice_service = voice_service
        self.wake_controller = None
        self._command_thread = None
        self._command_worker = None
        self._listen_thread = None
        self._listen_worker = None
        self._build_ui()
        self.setStyleSheet(DARK)
        self.voice_state_changed.connect(self._on_voice_state)
        self.wake_command_detected.connect(self._on_wake_command)
        self._start_wake_loop_if_enabled()
        logger.info("Widget initialized dry_run=%s voice_available=%s", self.agent.dry_run, self.voice_service is not None)

    def _build_ui(self):
        self.setWindowTitle("SARA Widget")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setFixedWidth(420)
        self.setFixedHeight(160)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        self.status = QLabel(f"Idle (dry-run={self.agent.dry_run})")
        root.addWidget(self.status)
        self.voice_status = QLabel("Wake: disabled")
        root.addWidget(self.voice_status)
        self.dry_checkbox = QCheckBox("Dry-run")
        self.dry_checkbox.setChecked(self.agent.dry_run)
        self.dry_checkbox.stateChanged.connect(self._toggle_dry_run)
        root.addWidget(self.dry_checkbox)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type command...")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input)

        self.send_btn = QPushButton("Run")
        self.send_btn.setFixedWidth(64)
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn)

        self.ptt_btn = QPushButton("PTT")
        self.ptt_btn.setFixedWidth(64)
        self.ptt_btn.clicked.connect(self._push_to_talk)
        row.addWidget(self.ptt_btn)

        root.addLayout(row)

    def _toggle_dry_run(self, state: int) -> None:
        self.agent.dry_run = bool(state)
        self.status.setText(f"Idle (dry-run={self.agent.dry_run})")
        logger.info("Widget dry-run toggled to %s", self.agent.dry_run)

    def _send(self):
        command = self.input.text().strip()
        if not command:
            return
        self.input.clear()
        self._run_command(command, source="Typed")

    def _run_command(self, command: str, source: str) -> None:
        if self._command_thread and self._command_thread.isRunning():
            self.status.setText("Busy: command already running")
            logger.warning("Command ignored while busy source=%s command=%r", source, command)
            return

        logger.info("Dispatch command source=%s dry_run=%s command=%r", source, self.agent.dry_run, command)
        self.status.setText(f"{source}: Planning/Acting...")
        self.send_btn.setEnabled(False)
        self.ptt_btn.setEnabled(False)

        worker = _CommandWorker(self.agent, command)
        thread = QThread()
        self._command_worker = worker
        self._command_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_command_progress)
        worker.done.connect(self._on_command_result)
        worker.error.connect(self._on_command_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()

    def _on_command_progress(self, line: str):
        text = (line or "").strip()
        if text:
            self.status.setText(f"Step: {text}")

    def _on_command_result(self, result):
        self.send_btn.setEnabled(True)
        self.ptt_btn.setEnabled(True)
        logger.info(
            "Command result intent=%s success=%s tier=%s error=%s",
            result.intent,
            result.execution_success,
            result.tier_used,
            result.error,
        )
        if result.execution_success:
            self.status.setText("Done")
        else:
            self.status.setText(f"Failed: {result.error or 'unknown'}")
        if self.voice_service is not None and result.response_text:
            self.voice_service.speak(result.response_text)

    def _on_command_error(self, error: str):
        self.send_btn.setEnabled(True)
        self.ptt_btn.setEnabled(True)
        logger.error("Command worker failed: %s", error)
        self.status.setText(f"Failed: {error}")

    def _push_to_talk(self):
        if self.voice_service is None:
            self.status.setText("Voice unavailable")
            logger.warning("PTT requested but voice service unavailable")
            return

        if self._listen_thread and self._listen_thread.isRunning():
            self.status.setText("Already listening...")
            logger.warning("PTT requested while already listening")
            return

        self.status.setText("Listening...")
        logger.info("PTT listen started")
        self.ptt_btn.setEnabled(False)
        worker = _ListenOnceWorker(self.voice_service)
        thread = QThread()
        self._listen_worker = worker
        self._listen_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_ptt_done)
        worker.error.connect(self._on_ptt_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()

    def _on_ptt_done(self, command: str):
        self.ptt_btn.setEnabled(True)
        cmd = (command or "").strip()
        if not cmd:
            self.status.setText("No speech captured; use typed command")
            logger.info("PTT finished with no captured speech")
            return
        logger.info("PTT captured command=%r", cmd)
        self.input.setText(cmd)
        self._run_command(cmd, source="Voice")

    def _on_ptt_error(self, error: str):
        self.ptt_btn.setEnabled(True)
        logger.error("PTT failed: %s", error)
        self.status.setText(f"Voice failed: {error}")

    def _start_wake_loop_if_enabled(self) -> None:
        if self.voice_service is None:
            self.voice_status.setText("Wake: voice unavailable")
            logger.info("Wake loop unavailable: no voice service")
            return
        if not ENABLE_WAKE_LOOP:
            self.voice_status.setText("Wake: disabled by config")
            logger.info("Wake loop disabled by config")
            return

        self.wake_controller = WakeController(getattr(self.voice_service, "wake_word", "hey sara"))
        self.voice_service.start_listening(
            on_command=self._emit_wake_command,
            wake_controller=self.wake_controller,
            on_state_change=self._emit_voice_state,
        )
        self.voice_status.setText("Wake: enabled")
        logger.info("Wake loop started")

    def _emit_voice_state(self, state: str) -> None:
        self.voice_state_changed.emit(state)

    def _emit_wake_command(self, command: str) -> None:
        self.wake_command_detected.emit(command)

    def _on_voice_state(self, state: str) -> None:
        self.voice_status.setText(f"Wake: {state}")

    def _on_wake_command(self, command: str) -> None:
        cmd = (command or "").strip()
        if not cmd:
            return
        logger.info("Wake command captured=%r", cmd)
        self.input.setText(cmd)
        self._run_command(cmd, source="Wake")

    def closeEvent(self, event):
        if self.voice_service is not None:
            self.voice_service.stop_listening()
            logger.info("Widget closing; voice listening stopped")
        super().closeEvent(event)


def launch_widget(host_agent, voice_service=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    widget = SaraWidget(host_agent, voice_service=voice_service)
    widget.show()
    return app.exec_()
