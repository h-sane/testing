# SARA User Test Flow (Windows)

This file gives you a complete smoke test flow: environment activation, health checks, UI test, live automation test, and voice wake-word test.

## 1) Activate the project environment

Use PowerShell in the project root.

```powershell
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& .\.venv\Scripts\Activate.ps1)
```

Optional check:

```powershell
python --version
```

## 2) Quick health checks (must pass first)

Run these in order:

```powershell
python demo.py --preflight
python demo.py --test
```

Expected:

- Both commands should exit successfully.
- Preflight should print a JSON report and a generated preflight file path.
- Test should show PASS for remember, automation, and conversation checks.

## 3) Configure voice keys in .env (text + voice together)

Open .env and confirm these are set:

```dotenv
DEEPGRAM_API_KEY=your_deepgram_key
PICOVOICE_ACCESS_KEY=your_picovoice_key
SARA_WAKE_WORD_PATH=C:/Users/husai/Desktop/CODES/Project/testing/Hey-SARA_en_windows_v3_0_0.ppn
SARA_WAKE_WORD=hey sara
SARA_DISABLE_VOICE_INPUT=0
SARA_FORCE_FEMALE_TTS=1
SARA_FEMALE_TTS_MODEL=aura-2-thalia-en
SARA_DEEPGRAM_TTS_SAMPLE_RATE=48000

# Neo4j graph memory
SARA_ENABLE_GRAPH_MEMORY=1
SARA_MEMORY_USER_ID=local-user
SARA_NEO4J_URI=bolt://localhost:7687
SARA_NEO4J_USER=neo4j
SARA_NEO4J_PASSWORD=your_neo4j_password
SARA_NEO4J_DATABASE=neo4j
```

Note:

- Text input is always available.
- Voice input runs in parallel when configured.

Only if you explicitly want to turn voice off:

```dotenv
SARA_DISABLE_VOICE_INPUT=1
```

## 4) Launch the main app (chat UI)

Live execution mode:

```powershell
python demo.py --live
```

Dry-run mode (no real app actions):

```powershell
python demo.py
```

## 4.1) Verify graph memory is connected

Run:

```powershell
python demo.py --preflight
```

In the JSON output, check:

- checks.memory_graph.ok should be true
- checks.memory_graph.details.ready should be true

## 5) Manual click flow inside the chat UI

After the UI opens:

1. In the App dropdown, select Notepad.
2. Make sure Dry-run is unchecked for real execution.
3. In the input box, type each command below and click Send.

Use these prompts in order:

1. open file menu in notepad
2. remember my name is Hussain
3. my teacher is Sarah Khan
4. what was my name?
5. who is my teacher?
6. write a letter to my teacher in notepad

Expected behavior:

- You should see live step traces while actions run.
- Notepad File menu should open.
- Memory commands should confirm storage and graph recall.
- The letter command should resolve "my teacher" to the teacher name remembered in graph memory.

## 6) Voice and wake-word flow

In the same UI:

1. Confirm the wake status label shows enabled.
2. Click PTT and speak: open file menu in notepad
3. For wake-word flow, say: hey sara open file menu in notepad

Expected behavior:

- Speech is transcribed and dispatched as a command.
- The command executes similarly to typed input.
- Assistant responses are spoken back through TTS when voice mode is active.

## 7) Optional CLI test

```powershell
python demo.py --cli --live
```

Try these in CLI:

- status
- open file menu in notepad
- memory
- history
- exit

## 8) One-command verification block

If you want a fast rerun of core checks:

```powershell
python demo.py --preflight; python demo.py --test
```

## 9) Troubleshooting quick list

- If UI fails with PyQt5 missing:
  - install/repair dependencies in the active venv, then rerun preflight.
- If wake does not trigger:
  - verify SARA_DISABLE_VOICE_INPUT=0
  - verify PICOVOICE_ACCESS_KEY is valid
  - verify SARA_WAKE_WORD_PATH points to the .ppn file that exists
- If voice runs but no Deepgram STT/TTS:
  - verify DEEPGRAM_API_KEY is present in .env
  - rerun python demo.py --preflight and inspect voice details
- If memory recall fails:
  - verify Neo4j is running and credentials are valid
  - verify checks.memory_graph.ok is true in preflight output
  - ensure you used clear relation statements first (for example: "my teacher is Sarah Khan")
  - then ask recall questions (for example: "who is my teacher?")
- If voice sounds robotic:
  - verify Deepgram is actually used for responses (not fallback) with this command:
    - python -c "from sara.voice.service import VoiceService; import json; s=VoiceService(); print(json.dumps(s.get_pipeline_status(), indent=2))"
  - check these fields in output:
    - tts_model should be a female Aura voice (for example aura-2-thalia-en)
    - last_tts_backend should be deepgram after a spoken response
    - if last_tts_backend shows pyttsx3_fallback, the robotic voice is fallback TTS, not Deepgram

## 10) Probe a brand-new app (not already in dropdown/cache)

Why your dropdown does not show every app on the laptop:

- The UI is allowlist-driven. It shows apps known to SARA/harness config, not a full Windows-installed-app scan.
- Discovery/probing runs only for registered app entries (name + exe path + title regex).

Register and probe a new app in one command:

```powershell
python scripts/register_and_probe_app.py --app Slack --exe "C:\Users\husai\AppData\Local\slack\slack.exe" --title-re ".*Slack.*" --task "open settings" --discover --discover-time 240
```

Optional flags:

- --electron for Electron/Chromium apps
- --menu-fallback file=%F (repeatable)
- multiple --task flags to seed candidate tasks

After probing:

- App registration is persisted in .config/user_apps.json
- Cache is written to .cache/<app_name_lower>.json
- Crawl logs are in experiments/crawl_logs/

Manual alternative (if already registered):

```powershell
python scripts/crawl_app.py --app Slack --time 240
```

## 11) In-UI flow: discover any installed app, register it, probe it, and view hits/misses

In chat UI (python demo.py --live):

1. Click Discover Windows Apps.
2. Pick an app from the discovered list (registry + Start Menu scan).
3. Confirm Name, Exe, and Title Regex fields.
4. Optional: set Tasks CSV and Electron.
5. Click Register Pick.
6. Select that app in the App selector.
7. Click Probe Active App.
8. Open the Dashboard tab.

Dashboard now shows per-probe run metrics including:

- discovered elements
- task_match_hits
- task_match_misses
- task_match_ratio
- latest full probe report JSON
