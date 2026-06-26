# -*- coding: utf-8 -*-
"""Тесты _download_one с фейковым клиентом (без сети).

Проверяем: запись через *.part с переименованием в финал, лог воркера на старте
и финише, повтор после FloodWait, обработку ошибок и пустого результата.
"""

import asyncio
import logging
from types import SimpleNamespace

from telethon.errors import FloodWaitError, RPCError

from tgmedia.downloader import FloodGate, _download_one
from tests.conftest import make_config

# flood_buffer_seconds=0 → FloodWait в тесте не приводит к реальному ожиданию.
CFG = make_config(flood_buffer_seconds=0)


class FakeClient:
    """Подмена TelegramClient.download_media для офлайн-тестов."""

    def __init__(self, *, flood_times=0, error=False, exc=None, returns_none=False,
                 content=b"data", prog_total=0):
        self.flood_times = flood_times
        self.error = error
        self.exc = exc                         # произвольное исключение для имитации сбоя
        self.returns_none = returns_none
        self.content = content
        self.prog_total = prog_total           # если задан — эмулируем шаги прогресса
        self.calls = 0

    async def download_media(self, msg, file, progress_callback=None):
        self.calls += 1
        if self.flood_times > 0:
            self.flood_times -= 1
            raise FloodWaitError(request=None, capture=0)
        if self.exc is not None:
            raise self.exc
        if self.error:
            raise RPCError(request=None, message="boom", code=400)
        if self.returns_none:
            return None
        if progress_callback and self.prog_total:
            for frac in (0.5, 1.0):            # 50% и 100%
                progress_callback(int(self.prog_total * frac), self.prog_total)
        with open(file, "wb") as fh:           # имитируем запись скачанного во *.part
            fh.write(self.content)
        return file


def _msg(id=1, size=None):
    # .file.size известен из метаданных ещё до скачивания (для лога старта).
    return SimpleNamespace(id=id, file=SimpleNamespace(size=size))


def test_success_writes_final_and_removes_part(tmp_path, caplog):
    path = tmp_path / "100_video.mp4"
    client = FakeClient(content=b"hello")
    with caplog.at_level(logging.INFO, logger="downloader"):
        ok = asyncio.run(_download_one(client, _msg(100, size=3 * 1024 * 1024),
                                       path, CFG, FloodGate(), worker=2))
    assert ok is True
    assert path.read_bytes() == b"hello"
    assert not path.with_name(path.name + ".part").exists()   # временный убран
    # лог старта и финиша с номером воркера, хвостом имени, размером и временем
    assert "Worker 2: ↓ начал" in caplog.text
    assert "3.0 МБ" in caplog.text                        # размер из метаданных на старте
    assert "Worker 2: ✓ готов" in caplog.text
    assert "за" in caplog.text and "с" in caplog.text     # длительность в строке финиша
    assert "КБ" in caplog.text                            # фактический размер (5 байт → '0 КБ')


def test_floodwait_then_success(tmp_path):
    path = tmp_path / "5_photo.jpg"
    client = FakeClient(flood_times=2)         # дважды FloodWait, затем успех
    ok = asyncio.run(_download_one(client, _msg(5), path, CFG, FloodGate(), worker=1))
    assert ok is True
    assert client.calls == 3                   # 2 повтора + удачная попытка
    assert path.exists()


def test_floodwait_penalizes_shared_gate(tmp_path):
    # FloodWait, пойманный одним вызовом, отодвигает общий resume_at заслонки.
    path = tmp_path / "9_video.mp4"
    gate = FloodGate()
    cfg = make_config(flood_buffer_seconds=1)  # +1с к штрафу
    client = FakeClient(flood_times=1)

    async def go():
        loop = asyncio.get_running_loop()
        before = loop.time()
        # capture=0, буфер=1 → penalize(1): следующая wait() ждёт ~1с
        await _download_one(client, _msg(9), path, cfg, gate, worker=1)
        # после успешной загрузки resume_at уже в прошлом — проверим, что он был сдвинут
        return gate._resume_at - before

    shifted = asyncio.run(go())
    assert shifted >= 1.0                       # заслонка была отодвинута на буфер


def test_rpc_error_returns_false_and_cleans_part(tmp_path):
    path = tmp_path / "7_video.mp4"
    client = FakeClient(error=True)
    ok = asyncio.run(_download_one(client, _msg(7), path, CFG, FloodGate(), worker=3))
    assert ok is False
    assert not path.exists()
    assert not path.with_name(path.name + ".part").exists()


def test_generic_value_error_is_handled(tmp_path):
    # Telethon бросает ValueError('Request was unsuccessful N time(s)') — не должен
    # ронять загрузку, а помечать файл проваленным.
    path = tmp_path / "13_video.mp4"
    client = FakeClient(exc=ValueError("Request was unsuccessful 6 time(s)"))
    ok = asyncio.run(_download_one(client, _msg(13), path, CFG, FloodGate(), worker=1))
    assert ok is False
    assert not path.exists()
    assert not path.with_name(path.name + ".part").exists()


def test_cancelled_error_propagates(tmp_path):
    # CancelledError (Ctrl+C) — BaseException: НЕ глотается, пробрасывается наружу.
    import pytest
    path = tmp_path / "14_video.mp4"
    client = FakeClient(exc=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_download_one(client, _msg(14), path, CFG, FloodGate(), worker=1))


def test_returns_none_is_failure(tmp_path):
    path = tmp_path / "8_video.mp4"
    client = FakeClient(returns_none=True)
    ok = asyncio.run(_download_one(client, _msg(8), path, CFG, FloodGate(), worker=1))
    assert ok is False
    assert not path.exists()


def test_large_file_logs_progress(tmp_path, caplog):
    # Крупный файл (>50 МБ) → лог прогресса шагами (50%, 100%).
    total = 200 * 1024 * 1024
    path = tmp_path / "11_video.mp4"
    client = FakeClient(prog_total=total)
    with caplog.at_level(logging.INFO, logger="downloader"):
        ok = asyncio.run(_download_one(client, _msg(11, size=total),
                                       path, CFG, FloodGate(), worker=1))
    assert ok is True
    assert "50%" in caplog.text
    assert "100%" in caplog.text


def test_small_file_no_progress_spam(tmp_path, caplog):
    # Мелкий файл (<50 МБ) → без строк прогресса.
    total = 1 * 1024 * 1024
    path = tmp_path / "12_video.mp4"
    client = FakeClient(prog_total=total)
    with caplog.at_level(logging.INFO, logger="downloader"):
        asyncio.run(_download_one(client, _msg(12, size=total),
                                  path, CFG, FloodGate(), worker=1))
    assert "%" not in caplog.text
