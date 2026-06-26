# -*- coding: utf-8 -*-
"""Работа с Telegram через Telethon: разрешение scope и выгрузка медиа.

Этот модуль импортирует telethon — сетевую часть проверяем вручную на реальном
аккаунте (юнит-тестами не покрывается).
"""

import asyncio
import logging
import re
import time
from datetime import timezone
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.types import MessageService

from .config import Config
from .scoping import chat_kind, kind_allowed

log = logging.getLogger("downloader")

LOG_EVERY = 200             # как часто логировать прогресс и сохранять водяной знак
LARGE_FILE_BYTES = 50 * 1024 * 1024   # порог «крупного» файла для лога прогресса

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class FloodGate:
    """Общая на всех воркеров «заслонка» по FloodWait.

    FloodWait в Telegram — общий на аккаунт, а не на отдельный запрос. Поэтому
    когда один воркер словил FloodWait, остальным нет смысла долбить сервер (это
    только продлевает наказание) — все ждут до общего момента resume_at.
    """

    def __init__(self):
        self._resume_at = 0.0       # отметка loop.time(), до которой ждём всем

    async def wait(self) -> None:
        """Подождать, пока действует общий FloodWait (если действует)."""
        loop = asyncio.get_running_loop()
        while True:
            delay = self._resume_at - loop.time()
            if delay <= 0:
                return
            await asyncio.sleep(delay)

    def penalize(self, seconds: float) -> None:
        """Зарегистрировать FloodWait: отодвинуть общий момент возобновления."""
        loop = asyncio.get_running_loop()
        self._resume_at = max(self._resume_at, loop.time() + seconds)


def safe_name(text: str, fallback: str) -> str:
    """Превратить название чата в безопасное имя папки (Windows/Unix)."""
    name = _BAD_CHARS.sub("_", str(text or "")).strip(" .")
    name = name[:80].strip(" .")
    return name or fallback


def media_category(msg, cfg: Config):
    """Вернуть категорию медиа сообщения с учётом фильтров конфига, либо None.

    Категории: photo, video, round (кружок), photo_file, video_file.
    Стикеры/гифки/голосовые/аудио и сообщения без медиа отбрасываются.
    """
    # Стикеры и анимации (gif) — это документы, но не «фото/видео»: отбрасываем сразу.
    if getattr(msg, "sticker", None) or getattr(msg, "gif", None):
        return None

    if getattr(msg, "photo", None):
        return "photo" if cfg.photos else None
    if getattr(msg, "video_note", None):
        return "round" if cfg.video_notes else None
    if getattr(msg, "video", None):
        return "video" if cfg.videos else None

    # Документ, отправленный «файлом»: смотрим mime-тип.
    doc = getattr(msg, "document", None)
    if doc is not None:
        mime = (getattr(doc, "mime_type", "") or "").lower()
        if mime.startswith("image/"):
            return "photo_file" if cfg.file_photos else None
        if mime.startswith("video/"):
            return "video_file" if cfg.file_videos else None
    return None


async def resolve_scope(client: TelegramClient, cfg: Config) -> list:
    """Список сущностей-чатов: все диалоги по флагам scope, минус exclude_chats."""
    exclude_ids = set()
    for ident in cfg.exclude_chats:
        try:
            ent = await client.get_entity(ident)
            exclude_ids.add(ent.id)
        except Exception as e:
            log.warning(f"exclude: не удалось разрешить '{ident}': {e}")

    result = []
    skipped = {"group": 0, "channel": 0}
    async for dialog in client.iter_dialogs():
        ent = dialog.entity
        if ent is None or ent.id in exclude_ids:
            continue
        kind = chat_kind(ent)
        if not kind_allowed(kind, cfg.include_groups, cfg.include_channels):
            skipped[kind] += 1
            continue
        result.append(ent)
    if skipped["group"] or skipped["channel"]:
        log.info(f"Пропущено по типам (флаги scope): групп {skipped['group']}, "
                 f"каналов {skipped['channel']}")

    seen, uniq = set(), []
    for ent in result:
        if ent.id not in seen:
            seen.add(ent.id)
            uniq.append(ent)
    return uniq


def _too_big(msg, cfg: Config) -> bool:
    if cfg.max_file_mb <= 0:
        return False
    size = getattr(getattr(msg, "file", None), "size", None)
    return bool(size and size > cfg.max_file_mb * 1024 * 1024)


