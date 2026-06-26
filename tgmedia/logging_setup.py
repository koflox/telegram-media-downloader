# -*- coding: utf-8 -*-
"""Настройка логирования. Общий логгер на весь проект — logging.getLogger('downloader').

Название чата подсвечивается синим в консоли; в лог-файл ANSI-коды не пишутся.
Цвет включается только если вывод идёт в терминал.
"""

import logging
import os
import re
import sys
from pathlib import Path

log = logging.getLogger("downloader")

_BLUE = "\033[94m"
_RESET = "\033[0m"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_color_enabled = False


def chat_color(text) -> str:
    """Обернуть текст (название чата) в синий, если цвет включён."""
    return f"{_BLUE}{text}{_RESET}" if _color_enabled else str(text)


class _StripAnsiFormatter(logging.Formatter):
    """Форматтер для файла: убирает ANSI-коды."""
    def format(self, record):
        return _ANSI_RE.sub("", super().format(record))


def _supports_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _enable_windows_ansi() -> None:
    """В старых Windows-консолях ANSI выключен — включаем VT-обработку."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def setup_logging(log_path: str) -> None:
    global _color_enabled

    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    log.handlers.clear()

    datefmt = "%Y-%m-%d %H:%M:%S"
    line = "%(asctime)s %(levelname)-7s %(message)s"

    sh = logging.StreamHandler()
    _color_enabled = _supports_color(sh.stream)
    if _color_enabled:
        _enable_windows_ansi()
    sh.setFormatter(logging.Formatter(line, datefmt))

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(_StripAnsiFormatter(line, datefmt))

    log.addHandler(fh)
    log.addHandler(sh)
