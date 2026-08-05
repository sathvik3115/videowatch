# videowatch

Let Claude (or any model) **watch and analyse videos**, screen recordings,
tutorials, meetings, GIFs, animations, or a video URL. It runs **entirely on
your machine**: nothing is uploaded.

It works because a model reads images and text, not video. `videowatch` turns a
video into: scene-aware **timestamped frames**, **contact-sheet** overviews, an
optional **OCR** pass for exact on-screen text, and a **whisper transcript** —
then hands those to Claude.

Runs on **Windows, macOS and Linux**. Every dependency is bundled or
pip-managed, so a fresh machine needs nothing pre-installed.

---

## Install (one command)

With [pipx](https://pipx.pypa.io) (recommended, isolated, global command):

```
pipx install "git+https://github.com/sathvik3115/videowatch.git#egg=videowatch[mcp]"
videowatch-setup
```

Or with pip:

```
pip install "git+https://github.com/sathvik3115/videowatch.git#egg=videowatch[mcp]"
videowatch-setup
```

`videowatch-setup` is cross-platform (pure Python). It:
- installs the `/watch` slash command for **Claude Code CLI**,
- registers the **MCP server** with Claude Code (if the `claude` CLI is found),
- adds the MCP server to **Claude Desktop** (or prints the snippet to paste),
- verifies ffmpeg / whisper / yt-dlp.

> The first transcription downloads a small whisper model once, then caches it.

---

## Use

**Claude Code CLI**

```
/watch /path/to/recording.mp4
/watch /path/to/demo.gif
/watch https://youtu.be/...
/watch /path/to/screencast.webm --ocr        # exact on-screen text
/watch /path/to/talk.mp4 --model small        # better audio accuracy
```

**Claude Desktop / any MCP client**

The tool `analyse_video(path_or_url, ...)` appears automatically. Just ask
Claude to analyse a video and point it at a path or URL.

**Standalone CLI** (no Claude needed, produces the analysis folder)

```
videowatch /path/to/video.mp4 --out ./out
# then open ./out/manifest.md, ./out/sheets/, ./out/transcript.md
```

---

## Options

| Flag | Meaning |
|---|---|
| `--scene 0.15` | more frames (lower = more sensitive to change) |
| `--max-frames 60` | cap on sampled frames |
| `--interval 1.0` | force one grid frame per N seconds |
| `--frame-dim 1440` | readable-frame resolution (0 = native) |
| `--ocr` | pixel-accurate on-screen text (needs `tesseract`) |
| `--model small` | whisper model: tiny\|base\|small\|medium\|large-v3 |
| `--no-audio` | skip transcription |

---

## How it works

1. **Probe** the video (ffprobe).
2. **Sample frames** as the union of scene-changes and a duration-scaled
   uniform grid, so nothing brief is missed. Each frame is stamped with its
   timestamp at near-native resolution.
3. **Contact sheets**: frames tiled into downscaled grids for a cheap timeline
   overview; full-res frames kept for reading detail.
4. **Transcript**: audio (if any) transcribed with faster-whisper, VAD-filtered
   to suppress music hallucination.
5. **Manifest** tells the model exactly what to read.

### Notes on audio with music
Whisper is a speech model. Instrumental background music is mostly suppressed by
the VAD filter; vocals get transcribed as if speech; loud music over narration
degrades accuracy, use `--model small`/`medium` for those.

---

## Requirements

- Python 3.9+
- ffmpeg (auto-provided by `static-ffmpeg` if your system lacks it)
- Optional: `tesseract` for `--ocr`

## Privacy

All processing is local. URLs are fetched with yt-dlp to a temp dir and deleted
after processing. No video, frame, or transcript leaves your machine.

## License

MIT
