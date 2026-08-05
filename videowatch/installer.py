"""One-command, cross-platform setup: `videowatch-setup`.

Registers the tool with whatever Claude surfaces are present:
  - Claude Code CLI: installs the /watch slash command and (if the `claude`
    binary is found) registers the MCP server at user scope.
  - Claude Desktop: merges an mcpServers entry into the desktop config.
It is idempotent and never hard-fails; each surface is best-effort and
reported at the end.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
COMMAND_SRC = PKG / "command_template.md"

# The most robust way to invoke the server on any machine: the same
# interpreter that installed the package, running the module.
MCP_CMD = sys.executable
MCP_ARGS = ["-m", "videowatch.mcp_server"]


def _ok(m): print(f"  [ok]   {m}")
def _skip(m): print(f"  [skip] {m}")
def _warn(m): print(f"  [warn] {m}")


def check_dependencies() -> list[str]:
    problems = []
    try:
        from . import core
        core.ffmpeg(); core.ffprobe()
        _ok("ffmpeg / ffprobe available")
    except Exception as e:
        problems.append(str(e)); _warn(f"ffmpeg: {e}")
    try:
        import faster_whisper  # noqa: F401
        _ok("faster-whisper available")
    except Exception:
        _warn("faster-whisper not importable (audio transcription will be skipped)")
    try:
        import yt_dlp  # noqa: F401
        _ok("yt-dlp available (URL support)")
    except Exception:
        _warn("yt-dlp not importable (URL input will fail)")
    return problems


def install_cli_command() -> None:
    cmd_dir = Path.home() / ".claude" / "commands"
    if not (Path.home() / ".claude").exists():
        _skip("Claude Code not detected (~/.claude missing); slash command not installed")
        return
    cmd_dir.mkdir(parents=True, exist_ok=True)
    dst = cmd_dir / "watch.md"
    shutil.copyfile(COMMAND_SRC, dst)
    _ok(f"/watch slash command installed -> {dst}")


def register_cli_mcp() -> None:
    claude = shutil.which("claude")
    if not claude:
        _skip("`claude` CLI not found; skipping Claude Code MCP registration")
        return
    # Remove any prior registration so this is idempotent.
    subprocess.run([claude, "mcp", "remove", "videowatch", "--scope", "user"],
                   capture_output=True, text=True)
    cmd = [claude, "mcp", "add", "videowatch", "--scope", "user",
           "--", MCP_CMD, *MCP_ARGS]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        _ok("MCP server registered with Claude Code (user scope)")
    else:
        _warn(f"Claude Code MCP registration failed: {r.stderr.strip()[:200]}")


def desktop_config_path() -> Path | None:
    sysname = platform.system()
    if sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sysname == "Windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def register_desktop_mcp() -> None:
    cfg = desktop_config_path()
    if cfg is None or not cfg.parent.exists():
        _skip("Claude Desktop not detected; skipping desktop MCP registration")
        _print_desktop_snippet()
        return
    data = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            _warn(f"existing desktop config unreadable; not modifying {cfg}")
            _print_desktop_snippet()
            return
    servers = data.setdefault("mcpServers", {})
    servers["videowatch"] = {"command": MCP_CMD, "args": MCP_ARGS}
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _ok(f"MCP server added to Claude Desktop config -> {cfg} (restart Desktop)")


def _print_desktop_snippet() -> None:
    snippet = {"mcpServers": {"videowatch": {"command": MCP_CMD, "args": MCP_ARGS}}}
    print("\n  To enable in Claude Desktop, add this to claude_desktop_config.json:\n")
    print("  " + json.dumps(snippet, indent=2).replace("\n", "\n  "))


def main() -> int:
    print("videowatch setup\n")
    print("Checking dependencies:")
    check_dependencies()
    print("\nClaude Code CLI:")
    install_cli_command()
    register_cli_mcp()
    print("\nClaude Desktop:")
    register_desktop_mcp()
    print("\nDone. In Claude Code use:  /watch <path-or-url>")
    print("In any MCP client, the tool is:  analyse_video")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
