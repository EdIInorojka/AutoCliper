"""Interactive Russian wizard for the Windows launcher."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from app.utils.console import get_console

console = get_console()


@dataclass
class WizardOptions:
    input_path: str
    language: str
    output_dir: str
    clips: int
    render_preset: str
    input_start_sec: Optional[float] = None
    input_end_sec: Optional[float] = None
    cta_text_mode: str = "file"
    cta_text: str = ""
    cta_voice: str = ""
    preview_layout: bool = True
    preview_time: str = ""
    delete_source: bool = False
    music: bool = False
    banner: bool = False


def _print_header(title: str) -> None:
    console.print()
    console.print("[bold cyan]============================================[/bold cyan]")
    console.print(f"[bold cyan]  {title}[/bold cyan]")
    console.print("[bold cyan]============================================[/bold cyan]")
    console.print()


def _read(prompt: str, default: str = "") -> str:
    suffix = f" [[dim]{default}[/dim]]" if default else ""
    console.print(f"[cyan]{prompt}[/cyan]{suffix}")
    value = input("  > ").strip()
    return value or default


def _choice(prompt: str, choices: dict[str, tuple[str, str]], default: str) -> str:
    console.print(f"[bold cyan]{prompt}[/bold cyan]")
    for key, (title, description) in choices.items():
        if description:
            console.print(f"  [yellow]{key}[/yellow]. [white]{title}[/white] [dim]- {description}[/dim]")
        else:
            console.print(f"  [yellow]{key}[/yellow]. [white]{title}[/white]")
    while True:
        value = _read("Выбор", default).strip()
        if value in choices:
            return value
        console.print("[yellow]Введите номер из списка.[/yellow]")


def _bool_choice(prompt: str, default: bool = False) -> bool:
    value = _choice(
        prompt,
        {
            "1": ("Да", ""),
            "2": ("Нет", ""),
        },
        "1" if default else "2",
    )
    return value == "1"


def _ask_clips() -> int:
    while True:
        raw = _read("6. Сколько клипов сделать из этого видео", "5")
        try:
            clips = int(raw)
        except ValueError:
            console.print("[yellow]Нужно целое число, например 5.[/yellow]")
            continue
        if 1 <= clips <= 100:
            return clips
        console.print("[yellow]Поставьте число от 1 до 100.[/yellow]")


def _normalize_voice_path(raw: str) -> str:
    value = raw.strip().strip('"')
    if not value:
        return ""
    path = Path(value)
    if not path.exists():
        console.print("[yellow]Файл озвучки не найден, продолжаю без него:[/yellow]")
        console.print(f"  [dim]{value}[/dim]")
        return ""
    return str(path)


def _fmt_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _select_input_range(input_path: str) -> tuple[Optional[float], Optional[float]]:
    try:
        from app.downloader import resolve_input_metadata
        from app.trim_selector import select_input_range
    except Exception as exc:
        console.print(f"[yellow]Не удалось открыть выбор диапазона: {exc}[/yellow]")
        return None, None

    try:
        metadata = resolve_input_metadata(input_path, announce=False)
    except Exception as exc:
        console.print(f"[yellow]Не удалось получить длительность входа: {exc}[/yellow]")
        return None, None

    if metadata.duration_sec <= 1.0:
        console.print("[yellow]Видео слишком короткое для выбора диапазона, продолжаю целиком.[/yellow]")
        return None, None

    try:
        selected = select_input_range(
            title=metadata.display_name,
            duration_sec=metadata.duration_sec,
        )
    except Exception as exc:
        console.print(f"[yellow]Окно выбора диапазона не открылось: {exc}[/yellow]")
        return None, None

    if selected is None:
        console.print("[dim]Диапазон не выбран, продолжаю с целым видео.[/dim]")
        return None, None

    start_sec, end_sec = selected
    if start_sec <= 0.0 and abs(end_sec - metadata.duration_sec) <= 0.01:
        return None, None
    return start_sec, end_sec


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
    ]

    if options.input_start_sec is not None:
        args.extend(["--input-start", f"{options.input_start_sec:.3f}"])
    if options.input_end_sec is not None:
        args.extend(["--input-end", f"{options.input_end_sec:.3f}"])

    if options.cta_text_mode == "custom" and options.cta_text:
        args.extend(["--cta-text", options.cta_text])
    else:
        args.extend(["--cta-text-mode", "file"])

    if options.cta_voice:
        args.extend(["--cta-voice", options.cta_voice])
    if options.preview_layout:
        args.append("--preview-layout")
        if options.preview_time:
            args.extend(["--preview-time", options.preview_time])
    if options.delete_source:
        args.append("--delete-input-after-success")
    if options.music:
        args.append("--music")
    if options.banner:
        args.append("--banner")

    return args


def _print_summary(options: WizardOptions, command: Iterable[str]) -> None:
    _print_header("Запускаю генерацию")
    console.print(f"[white]Видео/ссылка:[/white]       [bold]{options.input_path}[/bold]")
    if options.input_start_sec is not None or options.input_end_sec is not None:
        start_label = _fmt_timestamp(options.input_start_sec or 0.0)
        end_label = _fmt_timestamp(options.input_end_sec) if options.input_end_sec is not None else "до конца"
        console.print(f"[white]Диапазон входа:[/white]     [bold]{start_label} - {end_label}[/bold]")
    console.print(
        f"[white]Язык:[/white]               [bold]{'русский' if options.language == 'ru' else 'английский'}[/bold]"
    )
    console.print(
        "[white]CTA текст:[/white]          "
        + (
            f"[bold]{options.cta_text}[/bold]"
            if options.cta_text_mode == "custom" and options.cta_text
            else "[bold]стандартный файл[/bold]"
        )
    )
    console.print(f"[white]CTA озвучка:[/white]        [bold]{options.cta_voice or 'нет'}[/bold]")
    console.print(f"[white]Папка выгрузки:[/white]     [bold]{options.output_dir}[/bold]")
    console.print(f"[white]Количество клипов:[/white]  [bold]{options.clips}[/bold]")
    console.print(f"[white]Качество:[/white]           [bold]{options.render_preset}[/bold]")
    console.print("[white]Музыка:[/white]             [bold]только Apply Cinema из musiccinema[/bold]")
    console.print(f"[white]Баннер:[/white]             [bold]{'да' if options.banner else 'нет'}[/bold]")
    console.print(f"[white]Предпросмотр:[/white]       [bold]{'да' if options.preview_layout else 'нет'}[/bold]")
    if options.preview_time:
        console.print(f"[white]Кадр предпросмотра:[/white] [bold]{options.preview_time}[/bold]")
    console.print(f"[white]Удалить исходник:[/white]   [bold]{'да' if options.delete_source else 'нет'}[/bold]")
    console.print()
    console.print("[bold cyan]Команда:[/bold cyan]")
    console.print("  " + subprocess.list2cmdline([sys.executable, *command]))
    console.print()


def collect_options() -> WizardOptions:
    _print_header("StreamCuter - мастер генерации клипов")

    input_path = _read("1. Путь к видео или ссылка YouTube/Kick").strip().strip('"')
    while not input_path:
        console.print("[yellow]Путь или ссылка обязательны.[/yellow]")
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

    banner_enabled = _bool_choice("8. Добавить баннер (только для Apply Cinema)", False)

    input_start_sec = None
    input_end_sec = None
    if _bool_choice("9. Ограничить диапазон входного видео", False):
        input_start_sec, input_end_sec = _select_input_range(input_path)

    preview_layout = True
    console.print("[cyan]10. Окно выбора вебки/слота будет открыто автоматически.[/cyan]")
    preview_time = ""
    preview_time = _read(
        "   Момент для кадра предпросмотра, Enter = середина видео, примеры 180 или 03:00"
    ).strip()

    delete_source = _bool_choice("11. Удалить исходное видео после успешной генерации", False)

    return WizardOptions(
        input_path=input_path,
        language=language,
        output_dir=output_dir,
        clips=clips,
        render_preset=render_preset,
        input_start_sec=input_start_sec,
        input_end_sec=input_end_sec,
        cta_text_mode=cta_text_mode,
        cta_text=cta_text,
        cta_voice=cta_voice,
        preview_layout=preview_layout,
        preview_time=preview_time,
        delete_source=delete_source,
        music=False,
        banner=banner_enabled,
    )


def _ask_run_again() -> bool:
    console.print()
    return _choice(
        "Генерация завершена. Что дальше?",
        {
            "1": ("Сгенерировать ещё", "вернуться к вводу новой ссылки"),
            "2": ("Выход", ""),
        },
        "2",
    ) == "1"


def main() -> int:
    while True:
        try:
            options = collect_options()
        except KeyboardInterrupt:
            console.print()
            console.print("[yellow]Отменено пользователем.[/yellow]")
            return 130

        cli_args = _build_cli_args(options)
        _print_summary(options, cli_args)

        try:
            exit_code = subprocess.call([sys.executable, *cli_args], cwd=os.getcwd())
        except KeyboardInterrupt:
            console.print()
            console.print("[yellow]Остановлено пользователем.[/yellow]")
            return 130

        if exit_code != 0:
            return exit_code

        if not _ask_run_again():
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
