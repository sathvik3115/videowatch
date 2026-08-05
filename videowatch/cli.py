"""videowatch CLI. `videowatch <path-or-url> --out <dir>` produces the
analysis package (frames, sheets, transcript, manifest). Prints a JSON summary
on the last stdout line; progress goes to stderr."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .core import Options, process


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="videowatch",
        description="Prepare a video (file, URL, GIF) for a model to read.")
    ap.add_argument("input", help="video file path, GIF, or http(s) URL")
    ap.add_argument("--out", default=None,
                    help="output directory (default: a temp dir)")
    ap.add_argument("--max-frames", type=int, default=60)
    ap.add_argument("--min-frames", type=int, default=8)
    ap.add_argument("--scene", type=float, default=0.20,
                    help="scene sensitivity 0..1 (lower = more frames)")
    ap.add_argument("--interval", type=float, default=0,
                    help="seconds between grid frames (0 = auto)")
    ap.add_argument("--frame-dim", type=int, default=1440,
                    help="max readable-frame dimension px (0 = native)")
    ap.add_argument("--sheet-cell", type=int, default=480)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--ocr", action="store_true",
                    help="OCR each frame (needs tesseract)")
    ap.add_argument("--model", default=None,
                    help="whisper model: tiny|base|small|medium|large-v3")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out = args.out or tempfile.mkdtemp(prefix="videowatch-")
    opts = Options(
        max_frames=args.max_frames, min_frames=args.min_frames, scene=args.scene,
        interval=args.interval, frame_dim=args.frame_dim, sheet_cell=args.sheet_cell,
        cols=args.cols, rows=args.rows, ocr=args.ocr, no_audio=args.no_audio,
    )
    if args.model:
        opts.model = args.model
    log = (lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))
    try:
        res = process(args.input, out, opts, log=log)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps({
        "out": res.out, "manifest": res.manifest, "sheets": res.sheets,
        "frames": res.frames, "duration": res.duration,
        "has_transcript": res.has_transcript, "has_ocr": res.has_ocr,
        "transcript_note": res.transcript_note,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
