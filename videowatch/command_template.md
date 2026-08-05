---
description: Watch and analyse a video, GIF, or video URL (frames + transcript)
argument-hint: <path-or-url> [extra flags]
allowed-tools: Bash, Read
---

You have been asked to watch and analyse a video.

Input from the user: `$ARGUMENTS`

Do the following:

1. Pick an output directory in your session scratchpad, e.g.
   `<SCRATCHPAD>/watch-run`. Forward any extra flags the user passed after the
   path/URL (for example `--scene 0.15`, `--max-frames 60`, `--ocr`,
   `--no-audio`, `--model small`) to the command unchanged.

2. Run the tool (installed globally as `videowatch`):

   ```
   videowatch "<PATH_OR_URL>" --out "<SCRATCHPAD>/watch-run" [extra flags]
   ```

   The last stdout line is JSON with `manifest`, `sheets`, `frames`,
   `has_transcript`, `has_ocr`. Progress goes to stderr.

3. Read `manifest.md`, then Read every contact sheet under "Contact sheets"
   for the timeline overview (each cell is a timestamped frame). The sheets
   are downscaled: to read exact on-screen text (filenames, labels, errors),
   Read the specific full-resolution frame from the `frames/` directory. If
   `frames_ocr.md` exists, trust it for exact strings.

4. If a transcript exists, Read `transcript.md` and correlate the audio with
   the frames.

5. Answer the user's question. If they only said "watch it", give a concise
   timeline summary: what happens, when (timestamps), and anything notable
   (errors on screen, UI states, spoken points).

Notes:
- Everything is processed locally; nothing is uploaded.
- First run downloads the whisper model once, then caches it.
- Handles video files, animated GIFs, and http(s) URLs.
