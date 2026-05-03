# SubTranslate

Small toolkit and web UI to extract, translate and convert subtitles for video streams.

This repository includes a lightweight HTTP server (`translate_subs.py`) that extracts subtitle tracks via `ffmpeg`, translates them using the Generative Language API (Gemini), and saves translated .srt files. It also contains helper scripts to convert subtitle files to audio (`srt_to_mp3_elevenlabs.py`) and to assist with simple OBS synchronization workflows (`obs_sync_start.py`).

## Features
- Extract subtitle tracks from a video stream (via `ffmpeg`).
- Translate subtitles using Gemini (Generative Language API).
- Convert `.srt` files to spoken audio via ElevenLabs (`srt_to_mp3_elevenlabs.py`).
- Small helper for starting OBS-sync workflows (`obs_sync_start.py`).
- Web UI for entering stream URL, API key, subtitle track and target language.
- Default outputs saved to `~/Downloads/translated_subs` (or a host-mounted directory in Docker).

## Files
- `translate_subs.py` — main server (HTTP UI + translation worker).
- `srt_to_mp3_elevenlabs.py` — convert `.srt` to spoken `mp3` using ElevenLabs voices.
- `obs_sync_start.py` — small helper script for OBS/startup sync scenarios.
- `Dockerfile` — container image with Python + ffmpeg.
- `docker-compose.yml` — convenient compose setup for running the service.

## Quick start — Docker Compose (recommended)
1. Create or export your Gemini API key and optional output dir:

```bash
export GEMINI_API_KEY="your_gemini_api_key"
export OUTPUT_DIR="$HOME/Downloads/translated_subs"
```

2. Build and run:

```bash
docker compose up --build
```

3. Open the UI at: http://localhost:7755

Notes:
- The compose file maps `${OUTPUT_DIR}` on the host to `/root/Downloads/translated_subs` inside the container so translated files are persisted.
- The service reads/writes `/root/.subtranslate.json` for saved settings; you can bind-mount your host `~/.subtranslate.json` if you want persistence across containers.

## Quick start — Docker (single container)
Build image:

```bash
docker build -t subtranslate:latest .
```

Run (map output dir and set API key):

```bash
docker run --rm -p 7755:7755 \
  -e GEMINI_API_KEY="your_key_here" \
  -v "$HOME/Downloads/translated_subs:/root/Downloads/translated_subs" \
  subtranslate:latest
```

## Run locally (no Docker)
Requirements: Python 3.11+, `ffmpeg` on PATH.

```bash
python3 translate_subs.py
```

If you prefer not to set `GEMINI_API_KEY` as an env var, enter it in the web UI and save.

## UI Fields
- TorrServer video URL — URL of the stream to extract subtitles from.
- Gemini API Key — your API key for the Generative Language API.
- Subtitle track — integer track index (default `0`).
- Target language — choose `Ukrainian (uk)`, `Russian (ru)`, or other supported language codes depending on your Gemini model.

Example TorrServer URL:

```
http://localhost:8090/stream/Castle.S03E15.1080p.WEBRip.4xRus.Eng.mkv?link=d9btestlinksometnigid&index=49&preload
```

## Screenshot

The web UI looks like this (place your screenshot at `assets/screenshot.png`):

![SubTranslate UI](assets/screenshot.png)


## Output
Files are written as `<basename>.<lang>.srt`, e.g. `movie.ru.srt` or `movie.uk.srt` in the output directory.

The `srt_to_mp3_elevenlabs.py` script writes `<basename>.<lang>.mp3` files next to your `.srt` files when converting subtitles to audio.

## Advanced
- The server exposes `/state` (JSON) with status, progress and log lines and `/files` to list output files for diagnostics.
- If running in Docker, the service binds to `0.0.0.0:7755`; access the UI at `http://localhost:7755` from your host.

## Troubleshooting
- If subtitles extraction fails, ensure `ffmpeg` can access the stream and the correct subtitle track is selected.
- For Gemini rate limits, the script implements simple retry/backoff and surfaces warnings in the UI.
- To manage Gemini API keys or view quota information, use the Google Cloud / AI Studio console for your account.

## Security
- Keep your `GEMINI_API_KEY` secret. Pass it via environment variables or a host-mounted `~/.subtranslate.json` rather than embedding it into images or committed files.

## License
This repository does not include a formal license file. Treat the code as provided "as-is" for personal or internal use. Add a license if you plan to redistribute or publish the project.
