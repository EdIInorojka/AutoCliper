"""Interactive Russian wizard for the Windows launcher.

The CMD files intentionally stay ASCII-only. Russian text lives here so that
Windows CMD never tries to parse mojibake prompts as commands.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class WizardOptions:
    input_path: str
    language: str
    output_dir: str
    clips: int
    render_preset: str
    cta_text_mode: str = "file"
    cta_text: str = ""
    cta_voice: str = ""
    quick_preview: bool = False
    preview_layout: bool = True
    preview_time: str = ""
    delete_source: bool = False
    music: bool = False


def _read(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _choice(prompt: str, choices: dict[str, tuple[str, str]], default: str) -> str:
    print(prompt)
    for key, (title, description) in choices.items():
        print(f"  {key}. {title}{' - ' + description if description else ''}")
    while True:
        value = _read("Выбор", default).strip()
        if value in choices:
            return value
        print("Введите номер из списка.")


def _yes_no(prompt: str, default: bool = False) -> bool:
    default_text = "д" if default else "н"
    while True:
        value = _read(f"{prompt} (д/н)", default_text).lower()
        if value in {"д", "да", "y", "yes"}:
            return True
        if value in {"н", "нет", "n", "no"}:
            return False
        print("Введите д или н.")


def _ask_clips() -> int:
    while True:
        raw = _read("6. Сколько клипов сделать из этого видео", "5")
        try:
            clips = int(raw)
        except ValueError:
            print("Нужно целое число, например 5.")
            continue
        if 1 <= clips <= 100:
            return clips
        print("Поставьте число от 1 до 100.")


def _normalize_voice_path(raw: str) -> str:
    value = raw.strip().strip('"')
    if not value:
        return ""
    path = Path(value)
    if not path.exists():
        print("Файл озвучки не найден, продолжаю без него:")
        print(f"  {value}")
        return ""
    return str(path)


def _build_cli_args(options: WizardOptions) -> list[str]:
    args = [
        "-m",
        "app.main",
        "--input",
        options.input_path,
        "--subtitle-lang",
        options.language,
        "--cta-lang",
        options.language,
        "--output-dir",
        options.output_dir,
        "--clips",
        str(options.clips),
        "--render-preset",
        options.render_preset,
        "--no-music",
    ]

    if options.cta_text_mode == "custom" and options.cta_text:
        args.extend(["--cta-text", options.cta_text])
    else:
        args.extend(["--cta-text-mode", "file"])

    if options.cta_voice:
        args.extend(["--cta-voice", options.cta_voice])
    if options.quick_preview:
        args.append("--quick-preview")
    if options.preview_layout:
        args.append("--preview-layout")
        if options.preview_time:
            args.extend(["--preview-time", options.preview_time])
    if options.delete_source:
        args.append("--delete-input-after-success")
    if options.music:
        args.remove("--no-music")
        args.append("--music")

    return args


def _print_summary(options: WizardOptions, command: Iterable[str]) -> None:
    print()
    print("============================================")
    print("  Запускаю генерацию")
    print("============================================")
    print(f"Видео/ссылка:       {options.input_path}")
    print(f"Язык:               {'русский' if options.language == 'ru' else 'английский'}")
    print(
        "CTA текст:          "
        + (options.cta_text if options.cta_text_mode == "custom" and options.cta_text else "стандартный файл")
    )
    print(f"CTA озвучка:        {options.cta_voice or 'нет'}")
    print(f"Папка выгрузки:     {options.output_dir}")
    print(f"Количество клипов:  {options.clips}")
    print(f"Качество:           {options.render_preset}")
    print(f"Музыка:             {'вкл' if options.music else 'выкл'}")
    print(f"Предпросмотр:       {'да' if options.preview_layout else 'нет'}")
    if options.preview_time:
        print(f"Кадр предпросмотра: {options.preview_time}")
    print(f"Быстрый preview:    {'да' if options.quick_preview else 'нет'}")
    print(f"Удалить исходник:   {'да' if options.delete_source else 'нет'}")
    print()
    print("Команда:")
    print("  " + subprocess.list2cmdline([sys.executable, *command]))
    print()


def collect_options() -> WizardOptions:
    print("============================================")
    print("  StreamCuter - мастер генерации клипов")
    print("============================================")
    print()

    input_path = _read("1. Путь к видео или ссылка YouTube/Kick").strip().strip('"')
    while not input_path:
        print("Путь или ссылка обязательны.")
        input_path = _read("1. Путь к видео или ссылка YouTube/Kick").strip().strip('"')

    lang_choice = _choice(
        "2. Язык субтитров и надписи на паузе",
        {
            "1": ("Русский", ""),
            "2": ("Английский", ""),
        },
        "1",
    )
    language = "ru" if lang_choice == "1" else "en"

    cta_choice = _choice(
        "3. Надпись на момент зависания",
        {
            "1": ("Стандартные фразы из файла", "берутся по выбранному языку"),
            "2": ("Своя надпись", "будет автоматически ужата по ширине"),
        },
        "1",
    )
    cta_text_mode = "file"
    cta_text = ""
    if cta_choice == "2":
        cta_text = _read("Введите свою надпись").strip()
        if cta_text:
            cta_text_mode = "custom"

    cta_voice = _normalize_voice_path(
        _read("4. Файл озвучки паузы mp3/wav, Enter = без озвучки")
    )
    output_dir = _read("5. Папка для готовых видео", "output\\generated").strip().strip('"')
    clips = _ask_clips()

    render_choice = _choice(
        "7. Качество рендера",
        {
            "1": ("Максимальное качество", "медленнее, меньше артефактов"),
            "2": ("Баланс", "быстрее, качество нормальное"),
            "3": ("Быстро", "для черновиков"),
            "4": ("Маленький размер", "сильнее сжимает"),
            "5": ("NVIDIA NVENC", "если есть видеокарта NVIDIA"),
        },
        "1",
    )
    render_preset = {
        "1": "quality",
        "2": "balanced",
        "3": "fast",
        "4": "small",
        "5": "nvenc_fast",
    }[render_choice]

    preview_layout = _yes_no("8. Открыть окно, где можно выбрать вебку и слот", True)
    preview_time = ""
    if preview_layout:
        preview_time = _read(
            "   Момент для кадра предпросмотра, Enter = середина видео, примеры 180 или 03:00"
        ).strip()

    quick_preview = _yes_no("9. Сделать только быстрый preview одного клипа", False)
    delete_source = _yes_no("10. Удалить исходное видео после успешной генерации", False)

    return WizardOptions(
        input_path=input_path,
        language=language,
        output_dir=output_dir,
        clips=clips,
        render_preset=render_preset,
        cta_text_mode=cta_text_mode,
        cta_text=cta_text,
        cta_voice=cta_voice,
        quick_preview=quick_preview,
        preview_layout=preview_layout,
        preview_time=preview_time,
        delete_source=delete_source,
        music=False,
    )


def main() -> int:
    try:
        options = collect_options()
    except KeyboardInterrupt:
        print()
        print("Отменено пользователем.")
        return 130

    cli_args = _build_cli_args(options)
    _print_summary(options, cli_args)

    try:
        return subprocess.call([sys.executable, *cli_args], cwd=os.getcwd())
    except KeyboardInterrupt:
        print()
        print("Остановлено пользователем.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
