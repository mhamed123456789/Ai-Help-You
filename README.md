# AI Help You

A Windows desktop AI companion with Gemini chat, voice input/output, image analysis, and local desktop shortcuts. **This project is a desktop app only; it has no website.**

The CustomTkinter desktop app starts a private FastAPI service on `127.0.0.1` and stops it when the app closes. The Gemini key stays local and is never sent over the app's local HTTP connection.

## Requirements

- Python 3.10 or later
- A Gemini API key for AI chat and image analysis
- A microphone and internet access for speech recognition

## Install and run

From this directory, create a virtual environment and install the app:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

In `.env`, add your private Gemini API key, then launch the desktop app:

```text
GEMINI_API_KEY=your_private_api_key
```

```powershell
python app.py
```

Get a key from [Google AI Studio](https://aistudio.google.com/apikey). Keep it private; do not commit it to source control.

## Daily AI credits

- The first launch initializes a local balance of **500 credits**.
- The balance is saved on this Windows user account and stays saved when the app closes or restarts. A brand-new install starts with 500 credits.
- Credits reset to **500 automatically at 00:00 local PC time**. The app displays a live countdown.
- Each AI message costs **5–20 credits**, based on message length and attached images.
- When credits reach zero, chat is locked until midnight. Failed Gemini requests restore the reserved credits.
- API connection tests do not use chat credits.

Credits are stored locally under `%APPDATA%\Ai Tool\credits.sqlite3`. This is a local-device allowance, not a server-enforced user account or a tamper-proof quota.

## Features

- Concise Gemini 3.5 Flash-Lite chat with a multilingual system prompt.
- Attach or paste PNG, JPEG, WebP, HEIC, or HEIF images, or attach a screenshot. Decodable images are resized and compressed for Gemini. Up to 4 images per message; each source image is limited to 10 MB and the combined encoded payload to 20 MB.
- Voice recognition through the system microphone and optional offline speech output.
- English, French, and Arabic interface and speech recognition options.
- Dark and light themes, plus automatic day/night switching.
- Screenshot capture, quick-launch actions, and configurable multi-app shortcuts.
- Desktop organization previews proposed moves and asks for confirmation; it never deletes files.
- Optional Windows startup setting.

Voice capture uses `sounddevice` instead of PyAudio, avoiding PyAudio's native C++ build requirement on Windows. The app records up to 8 seconds from the default microphone and uses Google's web speech recognizer. If the microphone is unavailable or blocked by Windows privacy settings, text chat and local shortcuts remain available.

## Tests

```powershell
python -m unittest discover -s tests -v
```
