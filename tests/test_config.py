# -*- coding: utf-8 -*-
"""Тесты загрузки и валидации config.yaml."""

import pytest

from tgmedia.config import ConfigError, load_config


def write_cfg(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


GOOD = """
telegram:
  api_id: 123
  api_hash: "abc"
  session_name: "sess"
download:
  output_dir: "./out"
  photos: true
  videos: false
  video_notes: true
  file_photos: false
  file_videos: true
  max_file_mb: 50
scope:
  include_groups: false
  include_channels: true
  exclude_chats: [111, "@user"]
throttle:
  download_workers: 8
  pause_between_chats: 2.5
  pause_between_files: 0.3
"""


def test_load_good_config(tmp_path):
    cfg = load_config(write_cfg(tmp_path, GOOD))
    assert cfg.api_id == 123
    assert cfg.api_hash == "abc"
    assert cfg.session_name == "sess"
    assert cfg.output_dir == "./out"
    assert cfg.photos is True and cfg.videos is False
    assert cfg.video_notes is True
    assert cfg.file_photos is False and cfg.file_videos is True
    assert cfg.max_file_mb == 50
    assert cfg.include_groups is False and cfg.include_channels is True
    assert cfg.exclude_chats == [111, "@user"]
    assert cfg.download_workers == 8
    assert cfg.pause_between_chats == 2.5
    assert cfg.pause_between_files == 0.3


def test_defaults(tmp_path):
    cfg = load_config(write_cfg(tmp_path, 'telegram: {api_id: 1, api_hash: "h"}'))
    # типы медиа по умолчанию включены
    assert cfg.photos and cfg.videos and cfg.video_notes
    assert cfg.file_photos and cfg.file_videos
    assert cfg.output_dir == "./downloads"
    assert cfg.include_groups is True
    assert cfg.include_channels is False     # каналы по умолчанию выключены
    assert cfg.exclude_chats == []
    assert cfg.max_file_mb == 0
    assert cfg.since_date is None
    assert cfg.flood_buffer_seconds == 5
    assert cfg.download_workers == 4         # дефолт параллелизма


def test_download_workers_clamped(tmp_path):
    low = 'telegram: {api_id: 1, api_hash: "h"}\nthrottle: {download_workers: 0}\n'
    assert load_config(write_cfg(tmp_path, low)).download_workers == 1
    high = 'telegram: {api_id: 1, api_hash: "h"}\nthrottle: {download_workers: 999}\n'
    assert load_config(write_cfg(tmp_path, high)).download_workers == 32
    bad = 'telegram: {api_id: 1, api_hash: "h"}\nthrottle: {download_workers: "x"}\n'
    assert load_config(write_cfg(tmp_path, bad)).download_workers == 4


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "нет.yaml"))


def test_missing_credentials_raise(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write_cfg(tmp_path, "download: {photos: true}\n"))


def test_invalid_yaml(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write_cfg(tmp_path, "telegram: [unclosed"))


def test_max_file_mb_negative_clamped(tmp_path):
    text = 'telegram: {api_id: 1, api_hash: "h"}\ndownload: {max_file_mb: -5}\n'
    cfg = load_config(write_cfg(tmp_path, text))
    assert cfg.max_file_mb == 0


def test_max_file_mb_garbage_falls_back(tmp_path):
    text = 'telegram: {api_id: 1, api_hash: "h"}\ndownload: {max_file_mb: "abc"}\n'
    cfg = load_config(write_cfg(tmp_path, text))
    assert cfg.max_file_mb == 0


def test_negative_pause_clamped(tmp_path):
    text = ('telegram: {api_id: 1, api_hash: "h"}\n'
            'throttle: {pause_between_chats: -3, pause_between_files: -1}\n')
    cfg = load_config(write_cfg(tmp_path, text))
    assert cfg.pause_between_chats == 0.0
    assert cfg.pause_between_files == 0.0


def test_since_date_parsed(tmp_path):
    text = 'telegram: {api_id: 1, api_hash: "h"}\ndownload: {since_date: "2026-06-01"}\n'
    cfg = load_config(write_cfg(tmp_path, text))
    assert cfg.since_date is not None
    assert (cfg.since_date.year, cfg.since_date.month, cfg.since_date.day) == (2026, 6, 1)
    assert cfg.since_date.tzinfo is not None     # tz-aware


def test_since_date_with_time(tmp_path):
    text = 'telegram: {api_id: 1, api_hash: "h"}\ndownload: {since_date: "2026-06-01 14:30"}\n'
    cfg = load_config(write_cfg(tmp_path, text))
    assert cfg.since_date.hour == 14 and cfg.since_date.minute == 30


def test_since_date_empty_is_none(tmp_path):
    text = 'telegram: {api_id: 1, api_hash: "h"}\ndownload: {since_date: ""}\n'
    cfg = load_config(write_cfg(tmp_path, text))
    assert cfg.since_date is None


def test_since_date_invalid_raises(tmp_path):
    text = 'telegram: {api_id: 1, api_hash: "h"}\ndownload: {since_date: "01.06.2026"}\n'
    with pytest.raises(ConfigError):
        load_config(write_cfg(tmp_path, text))
