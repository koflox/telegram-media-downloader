# -*- coding: utf-8 -*-
"""Разбор и валидация config.yaml в типизированный объект Config."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml


@dataclass
class Config:
    """Разобранный и провалидированный config.yaml."""
    # telegram
    api_id: int
    api_hash: str
    session_name: str
    # download
    output_dir: str
    photos: bool
    videos: bool
    video_notes: bool
    file_photos: bool
    file_videos: bool
    max_file_mb: int
    since_date: object          # datetime (tz-aware) или None
    # scope
    include_groups: bool
    include_channels: bool
    exclude_chats: list
    # throttle
    download_workers: int
    pause_between_chats: float
    pause_between_files: float
    flood_buffer_seconds: int
    # output
    log_path: str
    progress_path: str


class ConfigError(Exception):
    """Проблема с конфигом — выводим понятное сообщение и выходим."""


def _nonneg_float(value, default):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _parse_since(since_raw):
    """Принимаем 'ГГГГ-ММ-ДД' или 'ГГГГ-ММ-ДД ЧЧ:ММ'; трактуем как локальное время."""
    if since_raw in (None, "", False):
        return None
    s = str(since_raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).astimezone()
        except ValueError:
            continue
    raise ConfigError(
        f"Не понял download.since_date='{since_raw}'. "
        "Формат: 'ГГГГ-ММ-ДД' или 'ГГГГ-ММ-ДД ЧЧ:ММ'."
    )


def load_config(path: str) -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Не найден конфиг: {path}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Не удалось разобрать YAML ({path}): {e}")

    tg = data.get("telegram", {}) or {}
    dl = data.get("download", {}) or {}
    scope = data.get("scope", {}) or {}
    throttle = data.get("throttle", {}) or {}
    output = data.get("output", {}) or {}

    try:
        api_id = int(tg.get("api_id", 0))
    except (TypeError, ValueError):
        api_id = 0
    api_hash = str(tg.get("api_hash", "") or "")
    if not api_id or not api_hash:
        raise ConfigError(
            "Заполни telegram.api_id и telegram.api_hash в config.yaml "
            "(получить на https://my.telegram.org → API development tools)."
        )

    try:
        max_file_mb = max(0, int(dl.get("max_file_mb", 0)))
    except (TypeError, ValueError):
        max_file_mb = 0

    # Параллельные загрузки: зажимаем в [1, 32], чтобы не словить FloodWait/бан.
    try:
        _workers = int(throttle.get("download_workers", 4))
    except (TypeError, ValueError):
        _workers = 4
    _workers = max(1, min(32, _workers))

    return Config(
        api_id=api_id,
        api_hash=api_hash,
        session_name=str(tg.get("session_name", "media_downloader")),
        output_dir=str(dl.get("output_dir", "./downloads")),
        photos=bool(dl.get("photos", True)),
        videos=bool(dl.get("videos", True)),
        video_notes=bool(dl.get("video_notes", True)),
        file_photos=bool(dl.get("file_photos", True)),
        file_videos=bool(dl.get("file_videos", True)),
        max_file_mb=max_file_mb,
        since_date=_parse_since(dl.get("since_date")),
        include_groups=bool(scope.get("include_groups", True)),
        include_channels=bool(scope.get("include_channels", False)),
        exclude_chats=list(scope.get("exclude_chats") or []),
        download_workers=_workers,
        pause_between_chats=_nonneg_float(throttle.get("pause_between_chats", 1.0), 1.0),
        pause_between_files=_nonneg_float(throttle.get("pause_between_files", 0.0), 0.0),
        flood_buffer_seconds=max(0, int(throttle.get("flood_buffer_seconds", 5) or 0)),
        log_path=str(output.get("log_path", "./downloader.log")),
        progress_path=str(output.get("progress_path", "./progress.json")),
    )
