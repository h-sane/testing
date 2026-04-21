"""Excel AppAgent."""

from sara.app_agents.base_agent import BaseAppAgent


class ExcelAgent(BaseAppAgent):
    app_name = "Excel"
    exe_name = "excel.exe"
    ui_type = "Office UIA"
    known_tasks = [
        "Open File menu",
        "Save workbook",
        "Select cell",
        "Insert row",
        "Apply formula",
    ]

    def get_ui_summary(self) -> str:
        return (
            "Excel with ribbon tabs, formula bar, cell grid, worksheet tabs, "
            "and standard file operations"
        )