def _target_path(chat_dir: Path, msg, cat: str) -> Path:
    """Детерминированный путь файла: <id>_<категория><расширение>.

    Детерминированность — основа дедупликации: один и тот же файл всегда лёг бы
    по одному и тому же пути, поэтому повторно его не качаем.
    """
    ext = ""
    f = getattr(msg, "file", None)
    if f is not None and f.ext:
        ext = f.ext
    if not ext:
        ext = ".jpg" if cat in ("photo", "photo_file") else ".bin"
    return chat_dir / f"{msg.id}_{cat}{ext}"


def _short(name: str) -> str:
    """Короткий хвост имени файла для лога (последние 10 символов)."""
    return name[-10:]


def _fmt_duration(seconds: float) -> str:
    """Человекочитаемая длительность: '3.4с' или '2м 05с'."""
    if seconds < 60:
        return f"{seconds:.1f}с"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}м {s:02d}с"


def _fmt_size(num_bytes: int) -> str:
    """Человекочитаемый размер: '12.3 МБ' (для файлов меньше мегабайта — в КБ)."""
    mb = num_bytes / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.1f} МБ"
    return f"{num_bytes / 1024:.0f} КБ"


async def _download_one(client: TelegramClient, msg, path: Path, cfg: Config,
                        gate: "FloodGate", worker: int) -> bool:
    """Скачать медиа сообщения в path. Возвращает True при успехе.

    Качаем во временный *.part и переименовываем только после полной загрузки —
    оборванная закачка (Ctrl+C, обрыв сети) не оставит «готовый» неполный файл.

    gate — общая заслонка FloodWait: перед каждой попыткой ждём общий момент
    возобновления, а словив FloodWait, тормозим им ВСЕХ воркеров, а не только себя.
    worker — номер воркера (для наглядного лога).
    """
    tail = _short(path.name)
    tmp = path.with_name(path.name + ".part")
    # Размер известен из метаданных сообщения ещё до скачивания.
    start_size = getattr(getattr(msg, "file", None), "size", None)
    size_note = f" {_fmt_size(start_size)}" if start_size else ""
    log.info(f"    Worker {worker}: ↓ начал …{tail}{size_note}")

    # Прогресс крупных файлов — шагами по 10%, чтобы большая закачка не выглядела
    # зависшей (мелкие файлы не спамят: лог только для файлов от LARGE_FILE_BYTES).
    last_step = [-1]

    def _progress(received, total):
        if not total or total < LARGE_FILE_BYTES:
            return
        step = int(received * 10 / total)       # 0..10
        if step > last_step[0]:
            last_step[0] = step
            log.info(f"    Worker {worker}: …{tail} {step * 10}% "
                     f"({_fmt_size(received)} / {_fmt_size(total)})")

    while True:
        await gate.wait()                       # общий FloodWait — ждём вместе
        try:
            last_step[0] = -1                   # сброс прогресса на новую попытку
            t0 = time.monotonic()               # чистое время передачи (без ожиданий)
            saved = await client.download_media(msg, file=str(tmp),
                                                progress_callback=_progress)
            elapsed = time.monotonic() - t0
            break
        except FloodWaitError as e:
            wait = e.seconds + cfg.flood_buffer_seconds
            gate.penalize(wait)                 # тормозим всех воркеров до resume_at
            log.warning(f"    Worker {worker}: FloodWait {e.seconds}s — "
                        f"все воркеры ждут {wait}s и повторяют…")
        except Exception as e:
            # Любой не-flood сбой (RPCError, ValueError «Request was unsuccessful N
            # time(s)», обрыв сети и т.п.): помечаем файл проваленным и идём дальше —
            # один битый файл не должен ронять весь чат и вешать пайплайн.
            # CancelledError (Ctrl+C) — BaseException, сюда НЕ попадает.
            log.warning(f"    Worker {worker}: ошибка msg {msg.id}: {e} — пропускаю.")
            tmp.unlink(missing_ok=True)
            return False
    if saved is None:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    size = _fmt_size(path.stat().st_size)
    log.info(f"    Worker {worker}: ✓ готов …{tail} {size} за {_fmt_duration(elapsed)}")
    return True


