# Бесплатная автоматизация расшифровки собеседований

Этот скрипт берёт **локальный видео- или аудиофайл** и выполняет весь процесс:

`interview.mp4 → FFmpeg → WhisperX (+ диаризация) → transcript.txt`

## Установка (один раз)

### macOS

1. Установите Homebrew (если ещё не установлен): https://brew.sh/
2. Установите Python 3.11 и FFmpeg:

```bash
brew install python@3.11 ffmpeg
```

3. Перейдите в папку проекта и создайте окружение с зависимостями (версия WhisperX закреплена в `requirements.txt`):

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

При первой расшифровке нужен интернет: модели скачиваются автоматически. Заложите несколько ГБ на диске (PyTorch и модели).

4. Для разделения по говорящим зарегистрируйтесь на https://huggingface.co/, примите условия https://huggingface.co/pyannote/speaker-diarization-community-1 и создайте read token на https://huggingface.co/settings/tokens.

В терминале перед запуском:

```bash
export HF_TOKEN='hf_ваш_токен'
```

**Не публикуйте свой токен и не сохраняйте его в репозиторий.**

### Анализ в LLM (по желанию)

Кнопке «Проанализировать» нужен установленный и залогиненный CLI `claude` (Claude Code) и/или `codex`; API-ключи не нужны. На Windows `claude` требует Git for Windows (`winget install Git.Git`). Без них расшифровка работает, недоступен только AI-отчёт.

### Windows 10/11

1. Установите Python 3.11 и FFmpeg (в PowerShell или cmd):

```bat
winget install Python.Python.3.11
winget install Gyan.FFmpeg
```

После установки FFmpeg откройте новое окно терминала: PATH обновляется только для новых окон.

2. Запустите `scripts\setup.bat`: он создаст окружение `.venv-win` и поставит зависимости (WhisperX тянет PyTorch, это несколько ГБ).
3. HF_TOKEN: `set HF_TOKEN=hf_ваш_токен` (cmd) или `$env:HF_TOKEN='hf_ваш_токен'` (PowerShell) либо вставьте в поле веб-интерфейса.
4. Запуск: двойной клик по `AI Interview.bat`.

CLI: `.venv-win\Scripts\activate`, затем `python src\interview_to_transcript.py "C:\путь\interview.mp4" --language ru --speakers 2`.

Нюансы Windows:

- Если при установке PyTorch или запуске видна ошибка про `VCRUNTIME140`/`MSVCP140`, поставьте Microsoft Visual C++ Redistributable 2015–2022 (`winget install Microsoft.VCRedist.2015+.x64`).
- Hugging Face кэширует модели в `%USERPROFILE%\.cache\huggingface`; без режима разработчика Windows копирует файлы вместо симлинков, поэтому кэш занимает больше места.
- Имена загружаемых файлов приводятся к допустимым для Windows (запрещённые символы `<>:"|?*` заменяются на `_`, имя укорачивается), в библиотеке остаётся исходное название.
- Видеокарта NVIDIA: поставьте CUDA-сборку PyTorch и задайте `AI_INTERVIEW_DEVICE=cuda`. По умолчанию всё считается на CPU.
- Если путь к проекту очень длинный, включите длинные пути Windows или переместите проект ближе к корню диска.

## Веб-интерфейс (без копирования путей)

```bash
source .venv/bin/activate
python src/app.py
```

Откройте http://127.0.0.1:8765, перетащите видео в окно, выберите язык и число говорящих, нажмите «Расшифровать». Прогресс виден на странице, результат можно скопировать, скачать или показать в Finder / Проводнике. HF_TOKEN можно вставить в поле (нигде не сохраняется) или задать через `export`. Сервер слушает только localhost; результаты лежат в `data/transcripts/`, загруженная копия видео удаляется после обработки.

## Использование (командная строка)

Перейдите в папку со скриптом, активируйте окружение:

```bash
source .venv/bin/activate
```

Запустите анализ для русского интервью с двумя говорящими:

```bash
python src/interview_to_transcript.py "/путь/к/собеседованию.mp4" --language ru --speakers 2
```

Или без указания пути — скрипт попросит ввести или перетащить путь в терминал:

```bash
python src/interview_to_transcript.py --speakers 2
```

Если участников более двух, просто не используйте `--speakers 2`.

Для англоязычного интервью:

```bash
python src/interview_to_transcript.py "interview.mp4" --language en --speakers 2
```

Без Hugging Face, без разделения по голосам:

```bash
python src/interview_to_transcript.py "interview.mp4" --no-diarize
```

Чтобы повысить точность на сильном компьютере, пробуйте `--model medium` вместо `small` (медленнее).

## Результат

Рядом с файлом появится папка `interview_transcript` с:

- `transcript.txt`: текст с таймкодами и условными обозначениями участников;
- `raw_transcript.json`: исходные фрагменты с временными метками для дальнейшего анализа.

Отправьте `transcript.txt` в ChatGPT, если участники разрешили такую передачу данных.

## Ограничения

- Понадобятся достаточно свободного места на диске, время для загрузки моделей и обработки.
- На Mac распознавание (ASR) идёт на CPU, у ctranslate2 нет MPS, и для 90-минутного видео может быть медленно. Диаризация на Apple Silicon считается на MPS (`AI_INTERVIEW_DIARIZE_DEVICE` меняет устройство).
- Docker не рекомендуется: на macOS в контейнере нет доступа к MPS, диаризация уйдёт на CPU и замедлится в разы.
- Диаризация иногда путает говорящих.
- Для приватных интервью предпочтительно не отправлять записи в облачные сервисы без разрешения участников.

Исходный проект: https://github.com/m-bain/whisperX
