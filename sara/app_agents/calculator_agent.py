"""Calculator AppAgent."""

from sara.app_agents.base_agent import BaseAppAgent


class CalculatorAgent(BaseAppAgent):
    app_name = "Calculator"
    exe_name = "calc.exe"
    ui_type = "UWP"
    known_tasks = [
        "Switch mode",
        "Perform arithmetic",
        "Use memory",
        "Clear entry",
    ]

    def get_ui_summary(self) -> str:
        return "Windows Calculator with mode drawer, display, numpad and operator buttons"
