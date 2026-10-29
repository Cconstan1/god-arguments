# God Arguments

An interactive, browser-based map of arguments in the theist–atheist debate, centered on the Kalam cosmological argument. Explore the master map of 75 arguments, filter and search cards, then open the linked argument tree to follow claims, objections, and responses. The interface also includes audio narration, a fifth-grade summary mode, and a media sandbox.

## Run locally

The project is a static site; no frontend build step is required. From the repository directory, start a local web server:

```powershell
python -m http.server 8000
```

Open [http://localhost:8000](http://localhost:8000) in a browser. Use `Ctrl+C` in the terminal to stop the server. Serving the files over HTTP is recommended so the browser can load the JSON data and audio assets.

## Project files

- `index.html` — the interactive argument map and argument-tree views.
- `sandbox.html` — a standalone media and audio embed sandbox.
- `arguments_index.json` — the master list of arguments shown on the map.
- `kalam_tree.json` — argument nodes for the Kalam tree.
- `audio/` — generated MP3 narrations and their generation cache.
- `generate_5th_grader_text.py` — generates simplified summaries in the JSON data.
- `generate_audio.py` — generates male and female text-to-speech MP3s for argument-tree nodes.
- `take_screenshots.js` — runs a local browser session and saves UI screenshots.
- `screenshots/` — sample screenshots.

## Generate fifth-grade summaries

Requires Python 3 and a Gemini API key. In PowerShell, set the key for the current terminal session:

```powershell
$env:GEMINI_API_KEY = "your-api-key"
python .\generate_5th_grader_text.py
```

The script processes `*_tree.json` files and `arguments_index.json` by default, adding `summary_5th_grader` fields to entries that do not already have one. To process specific files, pass them with `--file`; use `--force` to regenerate existing summaries:

```powershell
python .\generate_5th_grader_text.py --file kalam_tree.json arguments_index.json
python .\generate_5th_grader_text.py --force
```

The script also accepts `GOOGLE_API_KEY`. Generated summaries are written back to the JSON files.

## Generate audio

Requires Python 3, the dependencies in `requirements.txt`, and Google Cloud Text-to-Speech credentials for a project with the API enabled:

```powershell
python -m pip install -r requirements.txt
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account.json"
python .\generate_audio.py
```

By default, the script processes each `*_tree.json` file in the project. It writes MP3s to `audio/`, updates each node's `audio_urls`, and stores a cache in `audio/audio_cache.json`. Use `--file` to process one tree or `--force` to regenerate cached audio:

```powershell
python .\generate_audio.py --file kalam_tree.json
python .\generate_audio.py --force
```

Keep API keys and service-account credentials private. Prefer environment variables or your local Google Cloud credentials; do not commit credential files.

## Capture screenshots (optional)

`take_screenshots.js` uses Playwright and Chromium. Install them if you want to regenerate the screenshots:

```powershell
npm install --no-save playwright
npx playwright install chromium
node .\take_screenshots.js
```

The script serves the project locally, captures the main interface and sandbox, and saves the images under `screenshots/`.
