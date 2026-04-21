"""Main chat-style UI window for SARA demo."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional

from sara.config import ENABLE_WAKE_LOOP, SUPPORTED_APPS
from sara.ui.components import ActiveTaskCard, ChatContainer, HealthCard, PlanCard, StatusChip, VoiceBubble
from sara.ui.theme import DEFAULT_THEME, build_main_stylesheet
from sara.voice.wake_controller import WakeController


try:
    from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
    from PyQt5.QtGui import QKeySequence
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QPushButton,
        QShortcut,
        QSplitter,
        QStackedWidget,
        QTabWidget,
        QTextEdit,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except Exception as exc:
    raise ImportError("PyQt5 is required for chat widget") from exc


logger = logging.getLogger("sara.ui.chat")


def _app_choices() -> list[str]:
    seen = set()
    ordered: list[str] = []

    def _add(name: str) -> None:
        value = str(name or "").strip()
        if not value:
            return
        key = value.lower()
        if key in seen:
            return
        seen.add(key)
        ordered.append(value)

    for name in SUPPORTED_APPS:
        _add(name)

    try:
        from src.harness import config as harness_config

        for name in harness_config.get_available_apps():
            _add(name)
        for name in harness_config.list_user_registered_apps():
            _add(name)
    except Exception:
        logger.exception("Unable to load dynamic app choices from harness config")

    return ordered


class _Worker(QObject):
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
        method = str(event.get("execution_method", "")).strip()
        signal = str(event.get("verification_signal", "")).strip()
        details = ", ".join(part for part in [method, signal] if part)

        label = f"{step_index}. {action_type}"
        if target:
            label += f" {target}"
        label += f" -> {status}"
        if details:
            label += f" ({details})"
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


class _ProbeWorker(QObject):
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, app_name: str, max_time: int, clear_cache: bool):
        super().__init__()
        self._app_name = app_name
        self._max_time = int(max_time)
        self._clear_cache = bool(clear_cache)

    def run(self):
        try:
            from src.harness.probe_dashboard import run_probe_report

            report = run_probe_report(
                app_name=self._app_name,
                max_time=self._max_time,
                clear_cache=self._clear_cache,
            )
            self.done.emit(report)
        except Exception as exc:
            self.error.emit(str(exc))


class _ExecutableScanWorker(QObject):
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, max_results: int):
        super().__init__()
        self._max_results = int(max_results)

    def run(self):
        try:
            from src.harness.executable_inventory import discover_all_executables

            rows = discover_all_executables(max_results=self._max_results)
            self.done.emit(rows)
        except Exception as exc:
            self.error.emit(str(exc))


class _ChatInputBox(QTextEdit):
    send_requested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class SaraChatWindow(QMainWindow):
    voice_state_changed = pyqtSignal(str)
    wake_command_detected = pyqtSignal(str)

    def __init__(self, host_agent, voice_service=None):
        super().__init__()
        self.agent = host_agent
        self.voice_service = voice_service
        self.wake_controller = None
        self._thread: Optional[QThread] = None
        self._listen_thread: Optional[QThread] = None
        self._worker = None
        self._listen_worker = None
        self._probe_thread: Optional[QThread] = None
        self._probe_worker = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker = None
        self._probe_reports: List[Dict[str, Any]] = []
        self._discovered_apps: List[Dict[str, str]] = []
        self._executable_inventory: List[Dict[str, str]] = []
        self._automation_catalog: Dict[str, Dict[str, Any]] = {}
        self._saw_live_progress = False
        self._last_error = ""
        self._runtime_status = "idle"
        self._nav_expanded = True
        self._context_visible = False
        self._suspend_auto_onboard = False
        self._active_probe_origin = "manual"
        self._shortcuts: List[QShortcut] = []

        self._build_ui()
        self.setStyleSheet(build_main_stylesheet(DEFAULT_THEME))
        self.voice_state_changed.connect(self._on_voice_state)
        self.wake_command_detected.connect(self._on_wake_command)
        self._start_wake_loop_if_enabled()
        self._set_mode("assistant")
        self._refresh_panels()
        self._append_assistant_note(f"SARA ready. Enter a command. Dry-run={self.agent.dry_run}")
        logger.info("Chat window initialized dry_run=%s voice_available=%s", self.agent.dry_run, self.voice_service is not None)

    def _build_ui(self):
        self.setWindowTitle("SARA Assistant")
        screen = QApplication.primaryScreen().availableGeometry()
        desired_center_width = 860
        desired_width = desired_center_width + DEFAULT_THEME.layout.nav_expanded_width
        target_width = min(desired_width, max(820, screen.width() - 48))
        target_height = min(620, max(460, screen.height() - 240))
        self.resize(target_width, target_height)

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.left_nav = self._build_left_nav()
        root_layout.addWidget(self.left_nav)

        self.main_splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(self.main_splitter, 1)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self.top_bar = self._build_top_bar()
        center_layout.addWidget(self.top_bar)

        self.mode_stack = QStackedWidget()
        self.page_index = {}

        assistant_page = self._build_assistant_page()
        tasks_page = self._build_tasks_page()
        apps_page = self._build_apps_page()
        memory_page = self._build_memory_page()
        settings_page = self._build_settings_page()

        self.page_index["assistant"] = self.mode_stack.addWidget(assistant_page)
        self.page_index["tasks"] = self.mode_stack.addWidget(tasks_page)
        self.page_index["apps"] = self.mode_stack.addWidget(apps_page)
        self.page_index["memory"] = self.mode_stack.addWidget(memory_page)
        self.page_index["settings"] = self.mode_stack.addWidget(settings_page)

        center_layout.addWidget(self.mode_stack, 1)

        self.context_panel = self._build_context_panel()

        self.main_splitter.addWidget(center)
        self.main_splitter.addWidget(self.context_panel)
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 1)
        if self._context_visible:
            self.main_splitter.setSizes([700, DEFAULT_THEME.layout.context_panel_width])
            self.context_panel.setVisible(True)
        else:
            self.main_splitter.setSizes([900, 0])
            self.context_panel.setVisible(False)

        self.setCentralWidget(root)

        self._configure_keyboard_shortcuts()
        self._configure_tab_order()
        self._refresh_app_choices()

    def _build_left_nav(self) -> QWidget:
        nav = QWidget()
        nav.setProperty("component", "leftNav")
        initial_width = (
            DEFAULT_THEME.layout.nav_expanded_width
            if self._nav_expanded
            else DEFAULT_THEME.layout.nav_collapsed_width
        )
        nav.setFixedWidth(initial_width)

        layout = QVBoxLayout(nav)
        layout.setContentsMargins(
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.xl,
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.xl,
        )
        layout.setSpacing(DEFAULT_THEME.spacing.sm)

        title = QLabel("SARA")
        title.setProperty("component", "title")
        layout.addWidget(title)

        subtitle = QLabel("Assistant Shell")
        subtitle.setProperty("component", "caption")
        layout.addWidget(subtitle)

        layout.addSpacing(DEFAULT_THEME.spacing.md)

        self.nav_buttons: Dict[str, QPushButton] = {}
        self.nav_buttons["assistant"] = self._nav_button("assistant", "Assistant")
        self.nav_buttons["tasks"] = self._nav_button("tasks", "Tasks and Runs")
        self.nav_buttons["apps"] = self._nav_button("apps", "Crawler")
        self.nav_buttons["memory"] = self._nav_button("memory", "Memory")
        self.nav_buttons["settings"] = self._nav_button("settings", "Settings")

        for button in self.nav_buttons.values():
            layout.addWidget(button)

        layout.addStretch(1)
        return nav

    def _nav_button(self, mode: str, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setCheckable(True)
        button.setProperty("component", "navButton")
        button.setProperty("variant", "ghost")
        button.clicked.connect(lambda _checked=False, target=mode: self._set_mode(target))
        return button

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setProperty("component", "topBar")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.md,
        )
        layout.setSpacing(DEFAULT_THEME.spacing.md)

        self.nav_toggle_btn = QPushButton("Nav -" if self._nav_expanded else "Nav +")
        self.nav_toggle_btn.setProperty("variant", "ghost")
        self.nav_toggle_btn.clicked.connect(self._toggle_nav)
        layout.addWidget(self.nav_toggle_btn)

        app_name = QLabel("SARA Assistant")
        app_name.setProperty("component", "sectionTitle")
        layout.addWidget(app_name)

        layout.addStretch(1)

        self.voice_bubble = VoiceBubble()
        layout.addWidget(self.voice_bubble)

        self.voice_label = QLabel("Wake: disabled")
        self.voice_label.setProperty("component", "caption")
        layout.addWidget(self.voice_label)

        self.runtime_chip = StatusChip("idle")
        layout.addWidget(self.runtime_chip)

        self.context_toggle_btn = QPushButton("Context -" if self._context_visible else "Context +")
        self.context_toggle_btn.setProperty("variant", "ghost")
        self.context_toggle_btn.clicked.connect(self._toggle_context_panel)
        layout.addWidget(self.context_toggle_btn)

        self.clear_chat_btn = QPushButton("Clear")
        self.clear_chat_btn.setProperty("variant", "ghost")
        self.clear_chat_btn.clicked.connect(self._clear_chat)
        layout.addWidget(self.clear_chat_btn)

        self.ptt_btn = QPushButton("Talk")
        self.ptt_btn.clicked.connect(self._push_to_talk)
        layout.addWidget(self.ptt_btn)

        return bar

    def _build_assistant_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
        )
        root.setSpacing(DEFAULT_THEME.spacing.lg)

        toolbar = QWidget()
        toolbar.setProperty("component", "assistantToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.sm,
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.sm,
        )
        toolbar_layout.setSpacing(DEFAULT_THEME.spacing.sm)

        self.dry_checkbox = QCheckBox("Dry-run")
        self.dry_checkbox.setChecked(self.agent.dry_run)
        self.dry_checkbox.stateChanged.connect(self._toggle_dry_run)
        toolbar_layout.addWidget(self.dry_checkbox)

        app_hint = QLabel("App routing is automatic")
        app_hint.setProperty("component", "caption")
        toolbar_layout.addWidget(app_hint)

        hint = QLabel("Enter: send | Shift+Enter: newline")
        hint.setProperty("component", "caption")
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(hint)

        root.addWidget(toolbar)

        self.chat_container = ChatContainer()
        root.addWidget(self.chat_container, 1)

        composer = QWidget()
        composer.setProperty("component", "composerRow")
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.sm,
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.sm,
        )
        composer_layout.setSpacing(DEFAULT_THEME.spacing.sm)

        self.input_box = _ChatInputBox()
        self.input_box.setFixedHeight(104)
        self.input_box.send_requested.connect(self._send)
        composer_layout.addWidget(self.input_box, 1)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        composer_layout.addWidget(self.send_btn)

        root.addWidget(composer)
        return page

    def _build_tasks_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
        )
        root.setSpacing(DEFAULT_THEME.spacing.md)

        header = QLabel("Tasks and Runs")
        header.setProperty("component", "sectionTitle")
        root.addWidget(header)

        tabs = QTabWidget()
        self.plan_tab = QTextEdit()
        self.plan_tab.setReadOnly(True)
        tabs.addTab(self.plan_tab, "Plan")

        self.status_tab = QTextEdit()
        self.status_tab.setReadOnly(True)
        tabs.addTab(self.status_tab, "Status")

        self.dashboard_tab = QTextEdit()
        self.dashboard_tab.setReadOnly(True)
        tabs.addTab(self.dashboard_tab, "Dashboard")

        root.addWidget(tabs, 1)
        return page

    def _build_apps_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
        )
        root.setSpacing(DEFAULT_THEME.spacing.md)

        title = QLabel("Crawler and Onboarding")
        title.setProperty("component", "sectionTitle")
        root.addWidget(title)

        inventory_ops = QHBoxLayout()
        self.scan_executables_btn = QPushButton("Scan All Executables")
        self.scan_executables_btn.clicked.connect(self._scan_all_executables)
        inventory_ops.addWidget(self.scan_executables_btn)

        inventory_ops.addWidget(QLabel("Scan limit (0=all):"))
        self.scan_limit_input = QLineEdit("0")
        self.scan_limit_input.setFixedWidth(70)
        inventory_ops.addWidget(self.scan_limit_input)

        self.browse_exe_btn = QPushButton("Browse EXE...")
        self.browse_exe_btn.clicked.connect(self._browse_executable)
        inventory_ops.addWidget(self.browse_exe_btn)

        inventory_ops.addStretch(1)
        root.addLayout(inventory_ops)

        self.executable_combo = QComboBox()
        self.executable_combo.setMinimumWidth(480)
        self.executable_combo.currentIndexChanged.connect(self._on_executable_pick_changed)
        root.addWidget(self.executable_combo)

        onboarding_ops = QHBoxLayout()
        self.auto_onboard_checkbox = QCheckBox("Auto register + probe on executable selection")
        self.auto_onboard_checkbox.setChecked(True)
        onboarding_ops.addWidget(self.auto_onboard_checkbox)

        self.auto_onboard_btn = QPushButton("Register + Probe Selected Executable")
        self.auto_onboard_btn.clicked.connect(self._auto_onboard_selected_executable)
        onboarding_ops.addWidget(self.auto_onboard_btn)
        onboarding_ops.addStretch(1)
        root.addLayout(onboarding_ops)

        app_ops = QHBoxLayout()
        self.discover_btn = QPushButton("Discover Windows Apps")
        self.discover_btn.clicked.connect(self._discover_windows_apps)
        app_ops.addWidget(self.discover_btn)

        self.discovered_combo = QComboBox()
        self.discovered_combo.currentIndexChanged.connect(self._on_discovered_pick_changed)
        self.discovered_combo.setMinimumWidth(220)
        app_ops.addWidget(self.discovered_combo)

        app_ops.addStretch(1)
        root.addLayout(app_ops)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(DEFAULT_THEME.spacing.md)
        form.setVerticalSpacing(DEFAULT_THEME.spacing.sm)

        self.new_app_name = QLineEdit()
        self.new_app_name.setPlaceholderText("App display name")
        self.new_app_name.setMaximumWidth(280)
        form.addRow("Name:", self.new_app_name)

        self.new_app_exe = QLineEdit()
        self.new_app_exe.setPlaceholderText("C:/Path/To/App.exe")
        self.new_app_exe.setMaximumWidth(420)
        form.addRow("Exe:", self.new_app_exe)

        self.new_app_title_re = QLineEdit()
        self.new_app_title_re.setPlaceholderText(".*App Name.*")
        self.new_app_title_re.setMaximumWidth(360)
        form.addRow("Title Regex:", self.new_app_title_re)

        self.new_app_tasks = QLineEdit()
        self.new_app_tasks.setPlaceholderText("open settings, search")
        self.new_app_tasks.setMaximumWidth(420)
        form.addRow("Tasks CSV:", self.new_app_tasks)

        root.addLayout(form)

        register_row = QHBoxLayout()
        register_row.setSpacing(DEFAULT_THEME.spacing.sm)

        self.new_app_electron = QCheckBox("Electron")
        register_row.addWidget(self.new_app_electron)

        self.register_btn = QPushButton("Register Only")
        self.register_btn.clicked.connect(self._register_picked_app)
        register_row.addWidget(self.register_btn)

        register_row.addStretch(1)
        root.addLayout(register_row)

        probe_ops = QHBoxLayout()
        self.probe_btn = QPushButton("Probe App (selected ready app or Name field)")
        self.probe_btn.clicked.connect(self._probe_active_app)
        probe_ops.addWidget(self.probe_btn)

        probe_ops.addWidget(QLabel("Probe Time (s):"))
        self.probe_time_input = QLineEdit("180")
        self.probe_time_input.setFixedWidth(60)
        probe_ops.addWidget(self.probe_time_input)

        self.clear_cache_checkbox = QCheckBox("Clear cache first")
        probe_ops.addWidget(self.clear_cache_checkbox)
        probe_ops.addStretch(1)
        root.addLayout(probe_ops)

        helper = QTextEdit()
        helper.setReadOnly(True)
        helper.setPlainText(
            "Crawler flow: Scan/Browse executable -> auto register entrypoint -> run probe to build cache/fingerprints/exposure paths.\n"
            "After probe completion, apps with full cache + exposure-path readiness appear in Automation-Ready Apps."
        )
        helper.setMaximumHeight(76)
        root.addWidget(helper)

        catalog_header = QHBoxLayout()
        self.automation_ready_count_label = QLabel("Automation-Ready Apps (0)")
        self.automation_ready_count_label.setProperty("component", "sectionTitle")
        catalog_header.addWidget(self.automation_ready_count_label)
        catalog_header.addStretch(1)

        self.refresh_catalog_btn = QPushButton("Refresh Automation Catalog")
        self.refresh_catalog_btn.setProperty("variant", "ghost")
        self.refresh_catalog_btn.clicked.connect(self._refresh_app_choices)
        catalog_header.addWidget(self.refresh_catalog_btn)
        root.addLayout(catalog_header)

        catalog_splitter = QSplitter(Qt.Horizontal)

        self.automation_app_list = QListWidget()
        self.automation_app_list.currentItemChanged.connect(
            lambda current, _previous: self._on_automation_app_selected(current)
        )
        catalog_splitter.addWidget(self.automation_app_list)

        self.automation_tree = QTreeWidget()
        self.automation_tree.setHeaderLabels(["Element", "Details"])
        catalog_splitter.addWidget(self.automation_tree)
        catalog_splitter.setStretchFactor(0, 2)
        catalog_splitter.setStretchFactor(1, 5)
        root.addWidget(catalog_splitter, 1)

        self.automation_tree_summary = QLabel("Select an automation-ready app to inspect its cached automation tree.")
        self.automation_tree_summary.setProperty("component", "caption")
        self.automation_tree_summary.setWordWrap(True)
        root.addWidget(self.automation_tree_summary)

        return page

    def _build_memory_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
        )
        root.setSpacing(DEFAULT_THEME.spacing.md)

        title = QLabel("Memory")
        title.setProperty("component", "sectionTitle")
        root.addWidget(title)

        self.memory_tab = QTextEdit()
        self.memory_tab.setReadOnly(True)
        root.addWidget(self.memory_tab, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
        )
        root.setSpacing(DEFAULT_THEME.spacing.md)

        title = QLabel("Settings")
        title.setProperty("component", "sectionTitle")
        root.addWidget(title)

        app_note = QLabel(
            "App routing is automatic. The agent chooses from discovered automation-capable apps based on your command. "
            "If you explicitly mention an app in your command, it will prefer that app."
        )
        app_note.setProperty("component", "caption")
        app_note.setWordWrap(True)
        root.addWidget(app_note)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(
            "Keyboard shortcuts:\n"
            "Alt+1 Assistant\n"
            "Alt+2 Tasks and Runs\n"
            "Alt+3 Crawler\n"
            "Alt+4 Memory\n"
            "Alt+5 Settings\n"
            "Ctrl+L Toggle left nav\n"
            "Ctrl+J Toggle context panel\n"
            "Ctrl+K Focus composer"
        )
        root.addWidget(notes, 1)

        return page

    def _build_context_panel(self) -> QWidget:
        panel = QWidget()
        panel.setProperty("component", "contextPanel")
        panel.setMinimumWidth(180)
        panel.setMaximumWidth(320)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
        )
        layout.setSpacing(DEFAULT_THEME.spacing.md)

        heading = QLabel("Context")
        heading.setProperty("component", "sectionTitle")
        layout.addWidget(heading)

        self.active_task_card = ActiveTaskCard()
        layout.addWidget(self.active_task_card)

        self.plan_card = PlanCard()
        layout.addWidget(self.plan_card)

        self.health_card = HealthCard()
        layout.addWidget(self.health_card)

        layout.addStretch(1)
        return panel

    def _configure_keyboard_shortcuts(self) -> None:
        self._shortcuts.clear()

        def _bind(sequence: str, callback) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

        _bind("Alt+1", lambda: self._set_mode("assistant"))
        _bind("Alt+2", lambda: self._set_mode("tasks"))
        _bind("Alt+3", lambda: self._set_mode("apps"))
        _bind("Alt+4", lambda: self._set_mode("memory"))
        _bind("Alt+5", lambda: self._set_mode("settings"))
        _bind("Ctrl+L", self._toggle_nav)
        _bind("Ctrl+J", self._toggle_context_panel)
        _bind("Ctrl+K", self.input_box.setFocus)

    def _configure_tab_order(self) -> None:
        self.setTabOrder(self.dry_checkbox, self.ptt_btn)
        self.setTabOrder(self.ptt_btn, self.input_box)
        self.setTabOrder(self.input_box, self.send_btn)
        self.setTabOrder(self.send_btn, self.scan_executables_btn)
        self.setTabOrder(self.scan_executables_btn, self.scan_limit_input)
        self.setTabOrder(self.scan_limit_input, self.browse_exe_btn)
        self.setTabOrder(self.browse_exe_btn, self.executable_combo)
        self.setTabOrder(self.executable_combo, self.auto_onboard_checkbox)
        self.setTabOrder(self.auto_onboard_checkbox, self.auto_onboard_btn)
        self.setTabOrder(self.auto_onboard_btn, self.discover_btn)
        self.setTabOrder(self.discover_btn, self.discovered_combo)
        self.setTabOrder(self.discovered_combo, self.new_app_name)
        self.setTabOrder(self.new_app_name, self.new_app_exe)
        self.setTabOrder(self.new_app_exe, self.new_app_title_re)
        self.setTabOrder(self.new_app_title_re, self.new_app_tasks)
        self.setTabOrder(self.new_app_tasks, self.register_btn)
        self.setTabOrder(self.register_btn, self.probe_btn)
        self.setTabOrder(self.probe_btn, self.probe_time_input)
        self.setTabOrder(self.probe_time_input, self.refresh_catalog_btn)
        self.setTabOrder(self.refresh_catalog_btn, self.automation_app_list)

    def _set_mode(self, mode: str) -> None:
        target = str(mode or "assistant").strip().lower()
        index = self.page_index.get(target, self.page_index["assistant"])
        self.mode_stack.setCurrentIndex(index)

        for name, button in self.nav_buttons.items():
            active = name == target
            button.setChecked(active)
            button.setProperty("active", "true" if active else "false")
            style = button.style()
            if style is not None:
                style.unpolish(button)
                style.polish(button)

    def _toggle_nav(self) -> None:
        self._nav_expanded = not self._nav_expanded
        width = (
            DEFAULT_THEME.layout.nav_expanded_width
            if self._nav_expanded
            else DEFAULT_THEME.layout.nav_collapsed_width
        )
        self.left_nav.setFixedWidth(width)
        self.nav_toggle_btn.setText("Nav -" if self._nav_expanded else "Nav +")

    def _toggle_context_panel(self) -> None:
        self._context_visible = not self._context_visible
        self.context_panel.setVisible(self._context_visible)

        if self._context_visible:
            total = sum(self.main_splitter.sizes()) or 1024
            right = DEFAULT_THEME.layout.context_panel_width
            left = max(320, total - right)
            self.main_splitter.setSizes([left, right])
            self.context_toggle_btn.setText("Context -")
        else:
            total = sum(self.main_splitter.sizes()) or 1024
            self.main_splitter.setSizes([total, 0])
            self.context_toggle_btn.setText("Context +")

    def _clear_chat(self) -> None:
        self.chat_container.clear_messages()
        self._append_assistant_note("Chat cleared.")

    def _set_runtime_status(self, status: str) -> None:
        normalized = str(status or "idle").strip().lower()
        if normalized not in {"idle", "running", "error"}:
            normalized = "idle"
        self._runtime_status = normalized
        self.runtime_chip.set_status(normalized)

    def _toggle_dry_run(self, state: int):
        self.agent.dry_run = bool(state)
        logger.info("Chat dry-run toggled to %s", self.agent.dry_run)
        self._append_assistant_note(f"Dry-run set to {self.agent.dry_run}")
        self._refresh_panels()

    def _append_assistant_note(self, line: str):
        self.chat_container.assistant_message(str(line or ""))

    def _send(self):
        command = self.input_box.toPlainText().strip()
        if not command:
            return

        self.input_box.clear()
        self._dispatch_command(command, source="You")

    def _dispatch_command(self, command: str, source: str):
        if self._thread and self._thread.isRunning():
            self._append_assistant_note("SARA: Busy processing previous command")
            logger.warning("Command ignored while busy source=%s command=%r", source, command)
            return

        logger.info("Dispatch command source=%s dry_run=%s command=%r", source, self.agent.dry_run, command)
        self.chat_container.user_message(command)
        self._set_runtime_status("running")
        self.active_task_card.set_task(command, status="running")
        self.voice_bubble.set_state("processing")
        self.send_btn.setEnabled(False)
        self.ptt_btn.setEnabled(False)
        self._saw_live_progress = False

        worker = _Worker(self.agent, command)
        thread = QThread()
        self._worker = worker
        self._thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_result)
        worker.error.connect(self._on_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()

    def _on_result(self, result):
        self.send_btn.setEnabled(True)
        self.ptt_btn.setEnabled(True)
        logger.info(
            "Command result intent=%s success=%s tier=%s error=%s plan_steps=%d",
            result.intent,
            result.execution_success,
            result.tier_used,
            result.error,
            len(result.plan),
        )
        if getattr(result, "progress_events", None) and not self._saw_live_progress:
            self._append_assistant_note("SARA steps:")
            for line in result.progress_events[:30]:
                self._append_assistant_note(f"  {line}")
        self._saw_live_progress = False

        response_text = str(result.response_text or "").strip() or "No response generated."
        self._append_assistant_note(response_text)

        if result.error:
            self._last_error = str(result.error)
            self._append_assistant_note(f"ERROR: {self._last_error}")
            self._set_runtime_status("error")
            self.active_task_card.set_task(result.intent or "Failed", status="error")
            self.voice_bubble.set_state("error")
        else:
            self._last_error = ""
            self._set_runtime_status("idle")
            self.active_task_card.set_task(result.intent or "Completed", status="idle")
            self.voice_bubble.set_state("idle")

        if self.voice_service is not None and response_text:
            self.voice_bubble.set_state("speaking")
            self.voice_service.speak(response_text)
            QTimer.singleShot(DEFAULT_THEME.motion.slow_ms, lambda: self.voice_bubble.set_state("idle"))

        self._refresh_panels(result)

    def _on_error(self, error: str):
        self.send_btn.setEnabled(True)
        self.ptt_btn.setEnabled(True)
        self._saw_live_progress = False
        self._last_error = str(error or "")
        logger.error("Command worker failed: %s", error)
        self._append_assistant_note(f"ERROR: {error}")
        self._set_runtime_status("error")
        self.active_task_card.set_task("Command failed", status="error")
        self.voice_bubble.set_state("error")
        self._refresh_panels()

    def _on_progress(self, line: str):
        text = (line or "").strip()
        if not text:
            return
        if not self._saw_live_progress:
            self._append_assistant_note("SARA steps (live):")
            self._saw_live_progress = True
        self._append_assistant_note(f"  {text}")

    def _push_to_talk(self):
        if self.voice_service is None:
            self._append_assistant_note("SARA: Voice unavailable")
            logger.warning("PTT requested but voice service unavailable")
            return
        if self._listen_thread and self._listen_thread.isRunning():
            self._append_assistant_note("SARA: Already listening")
            logger.warning("PTT requested while already listening")
            return

        self._append_assistant_note("SARA: Listening...")
        self.voice_bubble.set_state("listening")
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
            logger.info("PTT finished with no captured speech")
            self._append_assistant_note("SARA: No speech captured")
            self.voice_bubble.set_state("idle")
            return
        logger.info("PTT captured command=%r", cmd)
        self.voice_bubble.set_state("processing")
        self._dispatch_command(cmd, source="Voice")

    def _on_ptt_error(self, error: str):
        self.ptt_btn.setEnabled(True)
        self._last_error = str(error or "")
        logger.error("PTT failed: %s", error)
        self._append_assistant_note(f"ERROR: Voice failed: {error}")
        self._set_runtime_status("error")
        self.voice_bubble.set_state("error")
        self._refresh_panels()

    def _start_wake_loop_if_enabled(self):
        if self.voice_service is None:
            self.voice_label.setText("Wake: voice unavailable")
            self.voice_bubble.set_state("idle")
            logger.info("Wake loop unavailable: no voice service")
            return
        if not ENABLE_WAKE_LOOP:
            self.voice_label.setText("Wake: disabled by config")
            self.voice_bubble.set_state("idle")
            logger.info("Wake loop disabled by config")
            return

        self.wake_controller = WakeController(getattr(self.voice_service, "wake_word", "hey sara"))
        self.voice_service.start_listening(
            on_command=self._emit_wake_command,
            wake_controller=self.wake_controller,
            on_state_change=self._emit_voice_state,
        )
        self.voice_label.setText("Wake: enabled")
        self.voice_bubble.set_state("idle")
        logger.info("Wake loop started")

    def _emit_voice_state(self, state: str):
        self.voice_state_changed.emit(state)

    def _emit_wake_command(self, command: str):
        self.wake_command_detected.emit(command)

    def _map_voice_state(self, state: str) -> str:
        normalized = str(state or "").strip().lower()
        if "error" in normalized or "fail" in normalized:
            return "error"
        if "speak" in normalized:
            return "speaking"
        if "process" in normalized or "think" in normalized:
            return "processing"
        if "listen" in normalized or "wake" in normalized:
            return "listening"
        return "idle"

    def _on_voice_state(self, state: str):
        self.voice_label.setText(f"Wake: {state}")
        self.voice_bubble.set_state(self._map_voice_state(state))

    def _on_wake_command(self, command: str):
        cmd = (command or "").strip()
        if not cmd:
            return
        logger.info("Wake command captured=%r", cmd)
        self._append_assistant_note("Wake command detected.")
        self._dispatch_command(cmd, source="Wake")

    def _refresh_panels(self, last_result=None):
        if last_result is not None:
            self.plan_tab.setPlainText(json.dumps(last_result.plan, indent=2, ensure_ascii=False))
            self.plan_card.set_plan_lines(self._summarize_plan(last_result.plan))

        self.memory_tab.setPlainText(
            json.dumps(self.agent.get_memory_summary(), indent=2, ensure_ascii=False)
        )
        status_payload = self.agent.get_system_status()
        self.status_tab.setPlainText(
            json.dumps(status_payload, indent=2, ensure_ascii=False)
        )
        self._render_probe_dashboard()

        mode = "Dry-run" if self.agent.dry_run else "Live"
        self.health_card.set_health(
            mode=mode,
            wake_state=self.voice_label.text().replace("Wake: ", ""),
            last_error=self._last_error,
        )

    def _summarize_plan(self, plan: Iterable[Any]) -> List[str]:
        lines: List[str] = []
        for step in list(plan or [])[:5]:
            if not isinstance(step, dict):
                value = str(step).strip()
                if value:
                    lines.append(value)
                continue

            if isinstance(step.get("action"), dict):
                action = step.get("action", {})
                action_type = str(action.get("action") or action.get("action_type") or "step").strip().upper()
                target = str(action.get("target") or action.get("keys") or "").strip()
            else:
                action_type = str(step.get("action") or step.get("action_type") or "step").strip().upper()
                target = str(step.get("target") or step.get("keys") or "").strip()

            if target:
                lines.append(f"{action_type}: {target}")
            else:
                lines.append(action_type)
        return lines

    def _selected_ready_app_name(self) -> str:
        item = self.automation_app_list.currentItem()
        if item is None:
            return ""
        value = item.data(Qt.UserRole)
        return str(value or "").strip()

    def _analyze_app_cache_readiness(self, app_name: str, task_match_threshold: float = 0.65) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "app_name": str(app_name or "").strip(),
            "ready": False,
            "cache_path": "",
            "elements_count": 0,
            "exposure_path_count": 0,
            "task_match_hits": 0,
            "task_match_total": 0,
            "exposure_path_integrity_ok": False,
        }

        target = report["app_name"]
        if not target:
            return report

        try:
            from src.automation import matcher, storage
            from src.harness import config as harness_config
        except Exception:
            return report

        cache_path = storage.get_cache_path(target)
        report["cache_path"] = str(cache_path or "")
        if not cache_path or not os.path.exists(cache_path):
            return report

        try:
            with open(cache_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return report

        elements = payload.get("elements", {}) if isinstance(payload, dict) else {}
        if not isinstance(elements, dict) or not elements:
            return report

        report["elements_count"] = len(elements)

        exposure_count = 0
        integrity_ok = True
        for node in elements.values():
            if not isinstance(node, dict):
                continue
            exposure_path = node.get("exposure_path", [])
            if not isinstance(exposure_path, list) or not exposure_path:
                continue
            exposure_count += 1
            for step in exposure_path:
                if not isinstance(step, dict):
                    continue
                step_fp = str(step.get("fingerprint", "")).strip()
                if step_fp and step_fp not in elements:
                    integrity_ok = False
                    break
            if not integrity_ok:
                break

        report["exposure_path_count"] = exposure_count
        report["exposure_path_integrity_ok"] = integrity_ok

        tasks = [str(task or "").strip() for task in harness_config.get_tasks_for_app(target)]
        tasks = [task for task in tasks if task]
        report["task_match_total"] = len(tasks)

        task_hits = 0
        for task in tasks:
            try:
                if matcher.find_cached_element(target, task, min_confidence=task_match_threshold):
                    task_hits += 1
            except Exception:
                continue

        report["task_match_hits"] = task_hits
        has_full_task_coverage = not tasks or task_hits == len(tasks)
        report["ready"] = bool(exposure_count > 0 and integrity_ok and has_full_task_coverage)
        return report

    def _refresh_app_choices(self):
        previous = self._selected_ready_app_name()
        self._automation_catalog = {}

        app_names = _app_choices()
        ready_reports: List[Dict[str, Any]] = []
        for app_name in app_names:
            report = self._analyze_app_cache_readiness(app_name)
            self._automation_catalog[app_name] = report
            if bool(report.get("ready")):
                ready_reports.append(report)

        ready_reports.sort(key=lambda item: str(item.get("app_name", "")).lower())

        self.automation_app_list.blockSignals(True)
        self.automation_app_list.clear()
        selected_row = -1
        for idx, report in enumerate(ready_reports):
            app_name = str(report.get("app_name", "")).strip()
            task_hits = int(report.get("task_match_hits", 0) or 0)
            task_total = int(report.get("task_match_total", 0) or 0)
            elements_count = int(report.get("elements_count", 0) or 0)
            exposure_count = int(report.get("exposure_path_count", 0) or 0)
            label = (
                f"{app_name} | tasks {task_hits}/{task_total} | "
                f"nodes {elements_count} | paths {exposure_count}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, app_name)
            self.automation_app_list.addItem(item)
            if previous and app_name.lower() == previous.lower():
                selected_row = idx

        if self.automation_app_list.count() == 0:
            placeholder = QListWidgetItem("No automation-ready apps yet. Run probe for an app.")
            placeholder.setData(Qt.UserRole, "")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsSelectable)
            self.automation_app_list.addItem(placeholder)
            self.automation_tree.clear()
            self.automation_tree_summary.setText(
                "No automation-ready app found. Use Register + Probe to build cache and exposure paths first."
            )
        else:
            self.automation_app_list.setCurrentRow(selected_row if selected_row >= 0 else 0)

        self.automation_app_list.blockSignals(False)
        self.automation_ready_count_label.setText(
            f"Automation-Ready Apps ({len(ready_reports)})"
        )

        current = self.automation_app_list.currentItem()
        if current is not None and str(current.data(Qt.UserRole) or "").strip():
            self._on_automation_app_selected(current)

    def _on_automation_app_selected(self, item: Optional[QListWidgetItem]) -> None:
        if item is None:
            self.automation_tree.clear()
            self.automation_tree_summary.setText(
                "Select an automation-ready app to inspect its cached automation tree."
            )
            return

        app_name = str(item.data(Qt.UserRole) or "").strip()
        if not app_name:
            self.automation_tree.clear()
            self.automation_tree_summary.setText(
                "Select an automation-ready app to inspect its cached automation tree."
            )
            return

        self._render_automation_tree(app_name)

    def _render_automation_tree(self, app_name: str) -> None:
        report = self._automation_catalog.get(app_name) or self._analyze_app_cache_readiness(app_name)
        cache_path = str(report.get("cache_path", "") or "")
        if not cache_path or not os.path.exists(cache_path):
            self.automation_tree.clear()
            self.automation_tree_summary.setText(f"No cache file available for {app_name}.")
            return

        try:
            with open(cache_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            self.automation_tree.clear()
            self.automation_tree_summary.setText(f"Failed to parse cache for {app_name}: {exc}")
            return

        elements = payload.get("elements", {}) if isinstance(payload, dict) else {}
        if not isinstance(elements, dict) or not elements:
            self.automation_tree.clear()
            self.automation_tree_summary.setText(f"Cache for {app_name} has no elements.")
            return

        children_map: Dict[str, List[str]] = {}
        roots: List[str] = []
        for fingerprint, node in elements.items():
            if not isinstance(node, dict):
                roots.append(str(fingerprint))
                continue
            parent_fp = str(node.get("parent_fingerprint", "")).strip()
            fp = str(fingerprint).strip()
            if parent_fp and parent_fp in elements:
                children_map.setdefault(parent_fp, []).append(fp)
            else:
                roots.append(fp)

        def _sort_key(fp: str) -> str:
            node = elements.get(fp, {}) if isinstance(elements.get(fp, {}), dict) else {}
            name = str(node.get("name", "")).strip().lower()
            control_type = str(node.get("control_type", "")).strip().lower()
            return f"{name}|{control_type}|{fp.lower()}"

        roots = sorted(set(roots), key=_sort_key)
        for parent_fp, child_list in list(children_map.items()):
            children_map[parent_fp] = sorted(set(child_list), key=_sort_key)

        self.automation_tree.clear()
        seen: set[str] = set()
        max_nodes = 1500
        rendered = 0

        def _append_node(parent_item: Optional[QTreeWidgetItem], fingerprint: str) -> None:
            nonlocal rendered
            if fingerprint in seen or rendered >= max_nodes:
                return
            seen.add(fingerprint)
            node = elements.get(fingerprint, {}) if isinstance(elements.get(fingerprint, {}), dict) else {}
            label = self._build_tree_label(node)
            meta = str(node.get("control_type", "Unknown")).strip() or "Unknown"
            details = f"{meta} | fp={fingerprint}"

            tree_item = QTreeWidgetItem([label, details])
            if parent_item is None:
                self.automation_tree.addTopLevelItem(tree_item)
            else:
                parent_item.addChild(tree_item)

            rendered += 1
            for child_fp in children_map.get(fingerprint, []):
                _append_node(tree_item, child_fp)

        for root_fp in roots:
            _append_node(None, root_fp)
            if rendered >= max_nodes:
                break

        if rendered >= max_nodes:
            self.automation_tree.addTopLevelItem(
                QTreeWidgetItem(["... truncated ...", "Node limit reached while rendering tree"])
            )

        self.automation_tree.expandToDepth(1)
        task_hits = int(report.get("task_match_hits", 0) or 0)
        task_total = int(report.get("task_match_total", 0) or 0)
        self.automation_tree_summary.setText(
            f"{app_name}: rendered {rendered} nodes | task coverage {task_hits}/{task_total}"
        )

    def _build_tree_label(self, node: Dict[str, Any]) -> str:
        name = str(node.get("name", "")).strip()
        control_type = str(node.get("control_type", "")).strip()
        automation_id = str(node.get("automation_id", "")).strip()

        parts: List[str] = []
        if name:
            parts.append(name)
        if control_type:
            parts.append(f"[{control_type}]")
        if automation_id:
            parts.append(f"id={automation_id}")

        if parts:
            return " ".join(parts)
        return "<unnamed element>"

    def _discover_windows_apps(self):
        try:
            from src.harness.windows_app_discovery import discover_apps

            self._discovered_apps = discover_apps(max_results=500)
        except Exception as exc:
            self._append_assistant_note(f"ERROR: Discover apps failed: {exc}")
            self._set_runtime_status("error")
            return

        self.discovered_combo.blockSignals(True)
        self.discovered_combo.clear()
        self.discovered_combo.addItem("Select installed app...", None)
        for app in self._discovered_apps:
            label = f"{app.get('name', '')} [{app.get('source', '')}]"
            self.discovered_combo.addItem(label, app)
        self.discovered_combo.blockSignals(False)

        if len(self._discovered_apps) > 0:
            self.discovered_combo.setCurrentIndex(1)
            self._append_assistant_note(f"SARA: Discovered {len(self._discovered_apps)} apps from registry/start menu")
            self._set_runtime_status("idle")
        else:
            self._append_assistant_note("SARA: No discoverable desktop apps were found")

    def _scan_all_executables(self):
        if self._scan_thread and self._scan_thread.isRunning():
            self._append_assistant_note("SARA: Executable scan already running")
            return

        try:
            max_results = max(0, int(float((self.scan_limit_input.text() or "0").strip() or "0")))
        except Exception:
            max_results = 0

        self.scan_executables_btn.setEnabled(False)
        self.browse_exe_btn.setEnabled(False)
        self.auto_onboard_btn.setEnabled(False)
        self._set_runtime_status("running")
        self.active_task_card.set_task("Scan executables", status="running")
        if max_results > 0:
            self._append_assistant_note(f"SARA: Scanning system executables (limit={max_results})")
        else:
            self._append_assistant_note("SARA: Scanning all system executables (no limit)")

        worker = _ExecutableScanWorker(max_results=max_results)
        thread = QThread()
        self._scan_worker = worker
        self._scan_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_executable_scan_done)
        worker.error.connect(self._on_executable_scan_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()

    def _on_executable_scan_done(self, rows):
        self.scan_executables_btn.setEnabled(True)
        self.browse_exe_btn.setEnabled(True)
        self.auto_onboard_btn.setEnabled(True)

        normalized_rows: List[Dict[str, str]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            exe = str(row.get("exe", "")).strip()
            if not exe or not os.path.exists(exe):
                continue
            name = str(row.get("name", "")).strip() or os.path.splitext(os.path.basename(exe))[0]
            source = str(row.get("source", "")).strip() or "filesystem_scan"
            normalized_rows.append({"name": name, "exe": exe, "source": source})

        self._executable_inventory = normalized_rows

        self._suspend_auto_onboard = True
        self.executable_combo.blockSignals(True)
        self.executable_combo.clear()
        self.executable_combo.addItem("Select executable...", None)
        for item in self._executable_inventory:
            label = f"{item.get('name', '')} [{item.get('source', '')}] -> {item.get('exe', '')}"
            self.executable_combo.addItem(label, item)
        self.executable_combo.setCurrentIndex(0)
        self.executable_combo.blockSignals(False)
        self._suspend_auto_onboard = False

        if self._executable_inventory:
            self._append_assistant_note(
                f"SARA: Executable scan complete. Found {len(self._executable_inventory)} executables."
            )
            self.active_task_card.set_task("Executable scan completed", status="idle")
        else:
            self._append_assistant_note("SARA: Executable scan complete. No executable files were found.")
            self.active_task_card.set_task("Executable scan found nothing", status="idle")
        self._set_runtime_status("idle")

    def _on_executable_scan_error(self, error: str):
        self.scan_executables_btn.setEnabled(True)
        self.browse_exe_btn.setEnabled(True)
        self.auto_onboard_btn.setEnabled(True)
        self._last_error = str(error or "")
        self._append_assistant_note(f"ERROR: Executable scan failed: {error}")
        self._set_runtime_status("error")
        self.active_task_card.set_task("Executable scan failed", status="error")

    def _browse_executable(self):
        exe_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select executable for crawler onboarding",
            r"C:\\",
            "Executable Files (*.exe)",
        )
        if not exe_path:
            return

        exe_path = os.path.normpath(exe_path)
        if not os.path.exists(exe_path):
            self._append_assistant_note(f"ERROR: Executable not found: {exe_path}")
            return

        item = {
            "name": os.path.splitext(os.path.basename(exe_path))[0],
            "exe": exe_path,
            "source": "manual_browse",
        }

        existing_index = -1
        for idx in range(self.executable_combo.count()):
            current = self.executable_combo.itemData(idx)
            if isinstance(current, dict) and str(current.get("exe", "")).strip().lower() == exe_path.lower():
                existing_index = idx
                break

        self._suspend_auto_onboard = True
        if existing_index < 0:
            label = f"{item.get('name', '')} [{item.get('source', '')}] -> {item.get('exe', '')}"
            self.executable_combo.addItem(label, item)
            existing_index = self.executable_combo.count() - 1
        self.executable_combo.setCurrentIndex(existing_index)
        self._suspend_auto_onboard = False

        self._apply_discovery_item(item)
        if self.auto_onboard_checkbox.isChecked():
            self._auto_onboard_selected_executable()

    def _on_executable_pick_changed(self, _index: int):
        item = self.executable_combo.currentData()
        if not isinstance(item, dict):
            return

        self._apply_discovery_item(item)
        if not self._suspend_auto_onboard and self.auto_onboard_checkbox.isChecked():
            self._auto_onboard_selected_executable()

    def _on_discovered_pick_changed(self, _index: int):
        item = self.discovered_combo.currentData()
        if not isinstance(item, dict):
            return

        self._apply_discovery_item(item)

    def _apply_discovery_item(self, item: Dict[str, str]) -> None:
        name = str(item.get("name", "")).strip()
        exe = os.path.normpath(str(item.get("exe", "")).strip())

        if name:
            self.new_app_name.setText(name)
        if exe:
            self.new_app_exe.setText(exe)

        title_re = self._build_title_regex(name=name, exe_path=exe)
        self.new_app_title_re.setText(title_re)

    def _build_title_regex(self, name: str, exe_path: str) -> str:
        safe_name = str(name or "").strip() or os.path.splitext(os.path.basename(exe_path or ""))[0]
        exe_name = os.path.basename(str(exe_path or "")).strip().lower()

        if exe_name == "explorer.exe":
            return r".*(File Explorer|Explorer|This PC|Desktop|Downloads|Documents|Pictures|Videos|Music).*"
        if exe_name in {"cmd.exe", "powershell.exe", "pwsh.exe", "wt.exe"}:
            return r".*"
        if safe_name:
            return f".*{re.escape(safe_name)}.*"
        return r".*"

    def _default_tasks_for_app(self, exe_path: str) -> List[str]:
        exe_name = os.path.basename(str(exe_path or "")).strip().lower()
        if exe_name == "explorer.exe":
            return ["open quick access", "open this pc", "search", "open downloads", "open documents"]
        return ["open settings", "open help", "search", "file", "edit", "view"]

    def _resolve_unique_app_name(self, app_name: str, exe_path: str) -> str:
        from src.harness import config as harness_config

        base = re.sub(r"[^A-Za-z0-9_. -]", "", str(app_name or "").strip())
        if not base:
            base = os.path.splitext(os.path.basename(exe_path))[0]

        candidate = base
        counter = 2
        while True:
            existing = harness_config.get_app_config(candidate)
            if not existing:
                return candidate

            existing_exe = os.path.normpath(str(existing.get("exe", "")).strip())
            if existing_exe and existing_exe.lower() == os.path.normpath(exe_path).lower():
                return candidate

            candidate = f"{base}_{counter}"
            counter += 1

    def _register_app_from_form(self) -> Optional[str]:
        name = self.new_app_name.text().strip()
        exe = os.path.normpath(self.new_app_exe.text().strip())
        title_re = self.new_app_title_re.text().strip()
        tasks_raw = self.new_app_tasks.text().strip()

        if not exe:
            self._append_assistant_note("SARA: Select or browse an executable first")
            return None
        if not os.path.exists(exe):
            self._append_assistant_note(f"SARA: Executable path is invalid: {exe}")
            return None

        if not name:
            name = os.path.splitext(os.path.basename(exe))[0]

        if not title_re:
            title_re = self._build_title_regex(name=name, exe_path=exe)
            self.new_app_title_re.setText(title_re)

        tasks = [part.strip() for part in tasks_raw.split(",") if part.strip()]
        if not tasks:
            tasks = self._default_tasks_for_app(exe)
            self.new_app_tasks.setText(", ".join(tasks))

        app_name = self._resolve_unique_app_name(name, exe)
        self.new_app_name.setText(app_name)

        try:
            from src.harness import config as harness_config

            ok = harness_config.register_app(
                app_name=app_name,
                exe=exe,
                title_re=title_re,
                tasks=tasks,
                electron=bool(self.new_app_electron.isChecked()),
                persist=True,
            )
        except Exception as exc:
            self._append_assistant_note(f"ERROR: App registration failed: {exc}")
            self._set_runtime_status("error")
            return None

        if not ok:
            self._append_assistant_note("ERROR: App registration failed")
            self._set_runtime_status("error")
            return None

        self._refresh_app_choices()
        return app_name

    def _register_picked_app(self):
        app_name = self._register_app_from_form()
        if not app_name:
            return
        self._append_assistant_note(f"SARA: Registered app {app_name}. Run probe to make it automation-ready.")
        self._set_runtime_status("idle")

    def _auto_onboard_selected_executable(self):
        if self._probe_thread and self._probe_thread.isRunning():
            self._append_assistant_note("SARA: Probe already running")
            return

        item = self.executable_combo.currentData()
        if isinstance(item, dict):
            self._apply_discovery_item(item)

        app_name = self._register_app_from_form()
        if not app_name:
            return

        self._append_assistant_note(f"SARA: Registered {app_name}. Starting crawler probe now...")
        self._start_probe_for_app(app_name, origin="auto_onboard")

    def _set_crawler_controls_enabled(self, enabled: bool) -> None:
        for attr in [
            "probe_btn",
            "discover_btn",
            "register_btn",
            "scan_executables_btn",
            "browse_exe_btn",
            "auto_onboard_btn",
            "discovered_combo",
            "executable_combo",
            "scan_limit_input",
            "new_app_name",
            "new_app_exe",
            "new_app_title_re",
            "new_app_tasks",
            "new_app_electron",
            "probe_time_input",
            "clear_cache_checkbox",
            "auto_onboard_checkbox",
            "refresh_catalog_btn",
            "automation_app_list",
        ]:
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(enabled)

    def _probe_active_app(self):
        app_name = self._selected_ready_app_name() or self.new_app_name.text().strip()
        if not app_name:
            self._append_assistant_note(
                "SARA: Pick an app from Automation-Ready Apps, or fill Name and register before probing."
            )
            return

        try:
            from src.harness import config as harness_config

            if not harness_config.get_app_config(app_name):
                self._append_assistant_note(
                    f"SARA: App '{app_name}' is not registered yet. Use Register Only first."
                )
                return
        except Exception as exc:
            self._append_assistant_note(f"ERROR: Unable to validate app registration: {exc}")
            return

        self._start_probe_for_app(app_name, origin="manual")

    def _start_probe_for_app(self, app_name: str, origin: str = "manual"):
        if self._probe_thread and self._probe_thread.isRunning():
            self._append_assistant_note("SARA: Probe already running")
            return

        try:
            max_time = max(30, int(float(self.probe_time_input.text().strip() or "180")))
        except Exception:
            max_time = 180

        clear_cache = bool(self.clear_cache_checkbox.isChecked())

        self._active_probe_origin = str(origin or "manual")
        self._set_crawler_controls_enabled(False)
        self._set_runtime_status("running")
        self.active_task_card.set_task(f"Probe {app_name}", status="running")
        self._append_assistant_note(f"SARA: Probing {app_name} (time={max_time}s, clear_cache={clear_cache})")

        worker = _ProbeWorker(app_name=app_name, max_time=max_time, clear_cache=clear_cache)
        thread = QThread()
        self._probe_worker = worker
        self._probe_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_probe_done)
        worker.error.connect(self._on_probe_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()

    def _on_probe_done(self, report):
        self._set_crawler_controls_enabled(True)

        app_name = ""
        if isinstance(report, dict):
            app_name = str(report.get("app_name", "")).strip()
            self._probe_reports.insert(0, report)
            self._probe_reports = self._probe_reports[:30]

            discovery = report.get("discovery", {}) if isinstance(report.get("discovery", {}), dict) else {}
            cache = report.get("cache_analysis", {}) if isinstance(report.get("cache_analysis", {}), dict) else {}
            self._append_assistant_note(
                "SARA: Probe done | "
                f"discovered={discovery.get('discovered', 0)} "
                f"hits={cache.get('task_match_hits', 0)} "
                f"misses={cache.get('task_match_misses', 0)}"
            )

        if app_name:
            self._refresh_app_choices()

        self._set_runtime_status("idle")
        self.active_task_card.set_task("Probe completed", status="idle")
        self._refresh_panels()

        if getattr(self, "_active_probe_origin", "manual") == "auto_onboard":
            if app_name:
                self._append_assistant_note(
                    f"SARA: {app_name} probe completed. Check Automation-Ready Apps for cache readiness."
                )
            self._set_mode("assistant")
        else:
            self._set_mode("tasks")

    def _on_probe_error(self, error: str):
        self._set_crawler_controls_enabled(True)
        self._last_error = str(error or "")
        self._append_assistant_note(f"ERROR: Probe failed: {error}")
        self._set_runtime_status("error")
        self.active_task_card.set_task("Probe failed", status="error")
        self._refresh_panels()

    def _render_probe_dashboard(self):
        if not self._probe_reports:
            self.dashboard_tab.setPlainText(
                "No probe runs yet.\n"
                "Use Crawler page: Scan/Browse executable -> Register + Probe Selected Executable."
            )
            return

        lines: List[str] = []
        lines.append("Probe Runs (latest first)")
        lines.append("=" * 72)

        for index, report in enumerate(self._probe_reports[:12], start=1):
            discovery = report.get("discovery", {}) if isinstance(report.get("discovery", {}), dict) else {}
            cache = report.get("cache_analysis", {}) if isinstance(report.get("cache_analysis", {}), dict) else {}
            lines.append(
                f"{index}. {report.get('generated_at', '')} | app={report.get('app_name', '')} | "
                f"discovered={discovery.get('discovered', 0)} | "
                f"hits={cache.get('task_match_hits', 0)} | misses={cache.get('task_match_misses', 0)} | "
                f"ratio={cache.get('task_match_ratio', 0.0)}"
            )

        lines.append("")
        lines.append("Latest Report JSON")
        lines.append("=" * 72)
        lines.append(json.dumps(self._probe_reports[0], indent=2, ensure_ascii=False))
        self.dashboard_tab.setPlainText("\n".join(lines))

    def closeEvent(self, event):
        if self.voice_service is not None:
            self.voice_service.stop_listening()
            logger.info("Chat window closing; voice listening stopped")
        super().closeEvent(event)


def launch_chat(host_agent, voice_service=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = SaraChatWindow(host_agent, voice_service=voice_service)
    window.show()
    return app.exec_()
