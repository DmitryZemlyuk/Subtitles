#!/usr/bin/env python3
"""
srt_to_mp3_elevenlabs.py — Generate a voiced MP3 from an SRT file using ElevenLabs API.

Usage:
    pip install elevenlabs pydub
    brew install ffmpeg

    python3 srt_to_mp3_elevenlabs.py subtitles.uk.srt YOUR_API_KEY
    python3 srt_to_mp3_elevenlabs.py subtitles.uk.srt YOUR_API_KEY --voice-id YOUR_VOICE_ID
    python3 srt_to_mp3_elevenlabs.py subtitles.uk.srt YOUR_API_KEY --list-voices

How it works:
    1. Parses SRT timings
    2. Generates TTS audio for each subtitle line via ElevenLabs
    3. Stretches/squeezes each clip to fit its subtitle duration using ffmpeg
    4. Places each clip at the correct timestamp with silence in between
    5. Exports final MP3
"""

import argparse
import os
import re
import sys
import tempfile
import subprocess
import json
import time
import urllib.request

try:
    from pydub import AudioSegment
except ImportError:
    print("❌ Missing dependency: pip install pydub")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_VOICE_ID = "XB0fDUnXU5powFXDhCwa"  # Charlotte — multilingual, works well for Ukrainian
# Other good multilingual voices:
#   EXAVITQu4vr4xnSDxMaL  — Bella
#   21m00Tcm4TlvDq8ikWAM  — Rachel
# To use a cloned/custom Ukrainian voice, pass --voice-id YOUR_ID

ELEVENLABS_API = "https://api.elevenlabs.io/v1"
MAX_STRETCH_RATIO = 2.5   # max slow-down factor (beyond this we just leave it natural speed)
MIN_STRETCH_RATIO = 0.6   # max speed-up factor


# ── SRT parser ────────────────────────────────────────────────────────────────

def parse_time(ts: str) -> int:
    """Parse SRT timestamp → milliseconds."""
    h, m, rest = ts.strip().split(":")
    s, ms = rest.replace(",", ".").split(".")
    return int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1_000 + int(ms)


