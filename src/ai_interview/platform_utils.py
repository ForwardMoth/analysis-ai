"""Everything that differs between Windows, macOS and Linux lives here."""

import os
from pathlib import Path
import re
import subprocess
import sys
import time

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"

# Console-less child processes must not flash a terminal window on Windows.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0

MAX_FILE_NAME = 120  # leaves room for the 260-char MAX_PATH limit of older Windows setups
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = re.compile(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", re.I)


def configure_console() -> None:
    """Windows consoles default to cp1251/cp866 and choke on some characters in file names or logs."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def utf8_environment(env: dict[str, str]) -> dict[str, str]:
    """Forces UTF-8 in a Python child: its pipes would otherwise use the Windows ANSI code page."""
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def safe_file_name(name: str) -> str:
    """A name that is valid on every OS, so a data folder can be moved between Windows and macOS."""
    name = _ILLEGAL_CHARS.sub("_", name).strip(" .")
    stem, dot, suffix = name.rpartition(".") if "." in name else (name, "", "")
    suffix = (dot + suffix)[:16]
    stem = stem[:MAX_FILE_NAME - len(suffix)].rstrip(" .")
    if _RESERVED_NAMES.fullmatch(stem):
        stem = f"_{stem}"
    return (stem + suffix) or "interview"


def replace_file(src: Path, dst: Path, attempts: int = 20) -> None:
    """Atomic rename. On Windows it fails with PermissionError while a reader has the target open
    (antivirus and the indexer do this too), so retry briefly."""
    for attempt in range(attempts):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if not IS_WINDOWS or attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def write_text_atomic(path: Path, text: str, tmp_suffix: str) -> None:
    tmp = path.with_suffix(tmp_suffix)
    tmp.write_text(text, encoding="utf-8")
    replace_file(tmp, path)


def file_manager_name() -> str:
    """Prepositional case ('Показать в …') for the UI button."""
    if IS_WINDOWS:
        return "Проводнике"
    if IS_MAC:
        return "Finder"
    return "папке"


def reveal_in_file_manager(path: Path) -> None:
    if IS_WINDOWS:  # explorer reports exit code 1 even on success, so the result is ignored
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif IS_MAC:
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def kill_process_tree(proc: subprocess.Popen) -> None:
    """On Windows the claude/codex CLIs are .cmd shims, so killing only the shim would leave node running."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, creationflags=NO_WINDOW)
    proc.kill()
