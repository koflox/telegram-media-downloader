# -*- coding: utf-8 -*-
"""Резюмируемость между запусками.

progress.json хранит по каждому чату:
  oldest_id  — id самого СТАРОГО уже обработанного сообщения (iter идёт новые→старые;
               на следующем запуске продолжаем с offset_id=oldest_id, т.е. не
               перетряхиваем заново уже пройденную часть истории);
  done       — чат пройден до конца (старых сообщений больше нет);
  downloaded / skipped / failed — счётчики для статистики.

Это «грубый» уровень резюмируемости. Точный — проверка наличия файла на диске
(см. downloader.py): даже если прогресс потерян, уже скачанные файлы не качаются
повторно.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger("downloader")

PROGRESS_VERSION = 1


def load_progress(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "chats" in data:
                return data
        except Exception:
            log.warning("Файл прогресса повреждён — начинаю с нуля.")
    return {"version": PROGRESS_VERSION, "chats": {}}


def save_progress(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)   # атомарная замена — не оставляем битый progress.json при сбое


def chat_state(progress: dict, chat_id) -> dict:
    """Вернуть (создав при необходимости) запись прогресса по чату."""
    chats = progress.setdefault("chats", {})
    key = str(chat_id)
    if key not in chats:
        chats[key] = {
            "title": "",
            "oldest_id": 0,     # 0 = ещё не начинали / начинаем с самых новых
            "done": False,
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
        }
    return chats[key]
