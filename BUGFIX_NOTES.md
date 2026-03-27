# SteamClip v4.0 Bug Fix Notes

**Issue:** [#26 — Clips not displaying after v4.0 update](https://github.com/Nastas95/SteamClip/issues/26)
**Date:** 2026-03-27
**Contributors:** bra-khet (investigation, direction, review) and Claude Opus (diagnosis, implementation)

---

Hey Nastas95 and team,

First off — thank you for building SteamClip. It's a genuinely useful tool for the Steam community, and the v4.0 rewrite introduced a lot of solid improvements (the new theme, the media type filtering, the background recording support). We really appreciate the work that went into it.

We ran into the issue described in #26 (clips not showing up after the v4.0 update on Windows) and dug into the root cause. Below is a detailed breakdown of everything we found and changed, written to be easy to review, cherry-pick, or modify as you see fit.

---

## Root Cause Summary

The primary issue is a **signal chain timing problem** during GUI initialization. When `populate_steamid_dirs()` adds items to the Steam ID combo box, Qt fires `currentIndexChanged`, which triggers `on_steamid_selected()` → `filter_media_type()`. At this point the media type combo box still contains its initial items from `__init__`, and one of those items had a **different string** than what `filter_media_type()` checks against. This caused the clip folder list to never be populated.

Several secondary issues compounded the problem, making it harder to diagnose and more likely to silently fail.

---

## Fixes Applied (all in `steamclip.py`)

### Fix 1 — Media type string mismatch (line ~415)

**What:** Changed `"Background Clips"` to `"Background Recordings"` in the `__init__` combo box setup.

**Why:** `filter_media_type()` and `update_media_type_combo()` both use `"Background Recordings"`, but `__init__` used `"Background Clips"`. During the initialization signal chain, if `filter_media_type()` ran before `update_media_type_combo()` had a chance to repopulate the combo, the selected text would be `"Background Clips"` — which matched none of the `if`/`elif` branches. Since there was no `else` clause (see Fix 2), `self.clip_folders` was never assigned.

**How we found it:** Compared every string literal used for media type filtering across `__init__`, `update_media_type_combo()`, and `filter_media_type()`. The TEST file (`steamclip_TEST.py`) already used the correct string.

---

### Fix 2 — Missing `else` clause in `filter_media_type()` (line ~871)

**What:** Added a default `else` branch that falls back to showing all clips and logs a warning.

**Why:** Without an `else`, any unrecognized media type string (including the typo from Fix 1, or an empty combo state during initialization) would silently leave `self.clip_folders` as whatever it was before — typically `[]` from `__init__`. This made the bug completely silent: no errors, no warnings, just an empty grid.

---

### Fix 3 — `filter_media_type()` call outside `finally` block (line ~957)

**What:** Moved `self.filter_media_type()` from after the `try`/`finally` in `update_media_type_combo()` to inside the `finally` block.

**Why:** If the `try` block hit an early `return` (e.g., when `selected_steamid` was empty), the `finally` block correctly unblocked signals, but `filter_media_type()` — which is the sole entry point for clip discovery — was never called. This meant clips would not load on certain code paths. The TEST version already had this call inside `finally`.

**How we found it:** Side-by-side comparison of `update_media_type_combo()` in `steamclip.py` vs `steamclip_TEST.py`.

---

### Fix 4 — `clear_clip_grid()` not properly draining the layout (line ~873)

**What:** Changed from iterating with `range(count)` + `deleteLater()` to a `while count()` loop using `takeAt(0)` + `setParent(None)` + `deleteLater()`.

**Why:** `deleteLater()` defers widget destruction to the next event loop cycle. Without removing items from the layout first, repeated calls to `display_clips()` during init (triggered by the signal chain) accumulated invisible stale widgets in the grid. The old approach also iterated forward while the count was changing, which is unreliable. The new approach properly drains the layout.

---

### Fix 5 — `extract_datetime_from_folder_name()` splitting full paths (line ~946)

**What:** Added `os.path.basename(folder_path)` before splitting by `_`.

**Why:** The function received full paths like `C:\Program Files (x86)\Steam\userdata\12345\gamerecordings\clips\clip_730_20260327_120000` and split the entire string by `_`. This happened to work on default Steam paths (no underscores in parent directories), but would break on any custom path containing underscores (e.g., `D:\My_Games\Steam\...`). Using `basename()` isolates just the folder name before parsing.

---

### Fix 6 — `populate_gameid_combo()` splitting full paths (line ~957)

**What:** Changed `folder.split('_')[1]` to `os.path.basename(folder).split('_')[1]` with a guard for folders containing `_`.

**Why:** Same root cause as Fix 5. Extracting game IDs from full paths is fragile. The `if '_' in os.path.basename(folder)` guard also prevents `IndexError` on malformed folder names.

---

### Fix 7 — `SettingsWindow.update_game_ids()` splitting full paths (line ~1578)

**What:** Same `basename()` fix applied to the Settings window's game ID extraction.

**Why:** This code path was independently parsing folder names with the same fragile pattern. Kept in sync with Fix 6.

---

### Fix 8 — Thumbnail fallback for read-only clip directories (line ~1064)

**What:** Added a fallback that creates placeholder thumbnails in the system temp directory when the clip folder itself isn't writable.

**Why:** If `extract_first_frame()` and `create_placeholder_thumbnail()` both failed (e.g., because the Steam directory has restricted write permissions), the clip was silently dropped from the display grid. Now there's a last-resort fallback, and a log warning if even that fails.

---

### Fix 9 — HTTP request timeout for Steam API calls (line ~693)

**What:** Added `timeout=5` to `requests.get()` in `fetch_game_name_from_steam()`.

**Why:** This function is called synchronously for each unknown game ID during `populate_gameid_combo()`. Without a timeout, a slow or unreachable Steam API would freeze the entire GUI indefinitely, preventing clips from ever appearing.

---

### Fix 10 — Diagnostic logging in `filter_media_type()` (lines ~856–870)

**What:** Added logging for each directory scan showing the path checked and folder count found.

**Why:** The original code had minimal logging in this critical function. When clips fail to load, these logs immediately reveal which directories were checked and whether any folders were found, making future debugging much faster.

---

## How to Verify

1. Launch SteamClip with valid clips in the default Steam directory
2. Clips should appear in the grid immediately after selecting a Steam ID
3. Switch between "All Clips", "Manual Clips", and "Background Recordings" — each should filter correctly
4. Check the log output for the new diagnostic lines showing directory scan results

## Files Changed

- `steamclip.py` — 101 insertions, 9 deletions (all fixes + inline documentation)

---

Thanks again for SteamClip — happy to discuss any of these changes or adjust the approach. Hope this helps!

— bra-khet & Claude Opus
