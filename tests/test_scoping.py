# -*- coding: utf-8 -*-
"""Тесты классификации чатов и фильтра по типам."""

from tgmedia.scoping import chat_kind, kind_allowed
from tests.conftest import (
    fake_basic_group,
    fake_broadcast,
    fake_megagroup,
    fake_user,
)


def test_chat_kind_private():
    assert chat_kind(fake_user()) == "private"


def test_chat_kind_basic_group():
    assert chat_kind(fake_basic_group()) == "group"


def test_chat_kind_megagroup():
    assert chat_kind(fake_megagroup()) == "group"


def test_chat_kind_broadcast():
    assert chat_kind(fake_broadcast()) == "channel"


def test_kind_allowed_private_always():
    assert kind_allowed("private", include_groups=False, include_channels=False) is True


def test_kind_allowed_group_flag():
    assert kind_allowed("group", include_groups=True, include_channels=False) is True
    assert kind_allowed("group", include_groups=False, include_channels=False) is False


def test_kind_allowed_channel_flag():
    assert kind_allowed("channel", include_groups=False, include_channels=True) is True
    assert kind_allowed("channel", include_groups=False, include_channels=False) is False
