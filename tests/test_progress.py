# -*- coding: utf-8 -*-
"""Тесты резюмируемости: загрузка/сохранение/доступ к прогрессу."""

import json

from tgmedia.progress import chat_state, load_progress, save_progress


def test_load_missing_returns_fresh(tmp_path):
    p = tmp_path / "progress.json"
    data = load_progress(p)
    assert data == {"version": 1, "chats": {}}


def test_load_corrupted_returns_fresh(tmp_path):
    p = tmp_path / "progress.json"
    p.write_text("{ not json", encoding="utf-8")
    assert load_progress(p) == {"version": 1, "chats": {}}


def test_load_without_chats_key_returns_fresh(tmp_path):
    p = tmp_path / "progress.json"
    p.write_text(json.dumps({"version": 1}), encoding="utf-8")
    assert load_progress(p) == {"version": 1, "chats": {}}


def test_chat_state_creates_default():
    progress = {"version": 1, "chats": {}}
    st = chat_state(progress, 555)
    assert st["oldest_id"] == 0
    assert st["done"] is False
    assert st["downloaded"] == 0 and st["skipped"] == 0 and st["failed"] == 0
    # запись попала в общий прогресс под строковым ключом
    assert "555" in progress["chats"]


def test_chat_state_idempotent_returns_same_object():
    progress = {"version": 1, "chats": {}}
    st1 = chat_state(progress, 7)
    st1["downloaded"] = 9
    st2 = chat_state(progress, 7)
    assert st2 is st1
    assert st2["downloaded"] == 9      # не перезатёрся дефолтом


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "sub" / "progress.json"     # родительская папка создаётся
    progress = {"version": 1, "chats": {}}
    st = chat_state(progress, 42)
    st["oldest_id"] = 1000
    st["done"] = True
    st["title"] = "Чат"
    save_progress(progress, p)

    reloaded = load_progress(p)
    assert reloaded["chats"]["42"]["oldest_id"] == 1000
    assert reloaded["chats"]["42"]["done"] is True
    assert reloaded["chats"]["42"]["title"] == "Чат"


def test_save_is_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "progress.json"
    save_progress({"version": 1, "chats": {}}, p)
    # временный файл подчищается после атомарной замены
    assert not (tmp_path / "progress.json.tmp").exists()
    assert p.exists()
