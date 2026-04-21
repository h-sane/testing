"""Notepad AppAgent."""

from sara.app_agents.base_agent import BaseAppAgent


class NotepadAgent(BaseAppAgent):
    app_name = "Notepad"
    exe_name = "notepad.exe"
    ui_type = "Win32/UWP Hybrid"
    known_tasks = [
        "Open File menu",
        "Save file",
        "Save As",
        "Find text",
        "Replace text",
        "Toggle word wrap",
    ]

    def get_ui_summary(self) -> str:
        return (
            "Notepad with top menu (File/Edit/Format/View/Help), "
            "main text editor, and optional status bar"
        )
