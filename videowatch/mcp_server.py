"""videowatch MCP server. Exposes one tool, `analyse_video`, that any MCP
client (Claude Code CLI, Claude Desktop, others) can call to have a video
turned into contact sheets + transcript the model can read.

Run: `videowatch-mcp`  (stdio transport)
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

# The high-level server class was named FastMCP in mcp 1.x and renamed to
# MCPServer in mcp 2.x; both expose the same .tool()/.run() API and an Image
# content helper. Support whichever is installed.
try:
    from mcp.server.mcpserver import MCPServer as _Server, Image  # mcp >= 2.0
except Exception:
    try:
        from mcp.server.fastmcp import FastMCP as _Server, Image  # mcp 1.x
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "The 'mcp' package is required for the MCP server. "
            "Install with: pip install \"videowatch[mcp]\"  (or pip install mcp)\n"
            f"Import error: {e}"
        )

from .core import Options, process

mcp = _Server("videowatch")


@mcp.tool()
def analyse_video(
    path_or_url: str,
    max_frames: int = 48,
    scene: float = 0.20,
    frame_dim: int = 1280,
    ocr: bool = False,
    model: str = "base",
    no_audio: bool = False,
) -> list:
    """Watch a video, GIF, or video URL and return readable analysis material.

    Returns the contact-sheet montage images (each cell is a timestamped
    frame), the manifest, and the transcript text. For exact on-screen text,
    the full-resolution frames are saved in the returned output directory.

    Args:
        path_or_url: local video/GIF path, or an http(s) URL.
        max_frames: cap on sampled frames.
        scene: scene-change sensitivity 0..1 (lower = more frames).
        frame_dim: max readable-frame dimension in px (0 = native).
        ocr: run tesseract OCR per frame for exact on-screen text.
        model: whisper model (tiny|base|small|medium|large-v3).
        no_audio: skip transcription.
    """
    out = tempfile.mkdtemp(prefix="videowatch-mcp-")
    opts = Options(max_frames=max_frames, scene=scene, frame_dim=frame_dim,
                   ocr=ocr, model=model, no_audio=no_audio)
    res = process(path_or_url, out, opts)

    parts: list = []
    summary = [
        f"# Video analysis ready ({res.frames} frames)",
        f"- Output dir: {res.out}",
        f"- Full-resolution frames: {Path(res.out) / 'frames'}",
        f"- Manifest: {res.manifest}",
    ]
    transcript_path = Path(res.out) / "transcript.md"
    if res.has_transcript and transcript_path.exists():
        summary.append("\n## Transcript\n")
        summary.append(transcript_path.read_text(encoding="utf-8"))
    else:
        summary.append(f"- Transcript: none ({res.transcript_note})")
    if res.has_ocr:
        ocr_path = Path(res.out) / "frames_ocr.md"
        if ocr_path.exists():
            summary.append("\n## OCR (verbatim on-screen text)\n")
            summary.append(ocr_path.read_text(encoding="utf-8"))

    parts.append("\n".join(summary))
    for s in res.sheets:
        data = Path(s).read_bytes()
        parts.append(Image(data=data, format="jpeg"))
    return parts


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
