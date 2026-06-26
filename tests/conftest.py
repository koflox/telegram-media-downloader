# -*- coding: utf-8 -*-
"""Общие фабрики для тестов: Config и фейковые объекты сообщения/чата.

Чистая логика (config, scoping, progress, классификация медиа и построение
путей) тестируется без сети. telethon импортируется (он установлен), но никаких
сетевых вызовов в тестах нет.
"""

from types import SimpleNamespace

from tgmedia.config import Config


def make_config(**over) -> Config:
    """Config с разумными дефолтами; переопредели нужные поля через kwargs."""
    defaults = dict(
        api_id=1, api_hash="hash", session_name="test",
        output_dir="./downloads",
        photos=True, videos=True, video_notes=True,
        file_photos=True, file_videos=True,
        max_file_mb=0, since_date=None,
        include_groups=True, include_channels=False, exclude_chats=[],
        download_workers=4,
        pause_between_chats=0.0, pause_between_files=0.0, flood_buffer_seconds=5,
        log_path="./downloader.log", progress_path="./progress.json",
    )
    defaults.update(over)
    return Config(**defaults)


def fake_msg(id=1, *, sticker=None, gif=None, photo=None, video_note=None,
             video=None, document=None, file=None):
    """Утиная подмена telethon-сообщения: только нужные media_category/пути атрибуты."""
    return SimpleNamespace(
        id=id, sticker=sticker, gif=gif, photo=photo, video_note=video_note,
        video=video, document=document, file=file,
    )


def fake_file(ext="", size=None):
    return SimpleNamespace(ext=ext, size=size)


def fake_doc(mime_type=""):
    return SimpleNamespace(mime_type=mime_type)


# --- Подмены telethon-сущностей чата для scoping ---

def fake_user(id=10):
    # У User нет ни title, ни broadcast/megagroup.
    return SimpleNamespace(id=id)


def fake_basic_group(id=20):
    # Базовая группа (Chat): есть title, нет broadcast/megagroup.
    return SimpleNamespace(id=id, title="Группа")


def fake_megagroup(id=30):
    return SimpleNamespace(id=id, title="Супергруппа", broadcast=False, megagroup=True)


def fake_broadcast(id=40):
    return SimpleNamespace(id=id, title="Канал", broadcast=True, megagroup=False)
