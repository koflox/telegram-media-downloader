# -*- coding: utf-8 -*-
"""Тесты общей заслонки FloodWait (без сети, на коротких интервалах).

Проверяем чистую логику синхронизации: penalize отодвигает общий момент
возобновления, wait() блокирует до него, берётся МАКСИМУМ из нескольких штрафов,
а без штрафа wait() возвращается сразу.
"""

import asyncio

from tgmedia.downloader import FloodGate


def test_no_penalty_returns_immediately():
    async def go():
        loop = asyncio.get_running_loop()
        gate = FloodGate()
        t0 = loop.time()
        await gate.wait()
        return loop.time() - t0
    assert asyncio.run(go()) < 0.02


def test_penalize_blocks_wait():
    async def go():
        loop = asyncio.get_running_loop()
        gate = FloodGate()
        gate.penalize(0.05)
        t0 = loop.time()
        await gate.wait()
        return loop.time() - t0
    assert asyncio.run(go()) >= 0.04


def test_penalize_takes_max():
    async def go():
        loop = asyncio.get_running_loop()
        gate = FloodGate()
        gate.penalize(0.02)
        gate.penalize(0.10)      # больший штраф побеждает
        gate.penalize(0.03)
        t0 = loop.time()
        await gate.wait()
        return loop.time() - t0
    assert asyncio.run(go()) >= 0.09


def test_all_workers_wait_together():
    # Один воркер штрафует — несколько ждущих просыпаются примерно одновременно,
    # каждый ждёт ОДИН общий интервал, а не суммарно по очереди.
    async def go():
        loop = asyncio.get_running_loop()
        gate = FloodGate()
        gate.penalize(0.06)
        t0 = loop.time()
        await asyncio.gather(gate.wait(), gate.wait(), gate.wait())
        return loop.time() - t0
    elapsed = asyncio.run(go())
    assert 0.05 <= elapsed < 0.15      # ~один интервал, не 3×
