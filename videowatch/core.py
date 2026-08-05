"""
videowatch.core - cross-platform engine that turns a video (file, URL, GIF)
into artefacts a language model can read: near-native-resolution timestamped
frames, downscaled contact-sheet montages, optional OCR, and a whisper
transcript. Pure-local processing; nothing is uploaded.

Runs identically on Windows, macOS and Linux:
  - ffmpeg/ffprobe resolved from PATH, else pip-managed static-ffmpeg
  - font bundled in assets/, OS fonts only as fallback
  - all paths via pathlib/tempfile, drawtext paths escaped for every OS
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

URL_RE = re.compile(r"^https?://", re.I)
_ASSETS = Path(__file__).resolve().parent / "assets"


# --------------------------------------------------------------------------- #
# Tool + font resolution (the portability core)
# --------------------------------------------------------------------------- #

_TOOL_CACHE: dict[str, str] = {}


def _resolve_tool(name: str) -> str | None:
    if name in _TOOL_CACHE:
        return _TOOL_CACHE[name]
    p = shutil.which(name)
    if not p:
        # Fall back to pip-managed static binaries (downloaded once, per-OS).
        try:
            import static_ffmpeg  # type: ignore
            static_ffmpeg.add_paths()
            p = shutil.which(name)
        except Exception:
            p = None
    if p:
        _TOOL_CACHE[name] = p
    return p


def ffmpeg() -> str:
    p = _resolve_tool("ffmpeg")
    if not p:
        raise RuntimeError(
            "ffmpeg not found. Install it (macOS: `brew install ffmpeg`, "
            "Debian/Ubuntu: `sudo apt install ffmpeg`, Windows: `winget install "
            "ffmpeg`) or `pip install static-ffmpeg`."
        )
    return p


def ffprobe() -> str:
    p = _resolve_tool("ffprobe")
    if not p:
        raise RuntimeError(
            "ffprobe not found. It ships with ffmpeg; install ffmpeg or "
            "`pip install static-ffmpeg`."
        )
    return p


def resolve_font() -> str:
    bundled = _ASSETS / "DejaVuSans.ttf"
    if bundled.exists():
        return str(bundled)
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",              # Linux
        "/System/Library/Fonts/Supplemental/Arial.ttf",                # macOS
        "/Library/Fonts/Arial.ttf",                                    # macOS
        "C:/Windows/Fonts/arial.ttf",                                  # Windows
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise RuntimeError("no usable font found and bundled font missing")


def _ff_path(p: str) -> str:
    """Escape a path for use inside an ffmpeg filter (drawtext fontfile).

    Windows drive colons and backslashes must be escaped or ffmpeg parses
    them as filter option separators.
    """
    p = p.replace("\\", "/")
    return p.replace(":", "\\:")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _run(cmd: list[str], capture: bool = True):
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def fmt_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def fmt_ts_short(seconds: float) -> str:
    s = int(round(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# --------------------------------------------------------------------------- #
# Options + result
# --------------------------------------------------------------------------- #

@dataclass
class Options:
    max_frames: int = 60
    min_frames: int = 8
    scene: float = 0.20
    interval: float = 0.0          # 0 = auto by duration
    frame_dim: int = 1440          # 0 = native
    sheet_cell: int = 480
    cols: int = 4
    rows: int = 4
    ocr: bool = False
    model: str = field(default_factory=lambda: os.environ.get("WATCH_WHISPER_MODEL", "base"))
    no_audio: bool = False


@dataclass
class Result:
    out: str
    manifest: str
    sheets: list[str]
    frames: int
    duration: float
    has_transcript: bool
    has_ocr: bool
    transcript_note: str | None


# --------------------------------------------------------------------------- #
# Probe / sampling / extraction
# --------------------------------------------------------------------------- #

def probe(path: str) -> dict:
    rc, out, err = _run([ffprobe(), "-v", "error", "-print_format", "json",
                         "-show_format", "-show_streams", str(path)])
    if rc != 0:
        raise RuntimeError(f"ffprobe failed: {err.strip()}")
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if v is None:
        raise RuntimeError("no video stream found")
    dur = 0.0
    for src in (data.get("format", {}).get("duration"), v.get("duration")):
        try:
            dur = float(src)
            if dur > 0:
                break
        except (TypeError, ValueError):
            continue
    fr = v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1"
    try:
        num, den = fr.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "duration": dur,
        "width": int(v.get("width", 0)),
        "height": int(v.get("height", 0)),
        "fps": round(fps, 3),
        "vcodec": v.get("codec_name", "?"),
        "has_audio": a is not None,
        "acodec": a.get("codec_name") if a else None,
    }


def detect_scene_times(path: str, threshold: float) -> list[float]:
    rc, out, err = _run([ffmpeg(), "-hide_banner", "-i", str(path),
                         "-vf", f"select='gt(scene,{threshold})',showinfo",
                         "-an", "-f", "null", "-"])
    text = err + out
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", text)]
    return sorted(set(round(t, 3) for t in times))


def _uniform_grid(duration: float, interval: float) -> list[float]:
    if duration <= 0 or interval <= 0:
        return [0.0]
    n = max(1, int(duration // interval))
    return [round(duration * i / (n + 1), 3) for i in range(1, n + 1)]


def pick_times(scene_times, duration, min_f, max_f, interval, tol=0.4):
    times = {0.0}
    times.update(_uniform_grid(duration, interval))
    times.update(scene_times)
    if duration > 0:
        times.add(round(max(0.0, duration - 0.15), 3))
    ordered = sorted(times)

    dedup: list[float] = []
    for t in ordered:
        if not dedup or t - dedup[-1] >= tol:
            dedup.append(t)
    ordered = dedup

    if len(ordered) < min_f and duration > 0:
        extra = _uniform_grid(duration, max(0.4, duration / (min_f + 1)))
        ordered = sorted(set(ordered) | set(extra))

    if len(ordered) > max_f:
        idx = [round(i * (len(ordered) - 1) / (max_f - 1)) for i in range(max_f)]
        ordered = [ordered[i] for i in sorted(set(idx))]

    if duration > 0:
        ordered = [t for t in ordered if t <= duration + 0.05]
    return ordered


def _esc_drawtext(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def extract_frame(path, t, dst, frame_dim, label, font):
    if frame_dim and frame_dim > 0:
        scale = (f"scale='min({frame_dim},iw)':'min({frame_dim},ih)'"
                 f":force_original_aspect_ratio=decrease")
    else:
        scale = "scale=iw:ih"
    draw = (
        f"drawtext=fontfile={_ff_path(font)}:text='{_esc_drawtext(label)}'"
        f":fontcolor=white:fontsize=22:box=1:boxcolor=black@0.65:boxborderw=8"
        f":x=10:y=10"
    )
    rc, _, err = _run([ffmpeg(), "-hide_banner", "-y", "-ss", f"{t:.3f}",
                       "-i", str(path), "-frames:v", "1",
                       "-vf", f"{scale},{draw}", "-q:v", "2", str(dst)])
    return rc == 0 and Path(dst).exists()


def build_sheets(frames_dir, sheets_dir, cols, rows, cell_w):
    sheets_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(frames_dir / "frame_%04d.jpg")
    _run([ffmpeg(), "-hide_banner", "-y", "-framerate", "1", "-i", pattern,
          "-vf", (f"scale={cell_w}:-2,"
                  f"tile={cols}x{rows}:padding=6:margin=6:color=0x202020"),
          "-vsync", "vfr", "-q:v", "3", str(sheets_dir / "sheet_%03d.jpg")])
    return sorted(sheets_dir.glob("sheet_*.jpg"))


def ocr_frames(kept, out: Path):
    if not shutil.which("tesseract"):
        return None, "tesseract not installed"
    lines = []
    for _, t, dst in kept:
        rc, o, e = _run(["tesseract", str(dst), "stdout", "--psm", "6"])
        lines.append((t, Path(dst).name, " ".join(o.split()) if rc == 0 else ""))
    path = out / "frames_ocr.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("# On-screen text (OCR, verbatim per frame)\n\n")
        for t, name, text in lines:
            f.write(f"### {fmt_ts(t)}  ({name})\n\n{text or '_(no text detected)_'}\n\n")
    return path, None


def transcribe(wav: Path, model_name: str, models_dir: Path):
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:
        return None, f"faster-whisper not available ({e})"
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8",
                             download_root=str(models_dir))
        segments, info = model.transcribe(
            str(wav), vad_filter=True, condition_on_previous_text=False)
        lines = [f"[{fmt_ts_short(s.start)} -> {fmt_ts_short(s.end)}] {s.text.strip()}"
                 for s in segments]
        return {
            "language": info.language,
            "language_probability": round(getattr(info, "language_probability", 0) or 0, 3),
            "lines": lines,
        }, None
    except Exception as e:
        return None, f"transcription failed: {e}"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def _fetch_url(url: str, workdir: Path) -> str:
    try:
        import yt_dlp  # noqa: F401
        exe = shutil.which("yt-dlp")
    except Exception:
        exe = shutil.which("yt-dlp")
    if not exe:
        raise RuntimeError("yt-dlp not available; `pip install yt-dlp`")
    target = str(workdir / "video.%(ext)s")
    rc, o, e = _run([exe, "-f", "mp4/best", "-o", target, url])
    if rc != 0:
        raise RuntimeError(f"yt-dlp failed: {e.strip()[:400]}")
    files = list(workdir.glob("video.*"))
    if not files:
        raise RuntimeError("download produced no file")
    return str(files[0])


def process(input_path: str, out_dir: str, opts: Options | None = None,
            log=lambda m: None) -> Result:
    opts = opts or Options()
    font = resolve_font()
    ffmpeg()  # fail fast with a clear message if missing

    out = Path(out_dir).expanduser().resolve()
    frames_dir = out / "frames"
    sheets_dir = out / "sheets"
    frames_dir.mkdir(parents=True, exist_ok=True)
    models_dir = Path(os.environ.get(
        "WATCH_MODELS_DIR",
        Path.home() / ".cache" / "videowatch" / "models")).expanduser()
    models_dir.mkdir(parents=True, exist_ok=True)

    tmp: str | None = None
    src = input_path
    if URL_RE.match(input_path):
        tmp = tempfile.mkdtemp(prefix="videowatch-dl-")
        log("Downloading URL ...")
        src = _fetch_url(input_path, Path(tmp))
    elif not os.path.exists(src):
        raise RuntimeError(f"input not found: {src}")

    info = probe(src)
    log(f"Probed {info['width']}x{info['height']} {fmt_ts_short(info['duration'])} "
        f"audio={info['has_audio']}")

    interval = opts.interval if opts.interval > 0 else max(1.0, info["duration"] / 24.0)
    scene_times = detect_scene_times(src, opts.scene)
    times = pick_times(scene_times, info["duration"], opts.min_frames,
                       opts.max_frames, interval)
    log(f"{len(scene_times)} scene changes, grid {interval:.1f}s -> {len(times)} frames")

    kept = []
    for i, t in enumerate(times, 1):
        dst = frames_dir / f"frame_{i:04d}.jpg"
        if extract_frame(src, t, dst, opts.frame_dim, fmt_ts(t), font):
            kept.append((i, t, dst))

    sheets = build_sheets(frames_dir, sheets_dir, opts.cols, opts.rows, opts.sheet_cell)
    log(f"{len(kept)} frames, {len(sheets)} contact sheets")

    ocr_path, ocr_note = (None, None)
    if opts.ocr:
        log("Running OCR ...")
        ocr_path, ocr_note = ocr_frames(kept, out)

    transcript, transcript_note = (None, None)
    if info["has_audio"] and not opts.no_audio:
        wav = out / "audio.wav"
        rc, _, e = _run([ffmpeg(), "-hide_banner", "-y", "-i", src,
                         "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        if rc == 0 and wav.exists():
            log(f"Transcribing (whisper '{opts.model}') ...")
            transcript, transcript_note = transcribe(wav, opts.model, models_dir)
        else:
            transcript_note = "audio extraction failed"
    elif not info["has_audio"]:
        transcript_note = "no audio track"
    else:
        transcript_note = "skipped (no-audio)"

    if transcript:
        with open(out / "transcript.md", "w", encoding="utf-8") as f:
            f.write(f"# Transcript ({transcript['language']}, "
                    f"p={transcript['language_probability']})\n\n")
            f.write("\n".join(transcript["lines"]) + "\n")

    man = out / "manifest.md"
    _write_manifest(man, out, input_path, info, opts, interval, kept, sheets,
                    ocr_path, ocr_note, transcript, transcript_note)

    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)

    return Result(
        out=str(out), manifest=str(man), sheets=[str(s) for s in sheets],
        frames=len(kept), duration=info["duration"],
        has_transcript=bool(transcript), has_ocr=bool(ocr_path),
        transcript_note=transcript_note,
    )


def _write_manifest(man, out, source, info, opts, interval, kept, sheets,
                    ocr_path, ocr_note, transcript, transcript_note):
    with open(man, "w", encoding="utf-8") as f:
        f.write("# Video analysis package\n\n")
        f.write(f"- Source: `{source}`\n")
        f.write(f"- Resolution: {info['width']}x{info['height']} @ {info['fps']} fps\n")
        f.write(f"- Duration: {fmt_ts_short(info['duration'])} ({info['duration']:.1f}s)\n")
        f.write(f"- Video codec: {info['vcodec']} | audio: {info['acodec'] or 'none'}\n")
        f.write(f"- Frames sampled: {len(kept)} (scene {opts.scene}, grid "
                f"{interval:.1f}s, frame-dim {opts.frame_dim or 'native'})\n\n")
        f.write("## How to read this\n\n")
        f.write("1. Read the contact sheets for the timeline overview: each cell is "
                "one frame with its timestamp burned into the top-left corner. Sheets "
                "are downscaled, so do NOT read fine text off them.\n")
        f.write("2. To read exact on-screen text (filenames, labels, errors), open "
                "the specific full-resolution frame in `frames/`.\n")
        if ocr_path:
            f.write("3. `frames_ocr.md` has pixel-accurate OCR text per frame; trust "
                    "it over visual reading for exact strings.\n")
        if transcript:
            f.write("4. `transcript.md` has the timestamped spoken audio.\n")
        f.write("\n## Contact sheets (overview)\n\n")
        for s in sheets:
            f.write(f"- `{s}`\n")
        f.write("\n## Frame timeline (full-resolution, read for detail)\n\n")
        for _, t, dst in kept:
            f.write(f"- {fmt_ts(t)}  ->  `{dst}`\n")
        f.write("\n## Text extraction\n\n")
        if ocr_path:
            f.write(f"- OCR: `{ocr_path}`\n")
        elif ocr_note:
            f.write(f"- OCR: not run ({ocr_note})\n")
        else:
            f.write("- OCR: not requested (pass --ocr)\n")
        f.write("\n## Audio\n\n")
        if transcript:
            f.write(f"- Transcript: `{out / 'transcript.md'}` "
                    f"({len(transcript['lines'])} segments, "
                    f"lang={transcript['language']})\n")
        else:
            f.write(f"- No transcript: {transcript_note}\n")
