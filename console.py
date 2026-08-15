"""
console.py
Clean, minimal terminal output for the IQ Option bot.

Everything the bot prints goes through this module so the terminal shows
ONLY what matters:

  * one "floating" status line (with a spinner) that always shows what the
    bot is doing right now and is replaced in-place when the task changes;
  * clean, colour-coded event lines (info / success / warning / error);
  * a pretty banner + final summary.

The standard `logging` module is wired into this console via
`ConsoleLogHandler`, so every `logger.error(...)` / `logger.warning(...)`
in the codebase automatically becomes a clean terminal line too.
"""

import logging
import os
import sys
import threading
import time
from contextlib import contextmanager

# --------------------------------------------------------------------------- #
#  Output / colour setup
# --------------------------------------------------------------------------- #


def _enable_windows_vt() -> None:
    """Enable ANSI escape sequences on legacy Windows consoles."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _force_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


_enable_windows_vt()
_force_utf8_stdout()

_IS_TTY = bool(getattr(sys.stdout, "isatty", lambda: False)())
_NO_COLOR = os.environ.get("NO_COLOR", "").strip() != ""
_COLOR = _IS_TTY and not _NO_COLOR


class _Palette:
    def __init__(self):
        self.RESET = "\033[0m"
        self.BOLD = "\033[1m"
        self.DIM = "\033[2m"
        self.GREEN = "\033[92m"
        self.RED = "\033[91m"
        self.YELLOW = "\033[93m"
        self.CYAN = "\033[96m"
        self.BLUE = "\033[94m"
        self.MAGENTA = "\033[95m"
        self.GREY = "\033[90m"

    def paint(self, name: str, text: str) -> str:
        if not _COLOR:
            return text
        return f"{getattr(self, name, '')}{text}{self.RESET}"


PALETTE = _Palette()


def _markers() -> dict:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    utf8 = "utf" in enc
    return {
        "spinner": (
            ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            if utf8
            else ["|", "/", "-", "\\"]
        ),
        "info": "•" if utf8 else "-",
        "success": "✓" if utf8 else "OK",
        "warning": "!" if utf8 else "!",
        "error": "✗" if utf8 else "ERR",
        "event": "»" if utf8 else ">",
    }


_MARKERS = _markers()


class Console:
    """Manages the single floating status line + clean event lines."""

    SPIN_INTERVAL = 0.08

    def __init__(self):
        self._lock = threading.RLock()
        self._status_text = None
        self._spin_idx = 0
        self._spin_thread = None
        self._spin_alive = False

    # ------------------------------------------------------------------ #
    #  Spinner (keeps the status line animated in the background)
    # ------------------------------------------------------------------ #

    def _ensure_spinner(self) -> None:
        if not _IS_TTY:
            return
        if self._spin_thread and self._spin_thread.is_alive():
            return
        self._spin_alive = True
        self._spin_thread = threading.Thread(target=self._spin_loop, daemon=True)
        self._spin_thread.start()

    def _spin_loop(self) -> None:
        while self._spin_alive:
            with self._lock:
                if self._status_text is not None:
                    self._spin_idx += 1
                    self._draw_status()
            time.sleep(self.SPIN_INTERVAL)

    # ------------------------------------------------------------------ #
    #  Low-level line helpers
    # ------------------------------------------------------------------ #

    def _clear_line(self) -> None:
        if _IS_TTY:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _draw_status(self) -> None:
        if self._status_text is None:
            return
        if _IS_TTY:
            spin = _MARKERS["spinner"][self._spin_idx % len(_MARKERS["spinner"])]
            sys.stdout.write("\r\033[K" + PALETTE.paint("CYAN", spin) + " " + self._status_text)
            sys.stdout.flush()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def status(self, text: str) -> None:
        """Update the single floating status line (in place)."""
        text = str(text)
        with self._lock:
            if _IS_TTY:
                self._status_text = text
                self._ensure_spinner()
                self._draw_status()
            else:
                if text != self._status_text:
                    sys.stdout.write(f"[{_MARKERS['info']}] {text}\n")
                    sys.stdout.flush()
                self._status_text = text

    def clear_status(self) -> None:
        """Remove the status line (task finished)."""
        with self._lock:
            self._clear_line()
            self._status_text = None

    def _emit(self, marker: str, color: str, text: str) -> None:
        text = str(text)
        with self._lock:
            self._clear_line()
            sys.stdout.write(f"  {PALETTE.paint(color, marker)} {text}\n")
            sys.stdout.flush()
            self._draw_status()

    def info(self, text: str) -> None:
        self._emit(_MARKERS["info"], "BLUE", text)

    def success(self, text: str) -> None:
        self._emit(_MARKERS["success"], "GREEN", text)

    def warning(self, text: str) -> None:
        self._emit(_MARKERS["warning"], "YELLOW", text)

    def error(self, text: str) -> None:
        self._emit(_MARKERS["error"], "RED", text)

    def event(self, text: str) -> None:
        self._emit(_MARKERS["event"], "MAGENTA", text)

    @contextmanager
    def task(self, text: str, ok_text: str = None, fail_text: str = None):
        """Show `text` on the status line while a block of work runs."""
        self.status(text)
        try:
            yield
        except Exception:
            self.error(fail_text or f"{text} — failed")
            raise
        else:
            if ok_text:
                self.success(ok_text)

    # ------------------------------------------------------------------ #
    #  Banner / summary
    # ------------------------------------------------------------------ #

    def banner(self, title: str, fields) -> None:
        """Print a clean, centred header with key/value rows."""
        width = 60
        with self._lock:
            self._clear_line()
            print(PALETTE.paint("CYAN", "═" * width))
            print(PALETTE.paint("BOLD", " " + title.center(width - 2)))
            print(PALETTE.paint("CYAN", "═" * width))
            for key, value in fields:
                if key == "-":
                    print(PALETTE.paint("GREY", "─" * width))
                elif key:
                    print(f"  {PALETTE.paint('GREY', str(key).ljust(14))}: {value}")
            print(PALETTE.paint("CYAN", "═" * width))
            sys.stdout.flush()
            self._draw_status()

    def section(self, title: str) -> None:
        """Print a bold section divider."""
        width = 60
        with self._lock:
            self._clear_line()
            print(PALETTE.paint("CYAN", "═" * width))
            print(PALETTE.paint("BOLD", " " + str(title).center(width - 2)))
            print(PALETTE.paint("CYAN", "═" * width))
            sys.stdout.flush()
            self._draw_status()

    def stop(self) -> None:
        """Stop the spinner and leave the terminal on a clean new line."""
        with self._lock:
            self._spin_alive = False
            self._clear_line()
            self._status_text = None


# Singleton used across the whole bot.
console = Console()


class ConsoleLogHandler(logging.Handler):
    """Routes logging records to the console as clean, colour-coded lines."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        try:
            if record.levelno >= logging.ERROR:
                console.error(msg)
            elif record.levelno >= logging.WARNING:
                console.warning(msg)
            else:
                console.info(msg)
        except Exception:
            pass