async def download_chat(client: TelegramClient, entity, cfg: Config,
                        state: dict, output_root: Path, rescan: bool,
                        on_progress, gate: "FloodGate") -> None:
    """Выгрузить медиа одного чата с резюмом по offset_id и дедупом по файлам.

    state — запись прогресса этого чата (мутируется на месте).
    on_progress() — колбэк для периодического сохранения прогресса.
    rescan — игнорировать сохранённый offset и идти с самых новых (чтобы подхватить
             новые сообщения; уже скачанные файлы пропустятся по наличию на диске).
    gate — общая на весь запуск заслонка FloodWait (см. FloodGate).
    """
    cid = entity.id
    title = utils.get_display_name(entity) or str(cid)
    state["title"] = title

    chat_dir = output_root / f"{safe_name(title, str(cid))}_{cid}"
    chat_dir.mkdir(parents=True, exist_ok=True)

    # offset_id=N → iter отдаёт сообщения с id < N. 0 = с самых новых.
    offset_id = 0 if rescan else int(state.get("oldest_id", 0) or 0)

    workers_n = cfg.download_workers
    # Producer кладёт медиа-задания в очередь, N постоянных воркеров их разбирают:
    # освободившийся воркер сразу берёт следующее задание (без ожидания «волны»).
    queue: asyncio.Queue = asyncio.Queue(maxsize=workers_n * 4)

    # --- Непрерывный водяной знак резюма ----------------------------------
    # seq — порядковый номер сообщения в итерации (новые→старые). oldest_id
    # двигаем только по непрерывному завершённому ПРЕФИКСУ (seq 0,1,2,…), иначе
    # при крахе можно перепрыгнуть ещё не докачанное сообщение. В префикс входят
    # и пропуски (текст/не-медиа/уже-скачанное) — они «готовы» сразу.
    seq_id: dict = {}           # seq → msg.id (только незакоммиченные)
    done_seqs: set = set()      # завершённые seq, ещё не закоммиченные
    next_commit = 0             # следующий seq к коммиту
    highest_seq = -1            # последний выданный seq
    committed = 0               # сколько закоммичено (для троттлинга сохранений)

    # Backpressure: не даём окну незакоммиченного разрастись (одна застрявшая
    # большая закачка + длинный «хвост» сообщений после неё → рост памяти).
    window_cap = max(64, workers_n * 16)
    drained = asyncio.Event()
    drained.set()

    SAVE_EVERY = 50

    def _commit_prefix():
        nonlocal next_commit, committed
        advanced = False
        while next_commit in done_seqs:
            done_seqs.discard(next_commit)
            state["oldest_id"] = seq_id.pop(next_commit)
            next_commit += 1
            committed += 1
            advanced = True
        if highest_seq - next_commit <= window_cap:
            drained.set()                               # окно разгрузилось — будим producer
        if advanced and committed % SAVE_EVERY == 0:
            on_progress()

    def _mark_done(seq):
        done_seqs.add(seq)
        _commit_prefix()

    async def worker(worker_no: int):
        while True:
            item = await queue.get()
            try:
                if item is None:                        # сигнал завершения
                    return
                seq, msg, path = item
                ok = await _download_one(client, msg, path, cfg, gate, worker_no)
                state["downloaded" if ok else "failed"] += 1
                _mark_done(seq)
                if cfg.pause_between_files > 0:
                    await asyncio.sleep(cfg.pause_between_files)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker(i + 1)) for i in range(workers_n)]

    seen = 0
    try:
        async for msg in client.iter_messages(entity, offset_id=offset_id):
            seen += 1
            if isinstance(msg, MessageService) or msg is None:
                continue

            # Граница по дате: iter идёт новые→старые, дошли до старого — стоп.
            if cfg.since_date is not None and msg.date is not None:
                mdate = msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=timezone.utc)
                if mdate < cfg.since_date:
                    log.info("    … дошли до даты раньше since_date — останавливаю чат.")
                    break

            # Притормозить, если окно незакоммиченного слишком разрослось.
            if highest_seq - next_commit >= window_cap:
                drained.clear()
                await drained.wait()

            highest_seq += 1
            cur = highest_seq
            seq_id[cur] = msg.id

            cat = media_category(msg, cfg)
            if cat is None:
                _mark_done(cur)                         # не медиа — готово сразу
            elif _too_big(msg, cfg):
                log.info(f"    msg {msg.id}: {cat} больше лимита {cfg.max_file_mb}МБ — пропуск.")
                state["skipped"] += 1
                _mark_done(cur)
            else:
                path = _target_path(chat_dir, msg, cat)
                if path.exists() and path.stat().st_size > 0:
                    state["skipped"] += 1               # уже скачан ранее
                    _mark_done(cur)
                else:
                    await queue.put((cur, msg, path))   # blocks при полной очереди

            if seen % LOG_EVERY == 0:
                log.info(f"    … просмотрено {seen} сообщений "
                         f"(скачано {state['downloaded']}, пропущено {state['skipped']})")
    finally:
        # Сигналим воркерам завершиться и дожидаемся докачки всего, что в очереди.
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)

    _commit_prefix()                                    # докоммитить остаток префикса
    state["done"] = True
    on_progress()
    log.info(f"  Готово: скачано {state['downloaded']}, пропущено {state['skipped']}, "
             f"ошибок {state['failed']} (просмотрено {seen}).")
