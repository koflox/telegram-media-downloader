# -*- coding: utf-8 -*-
"""Тесты чистых функций выгрузки: классификация медиа, размер, имена/пути.

Сетевые функции (resolve_scope, download_chat, _download_one) здесь не трогаем —
их проверяем вручную на реальном аккаунте.
"""

from pathlib import Path

from tgmedia.downloader import (
    _fmt_duration,
    _fmt_size,
    _target_path,
    _too_big,
    media_category,
    safe_name,
)
from tests.conftest import fake_doc, fake_file, fake_msg, make_config


# ---------- _fmt_duration ----------

def test_fmt_duration_seconds():
    assert _fmt_duration(3.42) == "3.4с"
    assert _fmt_duration(0) == "0.0с"
    assert _fmt_duration(59.9) == "59.9с"


def test_fmt_duration_minutes():
    assert _fmt_duration(60) == "1м 00с"
    assert _fmt_duration(125) == "2м 05с"
    assert _fmt_duration(3661) == "61м 01с"


# ---------- _fmt_size ----------

def test_fmt_size_mb():
    assert _fmt_size(5 * 1024 * 1024) == "5.0 МБ"
    assert _fmt_size(int(1.25 * 1024 * 1024)) == "1.2 МБ"


def test_fmt_size_sub_mb_in_kb():
    assert _fmt_size(200 * 1024) == "200 КБ"
    assert _fmt_size(5) == "0 КБ"


# ---------- safe_name ----------

def test_safe_name_replaces_bad_chars():
    assert safe_name('a/b\\c:d*e?f"g<h>i|j', "x") == "a_b_c_d_e_f_g_h_i_j"


def test_safe_name_empty_uses_fallback():
    assert safe_name("", "123") == "123"
    assert safe_name("   ", "123") == "123"


def test_safe_name_strips_trailing_dots_and_spaces():
    # Windows не любит имена, оканчивающиеся точкой/пробелом.
    assert safe_name("  имя.  ", "x") == "имя"


def test_safe_name_truncated():
    assert len(safe_name("я" * 200, "x")) <= 80


# ---------- media_category ----------

def test_photo():
    assert media_category(fake_msg(photo=True), make_config()) == "photo"


def test_video_note_round():
    assert media_category(fake_msg(video_note=True), make_config()) == "round"


def test_video():
    assert media_category(fake_msg(video=True), make_config()) == "video"


def test_document_image_is_photo_file():
    msg = fake_msg(document=fake_doc("image/png"))
    assert media_category(msg, make_config()) == "photo_file"


def test_document_video_is_video_file():
    msg = fake_msg(document=fake_doc("video/mp4"))
    assert media_category(msg, make_config()) == "video_file"


def test_sticker_skipped():
    assert media_category(fake_msg(sticker=True, document=fake_doc("image/webp")), make_config()) is None


def test_gif_skipped():
    assert media_category(fake_msg(gif=True, document=fake_doc("video/mp4")), make_config()) is None


def test_other_document_skipped():
    # pdf и прочие документы — не фото/видео.
    assert media_category(fake_msg(document=fake_doc("application/pdf")), make_config()) is None


def test_no_media_skipped():
    assert media_category(fake_msg(), make_config()) is None


def test_flags_disable_categories():
    cfg = make_config(photos=False, videos=False, video_notes=False,
                      file_photos=False, file_videos=False)
    assert media_category(fake_msg(photo=True), cfg) is None
    assert media_category(fake_msg(video=True), cfg) is None
    assert media_category(fake_msg(video_note=True), cfg) is None
    assert media_category(fake_msg(document=fake_doc("image/png")), cfg) is None
    assert media_category(fake_msg(document=fake_doc("video/mp4")), cfg) is None


def test_mime_case_insensitive():
    assert media_category(fake_msg(document=fake_doc("IMAGE/JPEG")), make_config()) == "photo_file"


# ---------- _too_big ----------

def test_too_big_no_limit():
    msg = fake_msg(file=fake_file(size=999 * 1024 * 1024))
    assert _too_big(msg, make_config(max_file_mb=0)) is False


def test_too_big_under_limit():
    msg = fake_msg(file=fake_file(size=5 * 1024 * 1024))
    assert _too_big(msg, make_config(max_file_mb=10)) is False


def test_too_big_over_limit():
    msg = fake_msg(file=fake_file(size=20 * 1024 * 1024))
    assert _too_big(msg, make_config(max_file_mb=10)) is True


def test_too_big_unknown_size():
    msg = fake_msg(file=fake_file(size=None))
    assert _too_big(msg, make_config(max_file_mb=10)) is False


# ---------- _target_path ----------

def test_target_path_uses_file_ext():
    msg = fake_msg(id=77, file=fake_file(ext=".mp4"))
    p = _target_path(Path("/d"), msg, "video")
    assert p.name == "77_video.mp4"


def test_target_path_photo_fallback_ext():
    msg = fake_msg(id=5, file=None)
    p = _target_path(Path("/d"), msg, "photo")
    assert p.name == "5_photo.jpg"


def test_target_path_generic_fallback_ext():
    msg = fake_msg(id=8, file=fake_file(ext=""))
    p = _target_path(Path("/d"), msg, "video")
    assert p.name == "8_video.bin"


def test_target_path_deterministic():
    # Один и тот же msg → один и тот же путь (основа дедупликации).
    msg = fake_msg(id=99, file=fake_file(ext=".jpg"))
    a = _target_path(Path("/d"), msg, "photo_file")
    b = _target_path(Path("/d"), msg, "photo_file")
    assert a == b == Path("/d/99_photo_file.jpg")
