# -*- coding: utf-8 -*-
"""Классификация чатов по типу и фильтр по флагам scope.

Без импорта telethon (duck-typing по атрибутам сущности).

Типы:
  private — личка (User);
  group   — обычная группа (Chat) или супергруппа (Channel.megagroup);
  channel — канал-вещание (Channel.broadcast).
"""


def chat_kind(entity) -> str:
    # Channel имеет булевы атрибуты broadcast/megagroup; Chat и User — нет.
    broadcast = getattr(entity, "broadcast", None)
    megagroup = getattr(entity, "megagroup", None)
    if broadcast is not None or megagroup is not None:
        if megagroup:
            return "group"          # супергруппа
        return "channel"            # канал-вещание
    # У базовой группы (Chat) есть title, у лички (User) — нет.
    if getattr(entity, "title", None) is not None:
        return "group"
    return "private"


def kind_allowed(kind: str, include_groups: bool, include_channels: bool) -> bool:
    """Пропускать ли чат данного типа в обработку. Личку — всегда."""
    if kind == "group":
        return include_groups
    if kind == "channel":
        return include_channels
    return True
