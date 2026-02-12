import os
import time
import json
import base64
import requests
import itertools

from dotenv import load_dotenv
from PIL import ImageGrab
from pywinauto import Application, Desktop
from pywinauto.mouse import click

# =========================
# LOAD API KEYS SECURELY
# =========================

load_dotenv()

GROK_KEYS = [
    os.getenv("GROK_KEY_1"),
    os.getenv("GROK_KEY_2"),
    os.getenv("GROK_KEY_3"),
    os.getenv("GROK_KEY_4"),
]

KEY_CYCLE = itertools.cycle([k for k in GROK_KEYS if k])

GROK_ENDPOINT = "https://api.x.ai/v1/chat/completions"

OUTPUT_DIR = "hybrid_runs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================
# APPS TO TEST
# =========================

APPS = [
    {"name": "Notepad", "exe": r"C:\Windows\notepad.exe", "task": "edit text"},
    {"name": "Calculator", "exe": r"C:\Windows\System32\calc.exe", "task": "press number"},
    {"name": "Chrome", "exe": r"C:\Program Files\Google\Chrome\Application\chrome.exe", "task": "open new tab"},
]

# =========================
# SCREENSHOT
# =========================

def capture_screenshot(path):

    img = ImageGrab.grab()

    img.save(path)


# =========================
# GROK VISION CALL
# =========================

def grok_detect(image_path, task):

    try:

        key = next(KEY_CYCLE)

        with open(image_path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode()

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

        prompt = f"""
Find UI element for task: "{task}"

Return ONLY JSON:

{{"x": number, "y": number}}
"""

        payload = {
            "model": "grok-vision-beta",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    }
                ]
            }]
        }

        response = requests.post(GROK_ENDPOINT, headers=headers, json=payload, timeout=30)

        if response.status_code != 200:
            return None

        content = response.json()["choices"][0]["message"]["content"]

        coords = json.loads(content)

        return coords["x"], coords["y"]

    except Exception as e:

        print("Grok error:", e)

        return None


# =========================
# AX TARGETED EXECUTION
# =========================

def ax_targeted_action(window, task):

    task = task.lower()

    for elem in window.descendants():

        try:
            name = elem.window_text().lower()

            if task in name:

                try:
                    elem.invoke()
                    return True

                except:

                    try:
                        elem.click_input()
                        return True
                    except:
                        pass

        except:
            pass

    return False


# =========================
# RUN SINGLE APP
# =========================

def run_app(config):

    name = config["name"]
    exe = config["exe"]
    task = config["task"]

    print(f"\nTesting: {name}")

    result = {
        "app": name,
        "task": task,
        "method": None,
        "success": False
    }

    try:

        app = Application(backend="uia").start(exe)

        time.sleep(3)

        window = app.top_window()

        # AX attempt
        ax_success = ax_targeted_action(window, task)

        if ax_success:

            print("AX success")

            result["method"] = "AX"
            result["success"] = True

        else:

            print("AX failed → using Grok")

            screenshot = os.path.join(OUTPUT_DIR, f"{name}.png")

            capture_screenshot(screenshot)

            coords = grok_detect(screenshot, task)

            if coords:

                click(coords=coords)

                result["method"] = "GROK"
                result["success"] = True
                result["coords"] = coords

            else:

                result["method"] = "FAILED"

        # close app cleanly
        app.kill()

    except Exception as e:

        print("App error:", e)

    with open(os.path.join(OUTPUT_DIR, f"{name}.json"), "w") as f:

        json.dump(result, f, indent=4)


# =========================
# MAIN
# =========================

if __name__ == "__main__":

    for app in APPS:

        run_app(app)

    print("\nHybrid test complete.")
