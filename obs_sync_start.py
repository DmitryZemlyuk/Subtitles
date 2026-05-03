"""
obs_sync_start.py — OBS Python script
Restarts two Media Sources and triggers subtitle start in Browser Source
via a single hotkey.

Setup:
    1. OBS → Tools → Scripts → "+" → select this file
    2. Fill in source names in the settings panel
    3. OBS → Settings → Hotkeys → find "Sync Start" → assign a key
    4. Press the hotkey to start everything simultaneously
"""

import obspython as obs
import json

# ── Settings (filled via OBS Scripts UI) ─────────────────────────────────
_media1_name = ""
_media2_name = ""
_browser_name = ""
_hotkey_id = obs.OBS_INVALID_HOTKEY_ID


# ── Hotkey callback ───────────────────────────────────────────────────────

def on_sync_start(pressed):
    if not pressed:
        return

    # Restart Media Source 1
    if _media1_name:
        source = obs.obs_get_source_by_name(_media1_name)
        if source:
            proc = obs.obs_source_get_proc_handler(source)
            obs.calldata_t
            cd = obs.calldata_create()
            obs.proc_handler_call(proc, "restart", cd)
            obs.calldata_destroy(cd)
            obs.obs_source_release(source)

    # Restart Media Source 2
    if _media2_name:
        source = obs.obs_get_source_by_name(_media2_name)
        if source:
            proc = obs.obs_source_get_proc_handler(source)
            cd = obs.calldata_create()
            obs.proc_handler_call(proc, "restart", cd)
            obs.calldata_destroy(cd)
            obs.obs_source_release(source)

    # Send "start" command to Browser Source via JavaScript
    if _browser_name:
        source = obs.obs_get_source_by_name(_browser_name)
        if source:
            obs.obs_source_send_mouse_click(source, None, 0, False, 1)
            # Execute JS in the browser source to trigger start
            js = "if(typeof obsStart === 'function') obsStart();"
            obs.obs_source_execute_script(source, js) if hasattr(obs, 'obs_source_execute_script') else None
            obs.obs_source_release(source)

    obs.script_log(obs.LOG_INFO, "✓ Sync start triggered")


# ── OBS Script API ────────────────────────────────────────────────────────

def script_description():
    return """<b>Sync Start</b><br>
Restarts two Media Sources and starts subtitle Browser Source simultaneously.<br><br>
Fill in the exact source names below, then assign a hotkey in <b>Settings → Hotkeys → Sync Start</b>."""


def script_properties():
    props = obs.obs_properties_create()

    obs.obs_properties_add_text(
        props, "media1", "Media Source 1 name", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(
        props, "media2", "Media Source 2 name", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(
        props, "browser", "Browser Source name (subtitles)", obs.OBS_TEXT_DEFAULT)

    return props


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, "media1", "Media Source 1")
    obs.obs_data_set_default_string(settings, "media2", "Media Source 2")
    obs.obs_data_set_default_string(settings, "browser", "Subtitles")


def script_update(settings):
    global _media1_name, _media2_name, _browser_name
    _media1_name = obs.obs_data_get_string(settings, "media1")
    _media2_name = obs.obs_data_get_string(settings, "media2")
    _browser_name = obs.obs_data_get_string(settings, "browser")


def script_load(settings):
    global _hotkey_id
    _hotkey_id = obs.obs_hotkey_register_frontend(
        "sync_start", "Sync Start (media + subtitles)", on_sync_start)

    hotkey_save_array = obs.obs_data_get_array(settings, "sync_start_hotkey")
    obs.obs_hotkey_load(_hotkey_id, hotkey_save_array)
    obs.obs_data_array_release(hotkey_save_array)


def script_save(settings):
    hotkey_save_array = obs.obs_hotkey_save(_hotkey_id)
    obs.obs_data_set_array(settings, "sync_start_hotkey", hotkey_save_array)
    obs.obs_data_array_release(hotkey_save_array)


def script_unload():
    obs.obs_hotkey_unregister(on_sync_start)
