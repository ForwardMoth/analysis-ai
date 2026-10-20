# AI Interview

Локальный инструмент: видео/аудио собеседования → транскрипт (FFmpeg + WhisperX + диаризация) → анализ в LLM по готовому промпту.

## Структура

```
AI-Interview/
├── AI Interview.command   # двойной клик: запуск веб-интерфейса (macOS)
├── AI Interview.bat       # двойной клик: запуск веб-интерфейса (Windows)
├── scripts/               # start.sh (macOS/Linux), start.bat и setup.bat (Windows)
├── src/
│   ├── app.py             # точка входа веб-сервера (127.0.0.1:8765)
│   ├── interview_to_transcript.py  # точка входа CLI-конвейера расшифровки
│   ├── ai_interview/
│   │   ├── transcription/ # formatting, media (FFmpeg), pipeline (WhisperX), transcriber, cli
│   │   └── web/           # config, storage, roles, cli (запуск claude/codex), jobs, analysis, practice, uploads, handler, server
│   └── static/            # UI: index.html + css/ (base, upload, transcript, analysis, markdown) + js/ (ES-модули, вход main.js)
├── prompts/
│   ├── analyze-interview.md  # промпт для анализа (не привязан к роли)
│   ├── detect-tasks.md       # промпт автопоиска заданий в записи (границы по таймкодам)
│   ├── analyze-practice.md   # промпт для практических заданий (код, SQL, system design, устные задачи)
│   ├── role.example.md       # шаблон исходной роли
│   └── roles/                # роли <название>.md (frontend, python, devops и др.)
├── docs/
│   └── transcription-setup.md  # установка и подробное использование
├── assets/                # иконки
├── data/                  # рабочие данные (в .gitignore)
│   ├── transcripts/<id>/  # transcript.txt, raw_transcript.json, frames/ (кадры экрана), practice-*.md
│   ├── uploads/  logs/  work/
├── requirements.txt
├── .venv/                 # окружение Python 3.11 (macOS/Linux)
└── .venv-win/             # окружение Python 3.11 (Windows)
```

## Быстрый старт

### 1. Поставьте один раз

| Что | macOS | Windows |
|---|---|---|
| Python 3.11 | `brew install python@3.11` | `winget install Python.Python.3.11` |
| FFmpeg | `brew install ffmpeg` | `winget install Gyan.FFmpeg` (затем откройте новое окно терминала) |
| Зависимости | см. ниже | `scripts\setup.bat` |

macOS / Linux, окружение и зависимости (один раз, из папки проекта):

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Нужно: интернет при первой расшифровке (модели скачиваются автоматически), несколько ГБ на диске (PyTorch и модели).

### 2. Для разделения по говорящим (по желанию)

Зарегистрируйтесь на huggingface.co, примите условия модели [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) и создайте read-токен. Токен можно вставить в поле веб-интерфейса или задать как `HF_TOKEN`. Без него работает только расшифровка без разделения по голосам (`--no-diarize`).

### 3. Для кнопки «Проанализировать» (по желанию)

Нужен хотя бы один установленный и залогиненный CLI: `claude` (Claude Code) или `codex` (ChatGPT). API-ключи не нужны. На Windows `claude` требует Git for Windows. Без них расшифровка работает, не будет только AI-отчёта.

### 4. Запуск

- macOS: двойной клик по `AI Interview.command` или `scripts/start.sh`.
- Windows: двойной клик по `AI Interview.bat` (или `scripts\start.bat`).

Откроется веб-интерфейс на http://127.0.0.1:8765.

### Скорость

- Apple Silicon: распознавание на CPU (у ctranslate2 нет MPS), диаризация на MPS.
- Windows/Linux с NVIDIA: поставьте CUDA-сборку PyTorch и задайте `AI_INTERVIEW_DEVICE=cuda`, это в разы быстрее.
- Docker не нужен: на macOS он теряет доступ к MPS, на Windows даёт ту же скорость, что и нативный запуск.

Папку проекта можно держать общей для обеих систем: у каждой ОС своё окружение (`.venv` и `.venv-win`), а `data/` переносится как есть.

1. Перетащите видео в окно, выберите язык и число говорящих.
2. Заберите `transcript.txt` из `data/transcripts/<id>/`.
3. Прошлые расшифровки видны на главной странице: поиск по названию, тексту и заметкам. К каждой можно добавлять заметки (дата и время ставятся сами, таймкод по клику на реплику).
4. Кнопка «Проанализировать» отправляет транскрипт с `prompts/analyze-interview.md` в Claude (CLI `claude`) или ChatGPT (CLI `codex`) на выбор. Нужны установленные и залогиненные CLI (на Windows `claude` требует Git for Windows), API-ключи не нужны. Результат сохраняется в `data/transcripts/<id>/analysis-*.md`. Заметки и названия лежат в `meta.json` рядом.
5. Роли для анализа: все лежат в `prompts/roles/` (по одному файлу `<название>.md`): frontend-developer, python-developer, java-developer, golang-developer, ml-ds, qa-aqa, system-analyst, devops. Свою роль заведите так: `cp prompts/role.example.md prompts/roles/java-senior.md` и отредактируйте. Перед анализом роль выбирается в списке (с поиском; последний выбор запоминается), она добавляется к запросу блоком «ИСХОДНАЯ РОЛЬ» и указывается в сохранённом анализе. «Определить по интервью» — модель сама назовёт роль в начале отчёта.

6. Практические задания (лайвкодинг, SQL, system design, задачи на экране с устным ответом) разбираются той же кнопкой «Проанализировать», отдельных действий нет. При расшифровке видео с экраном приложение сохраняет только те кадры, где экран менялся (обычно 100–400 штук, единицы мегабайт), а само видео удаляется, как и раньше. Анализ идёт в несколько шагов: (1) CLI читает транскрипцию и находит задания с границами и типом (`prompts/detect-tasks.md`, только текст, быстро); (2) каждое задание разбирается отдельно по кадрам (до 10 на задание) вместе с репликами за этот отрезок, то есть экран сочетается с голосом (`prompts/analyze-practice.md`; результат лежит в `practice-*.md`); (3) общий отчёт по `prompts/analyze-interview.md` получает эти разборы и включает их отдельными подразделами с таймкодами, вердиктом и эталонным решением. Для аудио и старых записей кадров нет: анализ идёт по голосу, как раньше. Если разбор одного задания не удался, остальное всё равно доходит до отчёта, а в нём это отмечено. Чем выше разрешение записи экрана (от 1280×720), тем надёжнее читается код. Прогресс на вкладке показывает текущий этап.

Подробная установка и использование CLI — в [docs/transcription-setup.md](docs/transcription-setup.md).
