# -*- coding: utf-8 -*-
"""Сборка всего вместе: разбор аргументов, основной сценарий, точка входа."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from telethon import TelegramClient

from .config import ConfigError, load_config
from .downloader import FloodGate, download_chat, resolve_scope
from .logging_setup import chat_color, setup_logging
from .progress import chat_state, load_progress, save_progress

log = logging.getLogger("downloader")


async def run(cfg, args) -> None:
    output_root = Path(cfg.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    progress_path = Path(cfg.progress_path)

    if args.reset_progress and progress_path.exists():
        progress_path.unlink()
        log.info("Прогресс сброшен (--reset-progress).")

    progress = load_progress(progress_path)

    def flush():
        save_progress(progress, progress_path)

    if cfg.since_date is not None:
        log.info(f"Граница по дате: сообщения старше {cfg.since_date:%Y-%m-%d %H:%M} не выгружаются.")
    if args.rescan:
        log.info("Режим --rescan: проход с самых новых сообщений по всем чатам "
                 "(уже скачанные файлы пропускаются).")

    log.info("Подключаюсь к Telegram…")
    client = TelegramClient(cfg.session_name, cfg.api_id, cfg.api_hash)
    await client.start()
    log.info("Подключено.")

    totals = {"downloaded": 0, "skipped": 0, "failed": 0}
    gate = FloodGate()      # общая на весь запуск: FloodWait тормозит всех воркеров
    scope = []
    try:
        scope = await resolve_scope(client, cfg)
        log.info(f"Чатов в обработке: {len(scope)}")

        for entity in scope:
            cid = entity.id
            state = chat_state(progress, cid)
            title = state.get("title") or str(cid)

            # Уже полностью выгруженный чат пропускаем (если не --rescan).
            if state.get("done") and not args.rescan:
                log.info(f"Пропуск (уже выгружен ранее): {chat_color(title)} [{cid}]")
                continue

            log.info(f"--- Чат: {chat_color(title)} [{cid}] ---")
            before = dict(state)
            try:
                await download_chat(client, entity, cfg, state, output_root,
                                    rescan=args.rescan, on_progress=flush, gate=gate)
            except Exception as e:
                log.exception(f"Ошибка при обработке чата {title} [{cid}]: {e}")
                flush()
                continue

            totals["downloaded"] += state["downloaded"] - before.get("downloaded", 0)
            totals["skipped"] += state["skipped"] - before.get("skipped", 0)
            totals["failed"] += state["failed"] - before.get("failed", 0)
            flush()
            if cfg.pause_between_chats > 0:
                await asyncio.sleep(cfg.pause_between_chats)
    finally:
        flush()
        await client.disconnect()

    log.info(f"ИТОГО за запуск: скачано {totals['downloaded']}, "
             f"пропущено {totals['skipped']}, ошибок {totals['failed']}.")
    log.info(f"Файлы: {output_root.resolve()}")

    # Финальный статус: все ли чаты из scope выгружены полностью.
    total_chats = len(scope)
    done_chats = sum(1 for e in scope
                     if progress["chats"].get(str(e.id), {}).get("done"))
    remaining = total_chats - done_chats
    if total_chats == 0:
        log.info("Нет чатов в обработке.")
    elif remaining == 0:
        log.info(f"✓ ВСЁ ГОТОВО: все чаты выгружены ({total_chats}).")
    else:
        log.info(f"Осталось незавершённых чатов: {remaining} из {total_chats} — "
                 f"повторный запуск продолжит с места остановки.")


def parse_args():
    p = argparse.ArgumentParser(
        description="Выгрузка медиа (фото, видео, файлы-фото/видео, кружочки) "
                    "из всех чатов Telegram под своим аккаунтом (Telethon).",
    )
    p.add_argument("--config", default="config.yaml", help="путь к config.yaml")
    p.add_argument("--reset-progress", action="store_true",
                   help="сбросить сохранённый прогресс и начать заново")
    p.add_argument("--rescan", action="store_true",
                   help="пройти все чаты с самых новых сообщений, чтобы подхватить "
                        "новые (уже скачанные файлы не качаются повторно)")
    return p.parse_args()


def _force_utf8_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _force_utf8_console()
    args = parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"[config] {e}", file=sys.stderr)
        sys.exit(2)

    setup_logging(cfg.log_path)
    try:
        asyncio.run(run(cfg, args))
    except KeyboardInterrupt:
        log.warning("Прервано пользователем (Ctrl+C). Прогресс сохранён — "
                    "повторный запуск продолжит с места остановки.")
        sys.exit(130)
