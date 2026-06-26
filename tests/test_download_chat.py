# -*- coding: utf-8 -*-
"""Интеграционные тесты пула воркеров download_chat с фейковым клиентом (без сети).

Проверяем: все медиа скачаны, не-медиа/уже-скачанное пропущены, дедуп по диску,
непрерывный водяной знак доходит до самого старого id, done=True, и резюм по
offset_id перечитывает только незакоммиченную часть.
"""

import asyncio
from types import SimpleNamespace

from tgmedia.downloader import FloodGate, download_chat
from tgmedia.progress import chat_state
from tests.conftest import fake_file, fake_msg, make_config


class FakeChatClient:
    """Подмена TelegramClient: iter_messages + download_media, без сети."""

    def __init__(self, messages, content=b"xxxxx"):
        self.messages = messages              # по убыванию id (новые→старые)
        self.content = content
        self.downloaded_ids = []
        self.iter_offsets = []

    def iter_messages(self, entity, offset_id=0):
        self.iter_offsets.append(offset_id)
        msgs = self.messages

        async def gen():
            for m in msgs:
                if offset_id and m.id >= offset_id:   # offset_id=N → только id < N
                    continue
                yield m
        return gen()

    async def download_media(self, msg, file, progress_callback=None):
        self.downloaded_ids.append(msg.id)
        with open(file, "wb") as fh:
            fh.write(self.content)
        return file


def _media(id):
    return fake_msg(id=id, video=True, file=fake_file(ext=".mp4", size=1000))


def _text(id):
    return fake_msg(id=id)                     # все media-атрибуты None → не медиа


def _run(client, tmp_path, state, **over):
    cfg = make_config(**over)
    entity = SimpleNamespace(id=777)
    asyncio.run(download_chat(client, entity, cfg, state, tmp_path,
                              rescan=over.pop("rescan", False),
                              on_progress=lambda: None, gate=FloodGate()))


def test_downloads_all_media_and_counts(tmp_path):
    # id по убыванию: 10..1, чётные — медиа, нечётные — текст.
    messages = [(_media(i) if i % 2 == 0 else _text(i)) for i in range(10, 0, -1)]
    client = FakeChatClient(messages)
    progress = {"version": 1, "chats": {}}
    state = chat_state(progress, 777)

    _run(client, tmp_path, state, download_workers=4)

    assert state["downloaded"] == 5           # 10,8,6,4,2
    assert state["failed"] == 0
    assert sorted(client.downloaded_ids) == [2, 4, 6, 8, 10]
    assert state["done"] is True
    assert state["oldest_id"] == 1            # префикс дошёл до самого старого
    # файлы реально на диске
    chat_dir = next(tmp_path.iterdir())
    assert len(list(chat_dir.glob("*.mp4"))) == 5
    assert not list(chat_dir.glob("*.part"))  # временные подчищены


def test_skips_already_downloaded(tmp_path):
    messages = [_media(3), _media(2), _media(1)]
    client = FakeChatClient(messages)
    progress = {"version": 1, "chats": {}}
    state = chat_state(progress, 777)

    # Предварительно создаём файл для msg 2 — должен пропуститься (дедуп по диску).
    chat_dir = tmp_path / "777_777"
    chat_dir.mkdir(parents=True)
    (chat_dir / "2_video.mp4").write_bytes(b"already")

    _run(client, tmp_path, state, download_workers=4)

    assert 2 not in client.downloaded_ids     # повторно не качали
    assert sorted(client.downloaded_ids) == [1, 3]
    assert state["downloaded"] == 2
    assert state["skipped"] == 1
    assert state["oldest_id"] == 1


def test_watermark_is_oldest_with_many_workers(tmp_path):
    # Много сообщений и воркеров: водяной знак обязан дойти до минимального id.
    messages = [_media(i) for i in range(50, 0, -1)]
    client = FakeChatClient(messages)
    progress = {"version": 1, "chats": {}}
    state = chat_state(progress, 777)

    _run(client, tmp_path, state, download_workers=8)

    assert state["downloaded"] == 50
    assert state["oldest_id"] == 1
    assert state["done"] is True


def test_resume_uses_offset_id(tmp_path):
    messages = [_media(i) for i in range(10, 0, -1)]
    client = FakeChatClient(messages)
    progress = {"version": 1, "chats": {}}
    state = chat_state(progress, 777)
    state["oldest_id"] = 5                     # как будто докачали до id 5

    _run(client, tmp_path, state, download_workers=4)

    assert client.iter_offsets == [5]          # iter стартовал с offset_id=5
    assert sorted(client.downloaded_ids) == [1, 2, 3, 4]   # только id < 5
    assert state["oldest_id"] == 1
