#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tg-media-downloader — точка входа.

    python download.py                      # выгрузка медиа из всех чатов (резюмируемая)
    python download.py --config config.yaml # явный конфиг
    python download.py --rescan             # подхватить новые сообщения в уже пройденных чатах
    python download.py --reset-progress     # начать заново (сбросить прогресс)
"""

from tgmedia.app import main

if __name__ == "__main__":
    main()
