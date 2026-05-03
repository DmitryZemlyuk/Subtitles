#!/usr/bin/env python3
"""
SubTranslate — web UI for translating subtitles (TorrServer).
Usage: python3 translate_subs.py
Opens browser at http://localhost:7755
This utility only translates subtitles; it does not open any player.
"""

import os, re, sys, json, time, threading, subprocess, shutil
import urllib.request, urllib.parse, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

OUTPUT_DIR = os.path.expanduser("~/Downloads/translated_subs")
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
BATCH_SIZE = 5
SETTINGS_PATH = os.path.expanduser("~/.subtranslate.json")
PORT = 7755
API_RPM_LIMIT = 15
MIN_API_INTERVAL = 60.0 / API_RPM_LIMIT

# Timestamp of last API call (seconds since epoch)
_last_api_call = 0.0
# Dynamic batching / token estimation for TPM
MAX_INPUT_TOKENS_PER_REQUEST = 3000
MAX_BATCH_SIZE_LIMIT = 50

def estimate_tokens(text: str) -> int:
  # Rough heuristic: ~4 characters per token for English-like text
  return max(1, int(len(text) / 4))

# Global log and status
_log_lines = []
_progress = 0
_status = "Ready"
_running = False
_lock = threading.Lock()

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SubTranslate</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,300;0,400;0,500;1,300&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0c0c10;
    --surface: #13131a;
    --surface2: #1c1c26;
    --border: #2a2a3a;
    --accent: #6d67f0;
    --accent-glow: rgba(109,103,240,0.3);
    --text: #e2e0f0;
    --text2: #7a7890;
    --ok: #4ade80;
    --err: #f87171;
    --warn: #fbbf24;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-weight: 300;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background: radial-gradient(ellipse 60% 40% at 50% 0%, rgba(109,103,240,0.08) 0%, transparent 70%);
    pointer-events: none;
  }
  .card {
    width: 100%;
    max-width: 680px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px;
    box-shadow: 0 32px 80px rgba(0,0,0,0.6);
  }
  .header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 28px;
  }
  .logo {
    font-size: 24px;
    font-weight: 600;
    letter-spacing: -0.5px;
    color: var(--text);
  }
  .logo span { color: var(--accent); }
  .subtitle {
    font-size: 12px;
    color: var(--text2);
    font-family: 'DM Mono', monospace;
    font-weight: 300;
  }
  .divider {
    height: 1px;
    background: var(--border);
    margin-bottom: 24px;
  }
  .field { margin-bottom: 16px; }
  label {
    display: block;
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text2);
    margin-bottom: 6px;
  }
  input {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    padding: 10px 14px;
    outline: none;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-glow);
  }
  .row { display: flex; gap: 12px; }
  .row .field { flex: 1; }
  .row .field.short { flex: 0 0 120px; }
  .status-bar {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12px;
    color: var(--text2);
    font-family: 'DM Mono', monospace;
  }
  .status-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--text2);
    flex-shrink: 0;
    transition: background 0.3s;
  }
  .status-dot.active { background: var(--accent); animation: pulse 1.2s infinite; }
  .status-dot.ok { background: var(--ok); }
  .status-dot.err { background: var(--err); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  .progress-track {
    height: 3px;
    background: var(--surface2);
    border-radius: 2px;
    margin-bottom: 16px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent), #a78bfa);
    border-radius: 2px;
    transition: width 0.4s ease;
    width: 0%;
  }
  .log-box {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 14px;
    height: 200px;
    overflow-y: auto;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    line-height: 1.7;
    margin-bottom: 16px;
  }
  .log-box::-webkit-scrollbar { width: 4px; }
  .log-box::-webkit-scrollbar-track { background: transparent; }
  .log-box::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
  .log-line { color: var(--text2); }
  .log-line.ok { color: var(--ok); }
  .log-line.err { color: var(--err); }
  .log-line.warn { color: var(--warn); }
  .log-line.accent { color: #a78bfa; }
  .btn-row { display: flex; gap: 10px; }
  button {
    padding: 11px 20px;
    border-radius: 8px;
    border: none;
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }
  .btn-primary {
    flex: 1;
    background: var(--accent);
    color: white;
  }
  .btn-primary:hover { background: #7c76f5; box-shadow: 0 4px 20px var(--accent-glow); }
  .btn-primary:active { transform: scale(0.98); }
  .btn-primary:disabled { background: var(--surface2); color: var(--text2); cursor: not-allowed; box-shadow: none; }
  .btn-stop {
    background: var(--surface2);
    color: var(--text2);
    border: 1px solid var(--border);
  }
  .btn-stop:hover { border-color: var(--err); color: var(--err); }
  .btn-stop:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div class="logo">Sub<span>Translate</span></div>
    <div class="subtitle">torrserver → gemini</div>
  </div>
  <div class="divider"></div>

  <div class="field">
    <label>TorrServer video URL</label>
    <input type="text" id="url" placeholder="http://localhost:8090/stream/...">
  </div>

  <div class="row">
    <div class="field">
      <label>Gemini API Key</label>
      <input type="password" id="apikey" placeholder="API key">
    </div>
    <div class="field short">
      <label>Subtitle track</label>
      <input type="text" id="track" value="0" style="text-align:center">
    </div>
    <div class="field short">
      <label>Target language</label>
      <select id="lang" style="width:100%;padding:10px 14px;height:38px;border-radius:8px;background:#1c1c26;color:#e2e0f0;border:1px solid #2a2a3a;font-family:'DM Mono',monospace;font-size:12px;">
        <option value="ru">Russian (ru)</option>
        <option value="uk">Ukrainian (uk)</option>
      </select>
    </div>
  </div>

  <div class="status-bar">
    <div class="status-dot" id="dot"></div>
    <span id="status-text">Ready</span>
  </div>

  <div class="progress-track">
    <div class="progress-fill" id="prog"></div>
  </div>

  <div class="log-box" id="log"></div>

  <div class="btn-row">
    <button class="btn-primary" id="btn-start" onclick="start()">▶ Translate</button>
    <button class="btn-stop" id="btn-stop" onclick="stop()" disabled>■ Stop</button>
  </div>
</div>

<script>
let polling = null;

window.onload = () => {
  fetch('/settings').then(r=>r.json()).then(s => {
    if (s.api_key) document.getElementById('apikey').value = s.api_key;
    if (s.track) document.getElementById('track').value = s.track;
    if (s.lang) document.getElementById('lang').value = s.lang;
  });
};

async function start(force) {
  const url = document.getElementById('url').value.trim();
  const key = document.getElementById('apikey').value.trim();
  const track = document.getElementById('track').value.trim() || '0';
  const lang = document.getElementById('lang').value || 'ru';
  if (!url) { alert('Paste video URL'); return; }
  if (!key) { alert('Enter Gemini API Key'); return; }
  if (force === undefined) {
    const check = await fetch('/check?url=' + encodeURIComponent(url) + '&lang=' + encodeURIComponent(lang)).then(r=>r.json());
    if (check.exists) {
      showDialog(check.path, url, key, track, lang);
      return;
    }
  }

  document.getElementById('btn-start').disabled = true;
  document.getElementById('btn-stop').disabled = false;
  document.getElementById('log').innerHTML = '';
  hideDialog();

  fetch('/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url, key, track, force: !!force, lang})
  });

  polling = setInterval(poll, 600);
}

function showDialog(path, url, key, track, lang) {
  document.getElementById('dlg-path').textContent = path;
  document.getElementById('dialog').style.display = 'flex';
  document.getElementById('btn-retranslate').onclick = () => start(true);
}

function hideDialog() {
  document.getElementById('dialog').style.display = 'none';
}

function stop() {
  fetch('/stop', {method:'POST'});
}

function poll() {
  fetch('/state').then(r=>r.json()).then(s => {
    document.getElementById('status-text').textContent = s.status;
    document.getElementById('prog').style.width = s.progress + '%';

    const dot = document.getElementById('dot');
    dot.className = 'status-dot' + (s.running ? ' active' : s.progress >= 100 ? ' ok' : '');

    const box = document.getElementById('log');
    box.innerHTML = s.log.map(l => `<div class="log-line ${l.tag}">${escHtml(l.msg)}</div>`).join('');
    box.scrollTop = box.scrollHeight;

    if (!s.running) {
      clearInterval(polling);
      document.getElementById('btn-start').disabled = false;
      document.getElementById('btn-stop').disabled = true;
    }
  });
}

async function openExisting(url) {
  hideDialog();
}

function escHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
</script>
<div id="dialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);align-items:center;justify-content:center;z-index:100;backdrop-filter:blur(4px);">
  <div style="background:#13131a;border:1px solid #2a2a3a;border-radius:16px;padding:28px;max-width:420px;width:90%;">
    <div style="font-size:15px;font-weight:600;margin-bottom:10px;">Translation already exists</div>
    <div style="font-size:11px;color:#7a7890;font-family:'DM Mono',monospace;margin-bottom:6px;word-break:break-all;" id="dlg-path"></div>
    <div style="font-size:13px;color:#9490a8;margin-bottom:24px;">Use existing file or re-translate?</div>
    <div style="display:flex;gap:10px;">
      <button id="btn-retranslate" class="btn-stop" style="flex:1;">↺ Re-translate</button>
    </div>
    <div style="text-align:center;margin-top:12px;">
      <button onclick="hideDialog()" style="background:none;border:none;color:#7a7890;font-size:12px;cursor:pointer;">Cancel</button>
    </div>
  </div>
</div>
</body>
</html>
"""


def load_settings():
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
      return {"api_key": os.environ.get("GEMINI_API_KEY", ""), "track": "0", "lang": "ru"}


def save_settings(api_key, track, lang="ru"):
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump({"api_key": api_key, "track": track, "lang": lang}, f)
    except Exception:
        pass


def add_log(msg, tag=""):
    with _lock:
        _log_lines.append({"msg": msg, "tag": tag})


def set_status(msg, pct=None):
    global _status, _progress
    _status = msg
    if pct is not None:
        _progress = pct


def normalize_url(url):
  url = url.replace("\\?", "?").replace("\\&", "&").replace("\\", "")
  url = re.sub(r"&preload\b", "&play", url)
  url = re.sub(r"\?preload\b", "?play", url)
  url = url.strip()

  # If running inside Docker, container-local "localhost:8090" won't reach the host.
  # Rewrite such URLs to host.docker.internal:8090 so ffmpeg inside the container
  # can access services running on the macOS host.
  def running_in_docker():
    try:
      if os.path.exists('/.dockerenv'):
        return True
      with open('/proc/1/cgroup', 'rt') as f:
        data = f.read()
        if 'docker' in data or 'kubepods' in data or 'containerd' in data:
          return True
    except Exception:
      pass
    return False

  try:
    parsed = urllib.parse.urlparse(url)
    if running_in_docker() and parsed.scheme in ('http', 'https') and parsed.hostname in ('localhost', '127.0.0.1'):
      port = parsed.port or (80 if parsed.scheme == 'http' else 443)
      if port == 8090:
        new_netloc = 'host.docker.internal:8090'
        new_parsed = parsed._replace(netloc=new_netloc)
        new_url = urllib.parse.urlunparse(new_parsed)
        try:
          add_log(f"↔ Rewriting URL for Docker: {url} → {new_url}", "warn")
        except Exception:
          pass
        return new_url
  except Exception:
    pass

  return url


def parse_srt(content):
    blocks = []
    pattern = re.compile(
        r"(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\s*\n"
        r"((?:(?!\d+\s*\n\d{2}:\d{2}).+\n?)*)", re.MULTILINE)
    for m in pattern.finditer(content):
        text = re.sub(r"<[^>]+>|\{[^}]+\}", "", m.group(3)).strip()
        if text:
            blocks.append((m.group(1), m.group(2), text))
    return blocks


def gemini_batch(texts, api_key, target_lang='ru'):
    parts = []
    for i, t in enumerate(texts):
        parts.append(f"<s id=\"{i}\"><en>{t}</en></s>")

    lang_name = 'Russian' if target_lang == 'ru' else 'Ukrainian'
    tag = target_lang

    prompt = (
        f"Translate TV show subtitles from English to {lang_name}. "
        f"For each <s> tag return <s id=\"N\"><{tag}>TRANSLATION</{tag}></s>. "
        "Translate ALL content fully, do not shorten. "
        "Respond only with XML, without explanations.\n\n" + "\n".join(parts)
    )

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192}
    }).encode()

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={api_key}")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

    data = None
    global _last_api_call
    for attempt in range(4):
        try:
            elapsed = time.time() - _last_api_call
            if elapsed < MIN_API_INTERVAL:
                to_wait = MIN_API_INTERVAL - elapsed
                add_log(f"  ⏳ Throttling: sleeping {to_wait:.1f}s to respect {API_RPM_LIMIT} RPM", "warn")
                time.sleep(to_wait)
            _last_api_call = time.time()
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            break
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                wait = (attempt + 1) * 20
                add_log(f"  ⏳ Rate limit (attempt {attempt+1}/4), waiting {wait}s...", "warn")
            else:
                wait = (attempt + 1) * 5
                add_log(f"  ⚠ API error (attempt {attempt+1}/4): {err_str[:120]}, retry in {wait}s...", "warn")
            time.sleep(wait)

    if data is None:
        add_log(f"  ❌ All retries failed, using original for this batch", "err")
        return texts

    reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    result = {}

    regex_full = re.compile(
        rf'<s\s+id=["\']?(\d+)["\']?>\s*<{tag}>(.*?)</{tag}>\s*</s>',
        re.DOTALL
    )
    for m in regex_full.finditer(reply):
        result[int(m.group(1))] = m.group(2).strip()

    regex_partial = re.compile(
        rf'<s\s+id=["\']?(\d+)["\']?>\s*<{tag}>(.*?)(?:</{tag}>|$)',
        re.DOTALL
    )
    for m in regex_partial.finditer(reply):
        idx = int(m.group(1))
        if idx not in result:
            text = m.group(2).strip()
            text = re.sub(r'<[^>]*$', '', text).strip()
            if text:
                result[idx] = text

    if not result:
        for line in reply.split("\n"):
            m = re.match(r"\[(\d+)\]\s*(.*)", line.strip())
            if m:
                result[int(m.group(1))] = m.group(2).strip()

    missing = [i for i in range(len(texts)) if i not in result]
    if missing:
        add_log(f"  ⚠ {len(missing)}/{len(texts)} lines not parsed (ids: {missing[:5]}{'...' if len(missing)>5 else ''})", "warn")
        add_log(f"  ⚠ Raw reply preview: {reply[:200].strip()}", "warn")

    return [result.get(i, texts[i]) for i in range(len(texts))]
  """Translate a batch of lines in one structured request to the given language.
  target_lang: 'ru' or 'uk'"""
  parts = []
  for i, t in enumerate(texts):
    parts.append(f"<s id=\"{i}\"><en>{t}</en></s>")

  lang_name = 'Russian' if target_lang == 'ru' else 'Ukrainian'
  tag = target_lang

  prompt = (
    f"Translate TV show subtitles from English to {lang_name}. "
    f"For each <s> tag return <s id=\"N\"><{tag}>TRANSLATION</{tag}></s>. "
    "Translate ALL content fully, do not shorten. "
    "Respond only with XML, without explanations.\n\n" + "\n".join(parts)
  )

  body = json.dumps({
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192}
  }).encode()

  url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
       f"{GEMINI_MODEL}:generateContent?key={api_key}")
  req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

  data = None
  global _last_api_call
  for attempt in range(4):
    try:
      # Enforce minimum interval between API calls to respect RPM limit
      elapsed = time.time() - _last_api_call
      if elapsed < MIN_API_INTERVAL:
        to_wait = MIN_API_INTERVAL - elapsed
        add_log(f"  ⏳ Throttling: sleeping {to_wait:.1f}s to respect {API_RPM_LIMIT} RPM", "warn")
        time.sleep(to_wait)
      _last_api_call = time.time()
      with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
      break
    except Exception as e:
      err_str = str(e)
      if "429" in err_str or "quota" in err_str.lower():
        wait = (attempt + 1) * 20
        add_log(f"  ⏳ Rate limit (attempt {attempt+1}/4), waiting {wait}s...", "warn")
      else:
        wait = (attempt + 1) * 5
        add_log(f"  ⚠ API error (attempt {attempt+1}/4): {err_str[:120]}, retry in {wait}s...", "warn")
      time.sleep(wait)

  if data is None:
    add_log(f"  ❌ All retries failed, using original for this batch", "err")
    return texts

  reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()

  # Parse XML response using chosen tag (tolerant to spaces/newlines around tags)
  result = {}
  regex = re.compile(rf'<s\s+id=["\']?(\d+)["\']?>\s*<{tag}>(.*?)</{tag}>\s*</s>', re.DOTALL)
  for m in regex.finditer(reply):
    result[int(m.group(1))] = m.group(2).strip()

  # If XML not recognized — try numeric [N] fallback
  if not result:
    for line in reply.split("\n"):
      m = re.match(r"\[(\d+)\]\s*(.*)", line.strip())
      if m:
        result[int(m.group(1))] = m.group(2).strip()

  # Log missing translations so we can see what went wrong
  missing = [i for i in range(len(texts)) if i not in result]
  if missing:
    add_log(f"  ⚠ {len(missing)}/{len(texts)} lines not parsed in batch (ids: {missing[:5]}{'...' if len(missing)>5 else ''})", "warn")
    add_log(f"  ⚠ Raw reply preview: {reply[:200].strip()}", "warn")

  return [result.get(i, texts[i]) for i in range(len(texts))]

def run_translation(video_url, api_key, track, force=False, lang='ru'):
  global _running, _progress
  try:
    video_url = normalize_url(video_url)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    parsed = urllib.parse.urlparse(video_url)
    basename = os.path.splitext(os.path.basename(parsed.path))[0].strip("\\/") or "subtitles"
    raw_srt = os.path.join(OUTPUT_DIR, f"{basename}.en.srt")
    translated_srt = os.path.join(OUTPUT_DIR, f"{basename}.{lang}.srt")

    add_log(f"🎬 {basename}", "accent")
    add_log(f"🔗 {video_url}", "")

    # Step 1: extraction
    if os.path.exists(raw_srt) and os.path.getsize(raw_srt) > 0:
      add_log("✓ Using cached subtitles", "ok")
      set_status("Subtitles from cache", 25)
    else:
      add_log("⏳ Extracting subtitles (1–5 min)...", "")
      set_status("Extracting subtitles...", 5)
      cmd = ["ffmpeg", "-y", "-analyzeduration", "10M", "-probesize", "10M",
           "-i", video_url, "-map", f"0:s:{track}",
           "-vn", "-an", "-c:s", "srt", raw_srt]
      try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
      except subprocess.TimeoutExpired:
        add_log("❌ ffmpeg timeout", "err")
        return
      if not os.path.exists(raw_srt) or os.path.getsize(raw_srt) == 0:
        for line in result.stderr.strip().split("\n")[-5:]:
          if line.strip():
            add_log(f"  {line.strip()}", "err")
        add_log("❌ Failed to extract subtitles", "err")
        set_status("Extraction error")
        return
      add_log(f"✓ Extracted {os.path.getsize(raw_srt)} bytes", "ok")
      set_status("Subtitles extracted", 25)

    if not _running:
      return

    # Step 2: translation — check cache
    if not force and os.path.exists(translated_srt) and os.path.getsize(translated_srt) > 0:
      add_log("✓ Using existing translation", "ok")
      set_status("Using translation cache", 95)
    else:
      lang_name = 'Russian' if lang == 'ru' else 'Ukrainian'
      add_log(f"🌐 Translating EN → {lang_name} via Gemini...", "")

    with open(raw_srt, encoding="utf-8", errors="replace") as f:
      content = f.read()
    blocks = parse_srt(content)
    total = len(blocks)
    if total == 0:
      add_log("❌ Subtitles are empty", "err")
      return
    add_log(f"  Blocks: {total}", "")
    translated_texts = []

    i = 0
    while i < total:
      if not _running:
        return
      # Build a batch that fits within estimated input token budget
      batch = []
      batch_input_tokens = 0
      j = i
      while j < total and len(batch) < MAX_BATCH_SIZE_LIMIT:
        t = blocks[j][2]
        tok = estimate_tokens(t)
        if batch_input_tokens + tok > MAX_INPUT_TOKENS_PER_REQUEST:
          break
        batch.append(blocks[j])
        batch_input_tokens += tok
        j += 1

      # If nothing was added (single line exceeds limit), force at least one
      if not batch:
        batch = [blocks[i]]
        j = i + 1

      texts = [b[2] for b in batch]
      try:
        translated_texts.extend(gemini_batch(texts, api_key, lang))
      except Exception as e:
        add_log(f"  ⚠ Batch at {i}: {e}", "warn")
        translated_texts.extend(texts)
        time.sleep(2)

      done = min(j, total)
      set_status(f"Translating: {done}/{total}", 25 + int(done / total * 70))
      # Small pause to allow UI updates; API throttling enforced in gemini_batch
      time.sleep(0.05)
      i = j

    with open(translated_srt, "w", encoding="utf-8") as f:
      for i, (idx, timing, _) in enumerate(blocks):
        text = translated_texts[i].strip() if i < len(translated_texts) else ""
        f.write(f"{idx}\n{timing}\n{text}\n\n")

    # Finished
    add_log("✅ Done!", "ok")
    set_status("Done", 100)
    add_log(f"Saved: {translated_srt}", "")

  except Exception as e:
    add_log(f"❌ {e}", "err")
    set_status("Error")
  finally:
    _running = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", HTML)
        elif self.path == "/settings":
            self._send(200, "application/json", json.dumps(load_settings()))
        elif self.path == "/state":
            with _lock:
                data = {"status": _status, "progress": _progress,
                        "running": _running, "log": list(_log_lines)}
            self._send(200, "application/json", json.dumps(data))
        elif self.path.startswith("/check"):
          params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
          url = params.get("url", [""])[0]
          lang = params.get("lang", ["ru"])[0]
          url = normalize_url(url)
          parsed = urllib.parse.urlparse(url)
          basename = os.path.splitext(os.path.basename(parsed.path))[0].strip("\/") or "subtitles"
          translated_srt = os.path.join(OUTPUT_DIR, f"{basename}.{lang}.srt")
          exists = os.path.exists(translated_srt) and os.path.getsize(translated_srt) > 0
          self._send(200, "application/json", json.dumps({"exists": exists, "path": translated_srt, "lang": lang}))
        elif self.path.startswith("/files"):
            try:
                files = []
                for fn in sorted(os.listdir(OUTPUT_DIR)):
                    path = os.path.join(OUTPUT_DIR, fn)
                    try:
                        st = os.stat(path)
                        files.append({"name": fn, "size": st.st_size, "mtime": int(st.st_mtime)})
                    except Exception:
                        files.append({"name": fn})
                self._send(200, "application/json", json.dumps({"dir": OUTPUT_DIR, "files": files}))
            except Exception as e:
                self._send(500, "application/json", json.dumps({"error": str(e)}))
        else:
            self._send(404, "text/plain", "Not found")

    def do_POST(self):
        global _running, _progress, _log_lines, _status
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if self.path == "/start" and not _running:
            data = json.loads(body)
            save_settings(data["key"], data.get("track", "0"), data.get("lang", "ru"))
            with _lock:
                _log_lines = []
                _progress = 0
            _status = "Starting..."
            _running = True
            threading.Thread(
                target=run_translation,
                args=(data["url"], data["key"], data.get("track", "0"),
                      data.get("force", False), data.get("lang", "ru")),
                daemon=True
            ).start()
            self._send(200, "application/json", '{"ok":true}')

        elif self.path == "/start_file" and not _running:
            import cgi
            ctype, pdict = cgi.parse_header(self.headers.get('Content-Type', ''))
            pdict['boundary'] = pdict.get('boundary', '').encode()
            import io
            fields = cgi.parse_multipart(io.BytesIO(body), pdict)

            content  = fields.get('content',  [b''])[0]
            filename = fields.get('filename', [b'subtitles.srt'])[0]
            api_key  = fields.get('key',      [b''])[0]
            lang     = fields.get('lang',     [b'ru'])[0]

            # Decode bytes if needed
            if isinstance(content,  bytes): content  = content.decode('utf-8', errors='replace')
            if isinstance(filename, bytes): filename = filename.decode('utf-8', errors='replace')
            if isinstance(api_key,  bytes): api_key  = api_key.decode('utf-8', errors='replace')
            if isinstance(lang,     bytes): lang     = lang.decode('utf-8', errors='replace')

            save_settings(api_key, "0", lang)
            with _lock:
                _log_lines = []
                _progress = 0
            _status = "Starting..."
            _running = True
            threading.Thread(
                target=run_translation_text,
                args=(content, filename, api_key, lang),
                daemon=True
            ).start()
            self._send(200, "application/json", '{"ok":true}')

        elif self.path == "/stop":
          _running = False
          _status = "Stopped"
          self._send(200, "application/json", '{"ok":true}')
        else:
            self._send(400, "text/plain", "Bad request")


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"\n  🎬 SubTranslate running → {url}")
    print(f"  Ctrl+C to stop\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")