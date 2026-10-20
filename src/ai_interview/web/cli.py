"""Runs the user's own claude / codex CLI (their login, no API keys): command line, rate-limit retries, result."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from ..platform_utils import NO_WINDOW, kill_process_tree, utf8_environment
from . import config

PROVIDER_BINARIES = {"claude": "claude", "chatgpt": "codex"}
# ~/.codex/config.toml (and its model cache) may name a model a ChatGPT account rejects, so never rely on Codex's default
DEFAULT_CODEX_MODEL = "gpt-5.6-sol"
RATE_LIMIT_RE = re.compile(r"\b429\b|too many requests|rate.?limit", re.I)
RATE_LIMIT_PAUSES = (30, 90, 180, 300)  # seconds before each repeat


def available_tools() -> dict[str, bool]:
    return {provider: bool(shutil.which(binary)) for provider, binary in PROVIDER_BINARIES.items()}


def build_command(provider: str, model: str, out_file: Path, tools: tuple[str, ...] = (),
                  frames: list[Path] | None = None) -> list[str]:
    """`tools` are the only tools Claude may use; `frames` are screenshots handed to the model. The prompt goes in via stdin."""
    binary = shutil.which(PROVIDER_BINARIES[provider]) or PROVIDER_BINARIES[provider]
    frames = frames or []
    if provider == "claude":
        cmd = [binary, "-p", "--no-session-persistence", "--tools", ",".join(tools)]
        if tools:
            cmd += ["--allowedTools", *tools]
        if frames:  # Claude reads the frames itself, only from their own folder
            cmd += ["--add-dir", str(frames[0].parent)]
        return cmd + (["--model", model] if model else [])
    cmd = [binary, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-o", str(out_file),
           "-m", model or DEFAULT_CODEX_MODEL]
    for frame in frames:
        cmd += ["-i", str(frame)]
    return cmd + ["-"]


def ask(provider: str, model: str, prompt: str, cwd: Path, out_file: Path, tools: tuple[str, ...] = (),
        frames: list[Path] | None = None) -> str:
    """Sends the prompt and returns the answer; `cwd` should be an empty folder so the CLI sees no project files."""
    cwd.mkdir(parents=True, exist_ok=True)
    proc = run(build_command(provider, model, out_file, tools, frames), prompt, cwd)
    text = out_file.read_text(encoding="utf-8") if provider == "chatgpt" and out_file.is_file() else proc.stdout
    text = text.strip()
    if proc.returncode != 0 or not text:
        raise RuntimeError(error_summary(proc))
    return text


def run(cmd: list[str], prompt: str, cwd: Path) -> subprocess.CompletedProcess:
    """A run has several requests in a row (tasks with screenshots, then the report), which can hit the
    provider's rate limit (429); wait and repeat instead of failing the whole analysis."""
    for pause in (*RATE_LIMIT_PAUSES, None):
        proc = _run_once(cmd, prompt, cwd)
        output = f"{proc.stderr}\n{proc.stdout}" if proc.returncode else ""
        if pause is None or not RATE_LIMIT_RE.search(output):
            return proc
        time.sleep(pause)
    return proc


def _run_once(cmd: list[str], prompt: str, cwd: Path) -> subprocess.CompletedProcess:
    """subprocess.run would leave the real CLI (node behind a .cmd shim on Windows) running after a timeout."""
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace", cwd=cwd,
                          env=utf8_environment(os.environ.copy()), creationflags=NO_WINDOW) as proc:
        try:
            stdout, stderr = proc.communicate(prompt, timeout=config.ANALYSIS_TIMEOUT)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc)
            proc.communicate()
            raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def error_summary(proc: subprocess.CompletedProcess) -> str:
    err = proc.stderr or proc.stdout or f"код выхода {proc.returncode}"
    # codex echoes the whole prompt to stderr, so keep only the error lines
    error_lines = [line for line in err.splitlines() if "ERROR" in line or "rror:" in line]
    return ("\n".join(dict.fromkeys(error_lines)) if error_lines else err).strip()[-1500:]
