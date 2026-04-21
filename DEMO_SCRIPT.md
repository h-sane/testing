# SARA Demo Quick Script

## 1) Install dependencies

python -m pip install -r requirements_demo.txt

## 2) Smoke test core flow

python demo.py --test

## 2.1) Preflight check

python demo.py --preflight

## 3) Run CLI (safe)

python demo.py --cli

Suggested commands:

- my name is Hussain
- open file menu in notepad
- what can you automate

## 4) Run chat UI

python demo.py

## 5) Run always-on-top widget

python demo.py --widget

## 6) Live mode (real app actions)

python demo.py --live

## Notes

- If PyQt5 is unavailable, demo falls back to CLI automatically.
- Keep one app at a time for low-resource stability.
- If NVIDIA is rate-limited, provider fallback will use Gemini/Claude unless strict mode is enabled.
