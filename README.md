# Reddit2Shorts

_Бизнес-задача которую решает проект: Автоматическая генерация YouTube Shorts из Reddit-постов для массового производства вирусного короткого контента._

Автоматизированная генерация YouTube Shorts из историй с Reddit.

Reddit → LLM-скрипт → Картинки → Озвучка → Видео → YouTube

## Что делает

1. **Забирает** посты из указанного сабреддита (топ за месяц/неделю/день)
2. **Генерирует сценарий** через LLM (Gemini / Cerebras / OpenRouter) — 3–4 сцены, до 40 секунд
3. **Создаёт изображения** для каждой сцены (Pollinations.ai)
4. **Озвучивает** текст (Kokoro / Chatterbox / Pollinations TTS)
5. **Собирает видео** с субтитрами, эффектом Ken Burns и фоновой музыкой (MoviePy)
6. **Загружает** на YouTube — сразу или по расписанию (scheduled publishing)

Повторно обработанные посты автоматически пропускаются (локальный трекер + Google Sheets).

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Python ≥ 3.12.

## Настройка

Скопируйте `.env.example` в `.env` и заполните ключи:

```bash
cp .env.example .env
```

Основные переменные:

| Переменная | Описание |
|---|---|
| `REDDIT__CLIENT_ID` | Reddit API client ID |
| `REDDIT__CLIENT_SECRET` | Reddit API client secret |
| `REDDIT__SUBREDDIT` | Целевой сабреддит (по умолчанию `selfimprovement`) |
| `IMAGE__POLLINATIONS_API_KEY` | Ключ Pollinations.ai для генерации картинок |
| `YOUTUBE__CLIENT_SECRETS_FILE` | Путь к OAuth2 секрету YouTube |
| `GOOGLE_SHEETS__CREDENTIALS_FILE` | Путь к service account JSON |
| `GOOGLE_SHEETS__SPREADSHEET_ID` | ID таблицы для трекинга |

Подробная конфигурация — через `config.yaml` (LLM-провайдеры, TTS, видео-параметры, расписание).

## Запуск

Одно видео:
```bash
python -m reddit2shorts reddit --num-videos 1
```

Дневной батч с отложенной публикацией:
```bash
python -m reddit2shorts reddit --num-videos 6
```

Dry-run (без загрузки на YouTube):
```bash
python -m reddit2shorts reddit --num-videos 1 --dry-run
```

## Структура проекта

```
reddit2shorts/
├── __init__.py
├── __main__.py          # python -m reddit2shorts
├── main.py              # Точка входа
├── cli.py               # Click CLI
├── cli_factory.py       # Авто-генерация команд из реестра
├── config/
│   ├── __init__.py
│   └── settings.py      # Pydantic Settings + YAML
├── core/
│   ├── base_orchestrator.py
│   ├── reddit_orchestrator.py  # Основной пайплайн Reddit→YouTube
│   ├── orchestrator_registry.py
│   ├── service_factory.py
│   ├── scheduled_publisher.py  # Отложенная публикация
│   ├── state.py               # Состояние воркфлоу
│   ├── exceptions.py
│   └── mixins/
│       ├── image_based.py
│       ├── music.py
│       ├── subtitles.py
│       └── video_generation.py
├── models/
│   ├── reddit.py         # RedditStory
│   └── script.py         # GeneratedScript, ScriptSegment
├── services/
│   ├── image.py          # Pollinations / Gemini
│   ├── reddit.py         # Reddit API (PRAW + public)
│   ├── sheets.py         # Google Sheets
│   ├── video.py          # VideoService (API)
│   ├── video_local.py    # Local video server
│   ├── video_moviepy.py  # MoviePy сборка
│   ├── youtube.py        # YouTube upload + scheduling
│   ├── llm/
│   │   ├── base.py
│   │   ├── gemini_provider.py
│   │   ├── openai_provider.py
│   │   └── service.py
│   └── tts/
│       ├── base.py
│       ├── kokoro.py
│       ├── kokoro_onnx.py
│       ├── chatterbox.py
│       ├── pollinations_tts.py
│       ├── local_server.py
│       └── service.py
└── utils/
    ├── api_rotator.py     # Ротация API-ключей
    ├── file_manager.py
    ├── logger.py
    ├── processed_tracker.py
    ├── proxy.py
    ├── retry.py
    └── thumbnail.py
```

## Арххитектура

- **Оркестратор** (`reddit_orchestrator.py`) координирует весь пайплайн
- **Service Factory** создаёт сервисы по конфигурации
- **Mixins** (`SubtitlesMixin`, `MusicMixin`, `ImageBasedMixin`, `VideoGenerationMixin`) — переиспользуемые блоки для разных флоу
- **API Rotator** — автоматическая ротация ключей с retry-логикой
- **Scheduled Publisher** — генерация расписания публикации (случайные интервалы в заданном окне)

## Лицензия

Приватный проект. Все права защищены.