def parse_srt(path: str):
    """Return list of (start_ms, end_ms, text)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    pattern = re.compile(
        r"\d+\s*\n"
        r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"
        r"((?:(?!\d+\s*\n\d{2}:\d{2}).+\n?)*)",
        re.MULTILINE,
    )
    blocks = []
    for m in pattern.finditer(content):
        text = re.sub(r"<[^>]+>|\{[^}]+\}", "", m.group(3)).strip()
        if text:
            blocks.append((parse_time(m.group(1)), parse_time(m.group(2)), text))
    return blocks


# ── ElevenLabs API ────────────────────────────────────────────────────────────

def list_voices(api_key: str):
    req = urllib.request.Request(
        f"{ELEVENLABS_API}/voices",
        headers={"xi-api-key": api_key}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data.get("voices", [])


def tts_to_file(text: str, voice_id: str, api_key: str, out_path: str, retries=3):
    """Call ElevenLabs TTS and save MP3 to out_path."""
    body = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True
        }
    }).encode()

    url = f"{ELEVENLABS_API}/text-to-speech/{voice_id}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        }
    )

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                audio_data = resp.read()
            with open(out_path, "wb") as f:
                f.write(audio_data)
            return True
        except Exception as e:
            wait = (attempt + 1) * 5
            print(f"  ⚠ TTS error (attempt {attempt+1}/{retries}): {e}, retry in {wait}s...")
            time.sleep(wait)
    return False


# ── Audio stretching ──────────────────────────────────────────────────────────

def stretch_audio(in_path: str, out_path: str, target_ms: int) -> AudioSegment:
    """
    Load audio, stretch/squeeze to target_ms using ffmpeg atempo filter,
    return as AudioSegment trimmed/padded to exactly target_ms.
    """
    seg = AudioSegment.from_mp3(in_path)
    src_ms = len(seg)

    if src_ms == 0:
        return AudioSegment.silent(duration=target_ms)

    ratio = src_ms / target_ms  # >1 means speed up, <1 means slow down

    # Clamp ratio to safe range
    ratio = max(MIN_STRETCH_RATIO, min(MAX_STRETCH_RATIO, ratio))

    if abs(ratio - 1.0) < 0.05:
        # Close enough — no stretching needed
        result = seg
    else:
        # ffmpeg atempo only supports 0.5–2.0 per filter; chain for extreme values
        filters = []
        r = ratio
        while r > 2.0:
            filters.append("atempo=2.0")
            r /= 2.0
        while r < 0.5:
            filters.append("atempo=0.5")
            r *= 2.0
        filters.append(f"atempo={r:.4f}")
        filter_str = ",".join(filters)

        tmp_out = out_path + ".stretched.mp3"
        cmd = [
            "ffmpeg", "-y", "-i", in_path,
            "-filter:a", filter_str,
            "-vn", tmp_out
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        result = AudioSegment.from_mp3(tmp_out)
        os.unlink(tmp_out)

    # Trim or pad to exactly target_ms
    if len(result) > target_ms:
        result = result[:target_ms]
    elif len(result) < target_ms:
        result = result + AudioSegment.silent(duration=target_ms - len(result))

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SRT → MP3 via ElevenLabs")
    parser.add_argument("srt", help="Path to .srt file")
    parser.add_argument("api_key", nargs="?", help="ElevenLabs API key")
    parser.add_argument("--voice-id", default=DEFAULT_VOICE_ID, help="ElevenLabs voice ID")
    parser.add_argument("--list-voices", action="store_true", help="List available voices and exit")
    parser.add_argument("--out", help="Output MP3 path (default: same dir as SRT)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        print("❌ Provide API key as argument or set ELEVENLABS_API_KEY env var")
        sys.exit(1)

    if args.list_voices:
        print("Fetching voices...")
        voices = list_voices(api_key)
        for v in voices:
            langs = ", ".join(v.get("fine_tuning", {}).get("language", []) or [])
            print(f"  {v['voice_id']}  {v['name']:<30} {langs}")
        return

    if not os.path.exists(args.srt):
        print(f"❌ File not found: {args.srt}")
        sys.exit(1)

    blocks = parse_srt(args.srt)
    if not blocks:
        print("❌ No subtitle blocks found in SRT")
        sys.exit(1)

    total = len(blocks)
    total_duration_ms = blocks[-1][1]  # end time of last block
    out_path = args.out or args.srt.replace(".srt", ".mp3")

    print(f"📄 {total} subtitle blocks, total duration: {total_duration_ms/1000:.1f}s")
    print(f"🎤 Voice: {args.voice_id}")
    print(f"💾 Output: {out_path}")
    print()

    # Build final track as silent canvas
    final = AudioSegment.silent(duration=total_duration_ms + 1000)

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, (start_ms, end_ms, text) in enumerate(blocks):
            duration_ms = end_ms - start_ms
            if duration_ms <= 0:
                continue

            print(f"  [{i+1}/{total}] {start_ms/1000:.1f}s → {end_ms/1000:.1f}s  ({duration_ms}ms)  {text[:60]}")

            tmp_mp3 = os.path.join(tmpdir, f"line_{i:04d}.mp3")
            ok = tts_to_file(text, args.voice_id, api_key, tmp_mp3)
            if not ok:
                print(f"    ❌ Skipping line {i+1}")
                continue

            try:
                clip = stretch_audio(tmp_mp3, os.path.join(tmpdir, f"line_{i:04d}_s.mp3"), duration_ms)
                final = final.overlay(clip, position=start_ms)
            except Exception as e:
                print(f"    ⚠ Audio processing error: {e}, skipping")
                continue

            # Small pause to avoid hammering the API
            time.sleep(0.3)

    print()
    print("💾 Exporting MP3...")
    final.export(out_path, format="mp3", bitrate="192k")
    print(f"✅ Done! Saved: {out_path}")


if __name__ == "__main__":
    main()