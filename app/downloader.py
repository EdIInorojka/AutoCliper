"""Video input resolution and yt-dlp integration."""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.utils.console import get_console
from app.utils.helpers import ffmpeg_exe, safe_filename

console = get_console()


@dataclass
class InputMetadata:
    source: str
    duration_sec: float
    display_name: str
    is_remote: bool


@dataclass
class ResolvedInput:
    source: str
    working_path: str
    delete_target: Optional[str]
    duration_sec: Optional[float]
    is_remote: bool
    selected_range: Optional[tuple[float, float]] = None


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _is_ascii_path(path: str) -> bool:
    try:
        path.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _windows_short_path(path: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        get_short_path = ctypes.windll.kernel32.GetShortPathNameW
        needed = get_short_path(path, None, 0)
        if needed <= 0:
            return None
        buffer = ctypes.create_unicode_buffer(needed)
        written = get_short_path(path, buffer, needed)
        if written <= 0:
            return None
        short_path = buffer.value
        if short_path and os.path.exists(short_path) and _is_ascii_path(short_path):
            return short_path
    except Exception:
        return None
    return None


def _copy_certifi_to_ascii_path(certifi_path: str) -> str | None:
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.append(Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "StreamCuter" / "certs")
    candidates.extend(
        [
            Path("tools") / "certs",
            Path("temp") / "certs",
        ]
    )

    for folder in candidates:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target = (folder / "cacert.pem").resolve()
            shutil.copyfile(certifi_path, target)
            target_str = str(target)
            if _is_ascii_path(target_str):
                return target_str
            short_path = _windows_short_path(target_str)
            if short_path:
                return short_path
        except OSError:
            continue
    return None


def _prepare_ascii_ca_bundle() -> str | None:
    """Return a CA bundle path that libcurl can consume on Cyrillic Windows profiles."""
    try:
        import certifi
    except Exception:
        return None

    certifi_path = certifi.where()
    if os.path.exists(certifi_path):
        if _is_ascii_path(certifi_path):
            return certifi_path
        short_path = _windows_short_path(certifi_path)
        if short_path:
            return short_path
        return _copy_certifi_to_ascii_path(certifi_path)
    return None


def configure_yt_dlp_tls() -> str | None:
    """Point curl_cffi/yt-dlp to an ASCII CA bundle path when available."""
    ca_bundle = _prepare_ascii_ca_bundle()
    if not ca_bundle:
        return None

    os.environ["CURL_CA_BUNDLE"] = ca_bundle
    os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
    os.environ["SSL_CERT_FILE"] = ca_bundle

    try:
        import curl_cffi.curl as curl_cffi_curl

        curl_cffi_curl.DEFAULT_CACERT = ca_bundle
    except Exception:
        pass

    return ca_bundle


def _looks_like_curl_cert_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "curl: (77)" in text
        or "error setting certificate verify locations" in text
        or ("cafile:" in text and "certifi" in text)
    )


def _browser_cookie_spec_from_env() -> tuple[str, str | None, str | None, str | None] | None:
    raw = os.environ.get("STREAMCUTER_COOKIES_FROM_BROWSER", "").strip()
    if not raw:
        return None

    match = re.fullmatch(
        r"""(?x)
        (?P<name>[^+:]+)
        (?:\s*\+\s*(?P<keyring>[^:]+))?
        (?:\s*:\s*(?!:)(?P<profile>.+?))?
        (?:\s*::\s*(?P<container>.+))?
        """,
        raw,
    )
    if match is None:
        raise RuntimeError(
            "Invalid STREAMCUTER_COOKIES_FROM_BROWSER value. "
            "Use yt-dlp syntax like chrome or chrome:Default."
        )

    browser_name, keyring, profile, container = match.group("name", "keyring", "profile", "container")
    browser_name = browser_name.lower()
    if keyring is not None:
        keyring = keyring.upper()

    return browser_name, profile, keyring, container


def _format_browser_cookie_spec(spec: tuple[str, str | None, str | None, str | None]) -> str:
    browser_name, profile, keyring, container = spec
    text = browser_name
    if keyring:
        text += f"+{keyring}"
    if profile:
        text += f":{profile}"
    if container:
        text += f"::{container}"
    return text


def _detect_js_runtime() -> dict[str, dict] | None:
    runtime_override = os.environ.get("STREAMCUTER_YTDLP_JS_RUNTIME", "").strip().lower()
    if runtime_override:
        if runtime_override in {"node", "deno", "bun", "quickjs"}:
            return {runtime_override: {}}
        raise RuntimeError(
            "Invalid STREAMCUTER_YTDLP_JS_RUNTIME value. "
            "Use node, deno, bun, or quickjs."
        )

    for runtime in ("node", "deno"):
        if shutil.which(runtime):
            return {runtime: {}}
    return None


def _yt_dlp_cachedir() -> str:
    cache_root = os.environ.get("STREAMCUTER_YTDLP_CACHE_DIR", "").strip()
    if not cache_root:
        cache_root = str(Path("cache") / "yt-dlp")
    path = Path(cache_root)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _base_yt_dlp_opts(temp_dir: str, outtmpl: str | None = None, *, announce: bool = False) -> dict:
    out_tmpl = outtmpl or os.path.join(temp_dir, "%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl": out_tmpl,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
        "retries": 3,
        "fragment_retries": 3,
        "cachedir": _yt_dlp_cachedir(),
        "extractor_args": {
            "generic": {"impersonate": ["chrome"]},
            "kick": {"impersonate": ["chrome"]},
            "youtube": {"impersonate": ["chrome"]},
        },
    }

    js_runtime = _detect_js_runtime()
    if js_runtime:
        ydl_opts["js_runtimes"] = js_runtime
        ydl_opts["remote_components"] = ["ejs:github"]
        if announce:
            console.print(f"[dim]Using yt-dlp JS runtime: {next(iter(js_runtime))}[/dim]")
            console.print("[dim]Using yt-dlp remote components: ejs:github[/dim]")

    cookies_file = os.environ.get("STREAMCUTER_COOKIES_FILE", "").strip()
    if not cookies_file:
        default_cookies = Path(__file__).resolve().parent.parent / "cookies.txt"
        if default_cookies.exists():
            cookies_file = str(default_cookies)
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
        if announce:
            console.print(f"[dim]Using cookie file: {cookies_file}[/dim]")

    browser_cookies = _browser_cookie_spec_from_env()
    if browser_cookies:
        ydl_opts["cookiesfrombrowser"] = browser_cookies
        if announce:
            console.print(
                f"[dim]Using browser cookies from: {_format_browser_cookie_spec(browser_cookies)}[/dim]"
            )

    return ydl_opts


def _range_output_template(temp_dir: str, start_sec: float, end_sec: float) -> str:
    start_ms = int(round(float(start_sec) * 1000))
    end_ms = int(round(float(end_sec) * 1000))
    return os.path.join(temp_dir, f"%(id)s__range_{start_ms}_{end_ms}.%(ext)s")


def _range_output_path(temp_dir: str, video_id: str, start_sec: float, end_sec: float, ext: str = "mp4") -> str:
    start_ms = int(round(float(start_sec) * 1000))
    end_ms = int(round(float(end_sec) * 1000))
    safe_id = safe_filename(video_id or "video")
    safe_ext = safe_filename(ext or "mp4").lstrip(".") or "mp4"
    return str(Path(temp_dir) / f"{safe_id}__range_{start_ms}_{end_ms}.{safe_ext}")


def _download_with_yt_dlp(yt_dlp, url: str, ydl_opts: dict, temp_dir: str) -> str:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except Exception as e:
            message = str(e)
            if "403" in message or "Forbidden" in message:
                raise RuntimeError(
                    "yt-dlp was blocked while fetching this URL. "
                    "Kick often requires a browser-like request and sometimes cookies. "
                    "Retry with a local cookie file or a supported browser session if the site "
                    "still blocks anonymous access."
                ) from e
            raise

        if "requested_downloads" in info and info["requested_downloads"]:
            for dl in info["requested_downloads"]:
                if dl.get("_filename"):
                    fn = dl["_filename"]
                    if os.path.exists(fn):
                        console.print(f"[green]Downloaded: {fn}[/green]")
                        return fn

        p = Path(temp_dir)
        mp4s = list(p.glob("*.mp4"))
        if mp4s:
            mp4s.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            console.print(f"[green]Downloaded: {mp4s[0]}[/green]")
            return str(mp4s[0])

    raise RuntimeError(f"yt-dlp did not produce a file for {url}")


def _friendly_remote_extract_error_message(exc: Exception) -> str | None:
    text = str(exc).lower()
    if any(
        marker in text
        for marker in (
            "sign in to confirm you're not a bot",
            "sign in to confirm you’re not a bot",
            "sign in to confirm your age",
            "cookies for the authentication",
            "use --cookies-from-browser or --cookies",
            "use --cookies or --cookies-from-browser",
        )
    ):
        return (
            "Remote extractor was blocked by the site. "
            "Your current cookies.txt looks stale or insufficient. "
            "Re-export cookies.txt from a signed-in browser and retry."
        )
    return None


def _extract_remote_format_info(yt_dlp, url: str, temp_dir: str, *, announce: bool = False) -> dict:
    ydl_opts = _base_yt_dlp_opts(temp_dir, announce=announce)
    ydl_opts.update(
        {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
    )
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(url, download=False)
        except Exception as exc:
            friendly = _friendly_remote_extract_error_message(exc)
            if friendly:
                raise RuntimeError(friendly) from exc
            raise


def _ffmpeg_header_blob(headers: dict | None) -> str | None:
    if not headers:
        return None
    lines = [f"{key}: {value}\r\n" for key, value in headers.items() if value is not None]
    return "".join(lines) if lines else None


def _ffmpeg_cookie_blob(cookiejar, url: str) -> str | None:
    try:
        cookies = cookiejar.get_cookies_for_url(url)
    except Exception:
        return None
    if not cookies:
        return None
    return "".join(
        f"{cookie.name}={cookie.value}; path={cookie.path}; domain={cookie.domain};\r\n"
        for cookie in cookies
    )


def _select_requested_formats(info: dict) -> list[dict]:
    requested = info.get("requested_formats")
    if isinstance(requested, list) and requested:
        return [fmt for fmt in requested if isinstance(fmt, dict) and fmt.get("url")]
    if info.get("url"):
        return [info]
    raise RuntimeError("yt-dlp did not return downloadable media URLs for this input range.")


def _build_remote_range_ffmpeg_cmd(
    ffmpeg_path: str,
    selected_formats: list[dict],
    cookiejar,
    out_path: str,
    start_sec: float,
    end_sec: float,
) -> list[str]:
    duration_sec = max(0.001, float(end_sec) - float(start_sec))
    cmd = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-nostats",
    ]
    for fmt in selected_formats:
        url = str(fmt["url"])
        cookie_blob = _ffmpeg_cookie_blob(cookiejar, url)
        if cookie_blob:
            cmd.extend(["-cookies", cookie_blob])
        header_blob = _ffmpeg_header_blob(fmt.get("http_headers"))
        if header_blob:
            cmd.extend(["-headers", header_blob])
        cmd.extend(
            [
                "-ss",
                f"{float(start_sec):.3f}",
                "-t",
                f"{duration_sec:.3f}",
                "-i",
                url,
            ]
        )
    for index, fmt in enumerate(selected_formats):
        stream_number = int(fmt.get("manifest_stream_number") or 0)
        cmd.extend(["-map", f"{index}:{stream_number}"])
    cmd.extend(["-c", "copy", "-movflags", "+faststart", out_path])
    return cmd


def _range_download_format_selector() -> str:
    override = os.environ.get("STREAMCUTER_YTDLP_RANGE_FORMAT", "").strip()
    if override:
        return override
    return (
        "best[protocol*=m3u8_native][height<=1080]"
        "/best[protocol*=m3u8_native]"
        "/best[protocol*=m3u8]"
        "/bestvideo[protocol*=m3u8_native]+bestaudio[protocol*=m3u8_native]"
        "/bestvideo[protocol*=m3u8]+bestaudio[protocol*=m3u8]"
        "/best"
    )


def _range_partial_output_path(out_path: str) -> str:
    path = Path(out_path)
    return str(path.with_name(f"{path.stem}.part{path.suffix}"))


def _is_completed_download(path: str) -> bool:
    candidate = Path(path)
    return candidate.exists() and candidate.stat().st_size > 0


class _QuietYdlLogger:
    def debug(self, _message: str) -> None:
        return None

    def info(self, _message: str) -> None:
        return None

    def warning(self, _message: str) -> None:
        return None

    def error(self, _message: str) -> None:
        return None


def _format_progress_bytes(num_bytes: float) -> str:
    value = max(0.0, float(num_bytes))
    units = ["B", "KiB", "MiB", "GiB"]
    unit_index = 0
    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"


def _pulse_bar(width: int, tick: int) -> str:
    width = max(8, int(width))
    pulse_w = min(5, max(2, width // 4))
    travel = max(1, width - pulse_w)
    step = tick % (travel * 2)
    start = step if step <= travel else (travel * 2 - step)
    chars = [" "] * width
    for index in range(start, min(width, start + pulse_w)):
        chars[index] = "=" if index < start + pulse_w - 1 else ">"
    return "".join(chars)


def _determinate_bar(percent: float, width: int) -> str:
    width = max(8, int(width))
    clamped = max(0.0, min(100.0, float(percent)))
    filled = int(round((clamped / 100.0) * width))
    if filled >= width:
        return "=" * width
    if filled <= 0:
        return ">" + (" " * (width - 1))
    return ("=" * max(0, filled - 1)) + ">" + (" " * (width - filled))


def _format_range_progress_line(
    current_bytes: float,
    *,
    total_bytes: float | None = None,
    fragment_index: int | None = None,
    fragment_count: int | None = None,
    elapsed_sec: float = 0.0,
    tick: int = 0,
    completed: bool = False,
    width: int = 22,
) -> str:
    if total_bytes and total_bytes > 0:
        percent = 100.0 if completed else (float(current_bytes) / max(float(total_bytes), 1.0)) * 100.0
        bar = _determinate_bar(percent, width)
        return (
            f"Range download [{bar}] {int(max(0.0, min(100.0, percent))):3d}% "
            f"{_format_progress_bytes(current_bytes)}/{_format_progress_bytes(total_bytes)}"
        )
    if fragment_count and fragment_count > 0:
        percent = 100.0 if completed else (float(fragment_index or 0) / float(fragment_count)) * 100.0
        bar = _determinate_bar(percent, width)
        shown_index = fragment_count if completed else max(0, int(fragment_index or 0))
        return (
            f"Range download [{bar}] {int(max(0.0, min(100.0, percent))):3d}% "
            f"{shown_index}/{int(fragment_count)} fragments"
        )
    bar = "=" * width if completed else _pulse_bar(width, tick)
    if completed:
        suffix = "done"
    elif current_bytes > 0:
        suffix = _format_progress_bytes(current_bytes)
    else:
        suffix = f"{max(0.0, elapsed_sec):.0f}s"
    return f"Range download [{bar}] {suffix}"


class _RangeProgressDisplay:
    def __init__(self, out_path: str, part_path: str):
        self.out_path = out_path
        self.part_path = part_path
        self.enabled = os.environ.get("STREAMCUTER_LIVE_PROGRESS", "1") != "0"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_line_len = 0
        self._tick = 0
        self._downloaded_bytes = 0.0
        self._total_bytes: float | None = None
        self._fragment_index: int | None = None
        self._fragment_count: int | None = None
        self._completed = False
        self._started_at = time.monotonic()

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

    def update_from_hook(self, data: dict) -> None:
        status = str(data.get("status") or "")
        with self._lock:
            downloaded = data.get("downloaded_bytes")
            if downloaded is not None:
                try:
                    self._downloaded_bytes = max(self._downloaded_bytes, float(downloaded))
                except Exception:
                    pass
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if total is not None:
                try:
                    self._total_bytes = float(total)
                except Exception:
                    pass
            fragment_count = data.get("fragment_count")
            if fragment_count is not None:
                try:
                    self._fragment_count = int(fragment_count)
                except Exception:
                    pass
            fragment_index = data.get("fragment_index")
            if fragment_index is not None:
                try:
                    self._fragment_index = int(fragment_index)
                except Exception:
                    pass
            if status == "finished":
                self._completed = True
                if self._total_bytes is not None:
                    self._downloaded_bytes = max(self._downloaded_bytes, self._total_bytes)
                if self._fragment_count is not None:
                    self._fragment_index = self._fragment_count

    def finish(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._completed = True
            current_size = self._current_file_size()
            self._downloaded_bytes = max(self._downloaded_bytes, current_size)
            if self._total_bytes is not None:
                self._downloaded_bytes = max(self._downloaded_bytes, self._total_bytes)
            if self._fragment_count is not None:
                self._fragment_index = self._fragment_count
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._write_line(self._snapshot_line(completed=True), final=True)

    def fail(self) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._last_line_len:
            self._write_line("", final=True)

    def _render_loop(self) -> None:
        while not self._stop.wait(0.15):
            self._tick += 1
            self._write_line(self._snapshot_line(completed=False), final=False)

    def _snapshot_line(self, *, completed: bool) -> str:
        with self._lock:
            current_bytes = max(self._downloaded_bytes, self._current_file_size())
            return _format_range_progress_line(
                current_bytes,
                total_bytes=self._total_bytes,
                fragment_index=self._fragment_index,
                fragment_count=self._fragment_count,
                elapsed_sec=time.monotonic() - self._started_at,
                tick=self._tick,
                completed=completed,
            )

    def _current_file_size(self) -> float:
        best_size = 0.0
        for candidate in (self.part_path, self.out_path):
            try:
                path = Path(candidate)
                if path.exists():
                    best_size = max(best_size, float(path.stat().st_size))
                parent = path.parent
                pattern = f"{path.name}*"
                if parent.exists():
                    for sibling in parent.glob(pattern):
                        if sibling.is_file():
                            best_size = max(best_size, float(sibling.stat().st_size))
            except OSError:
                continue
        return best_size

    def _write_line(self, line: str, *, final: bool) -> None:
        padded = line.ljust(self._last_line_len)
        sys.stdout.write("\r" + padded)
        if final:
            sys.stdout.write("\n")
            self._last_line_len = 0
        else:
            self._last_line_len = max(self._last_line_len, len(line))
        sys.stdout.flush()


def _range_progress_hook_factory(display: _RangeProgressDisplay) -> Callable[[dict], None]:
    def _hook(data: dict) -> None:
        display.update_from_hook(data)

    return _hook


def _run_ffmpeg_with_progress(
    cmd: list[str],
    out_path: str,
    duration_sec: float,
    stall_timeout_sec: float = 45.0,
) -> None:
    progress_mark = -1
    last_progress_sec = 0.0
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    output_tail: list[str] = []
    output_queue: queue.Queue[object] = queue.Queue()
    stream_end = object()

    def _reader() -> None:
        assert process.stdout is not None
        try:
            for raw_line in process.stdout:
                output_queue.put(raw_line)
        finally:
            output_queue.put(stream_end)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    last_output_at = time.monotonic()
    last_progress_at = last_output_at
    last_growth_at = last_output_at
    last_size = Path(out_path).stat().st_size if Path(out_path).exists() else 0
    stream_closed = False
    stalled_reason: str | None = None
    try:
        while True:
            now = time.monotonic()
            try:
                item = output_queue.get(timeout=1.0)
            except queue.Empty:
                item = None

            if item is stream_end:
                stream_closed = True
            elif isinstance(item, str):
                line = item.strip()
                if line:
                    last_output_at = now
                    if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
                        try:
                            out_time_raw = int(line.split("=", 1)[1])
                        except ValueError:
                            out_time_raw = 0
                        current_sec = max(0.0, out_time_raw / 1_000_000.0)
                        last_progress_sec = current_sec
                        last_progress_at = now
                        percent = min(100, int((current_sec / max(duration_sec, 0.001)) * 100))
                        if percent >= progress_mark + 5:
                            progress_mark = percent
                            console.print(
                                f"[dim]Range download progress: {percent}% "
                                f"({current_sec:.1f}s / {duration_sec:.1f}s)[/dim]"
                            )
                    elif line == "progress=end":
                        progress_mark = 100
                        last_progress_sec = duration_sec
                        last_progress_at = now
                        console.print(
                            f"[dim]Range download progress: 100% "
                            f"({duration_sec:.1f}s / {duration_sec:.1f}s)[/dim]"
                        )
                    else:
                        output_tail.append(line)
                        output_tail = output_tail[-30:]

            current_size = Path(out_path).stat().st_size if Path(out_path).exists() else 0
            if current_size > last_size:
                last_size = current_size
                last_growth_at = now

            if process.poll() is None:
                last_motion_at = max(last_progress_at, last_growth_at)
                if now - last_motion_at > stall_timeout_sec:
                    stalled_reason = (
                        "Selected-range download stopped making progress. "
                        f"No new ffmpeg output or file growth was detected for {int(stall_timeout_sec)}s "
                        f"at {last_progress_sec:.1f}s / {duration_sec:.1f}s."
                    )
                    process.kill()
                    break
            elif stream_closed and output_queue.empty():
                break
    finally:
        return_code = process.wait()
        reader.join(timeout=2.0)
    if stalled_reason:
        raise RuntimeError(stalled_reason)
    if return_code != 0 or not Path(out_path).exists() or Path(out_path).stat().st_size <= 0:
        tail = "\n".join(output_tail[-20:])
        raise RuntimeError(
            "ffmpeg failed while downloading the selected remote range. "
            f"ffmpeg returned {return_code}: {tail}"
        )


def _download_remote_range_with_yt_dlp(yt_dlp, url: str, temp_dir: str, start_sec: float, end_sec: float) -> str:
    console.print("[dim]Range stage: resolve formats[/dim]")
    info = _extract_remote_format_info(yt_dlp, url, temp_dir, announce=False)
    out_ext = str(info.get("ext") or "mp4")
    out_path = _range_output_path(temp_dir, str(info.get("id") or "video"), start_sec, end_sec, out_ext)
    part_path = _range_partial_output_path(out_path)
    if _is_completed_download(out_path):
        console.print(f"[green]Using existing selected-range download: {out_path}[/green]")
        return out_path
    if Path(out_path).exists():
        Path(out_path).unlink(missing_ok=True)
    if Path(part_path).exists() and Path(part_path).stat().st_size <= 0:
        console.print(f"[dim]Removing stale partial range download: {part_path}[/dim]")
        Path(part_path).unlink(missing_ok=True)

    ydl_opts = _base_yt_dlp_opts(temp_dir, _range_output_template(temp_dir, start_sec, end_sec))
    ydl_opts["format"] = _range_download_format_selector()
    ydl_opts["download_ranges"] = _download_ranges_callback(start_sec, end_sec)
    ydl_opts["force_keyframes_at_cuts"] = False
    ydl_opts["quiet"] = True
    ydl_opts["no_warnings"] = True
    ydl_opts["noprogress"] = True
    ydl_opts["logger"] = _QuietYdlLogger()
    progress_display = _RangeProgressDisplay(out_path, part_path)
    ydl_opts["progress_hooks"] = [_range_progress_hook_factory(progress_display)]
    console.print("[dim]Range stage: start yt-dlp partial download[/dim]")
    console.print(f"[dim]Range destination: {out_path}[/dim]")
    progress_display.start()
    try:
        _download_with_retry(yt_dlp, url, ydl_opts, temp_dir)
    except Exception:
        progress_display.fail()
        raise
    else:
        progress_display.finish()
    console.print("[dim]Range stage: finalize[/dim]")
    if not _is_completed_download(out_path):
        raise RuntimeError("Selected-range download did not produce a complete file.")
    console.print("[dim]Range stage: done[/dim]")
    console.print(f"[green]Downloaded selected range: {out_path}[/green]")
    return out_path


def _download_with_retry(yt_dlp, url: str, ydl_opts: dict, temp_dir: str) -> str:
    try:
        return _download_with_yt_dlp(yt_dlp, url, ydl_opts, temp_dir)
    except Exception as e:
        if not _looks_like_curl_cert_error(e):
            raise
        console.print(
            "[yellow]yt-dlp/curl could not use the certificate bundle. "
            "Retrying this download with certificate checks disabled.[/yellow]"
        )
        retry_opts = dict(ydl_opts)
        retry_opts["nocheckcertificate"] = True
        return _download_with_yt_dlp(yt_dlp, url, retry_opts, temp_dir)


def _resolve_url_metadata_with_yt_dlp(yt_dlp, url: str, temp_dir: str, *, announce: bool = False) -> InputMetadata:
    ydl_opts = _base_yt_dlp_opts(temp_dir, announce=announce)
    ydl_opts.update(
        {
            "skip_download": True,
            "extract_flat": False,
            "quiet": True,
            "no_warnings": True,
            "logger": _QuietYdlLogger(),
        }
    )
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as exc:
            friendly = _friendly_remote_extract_error_message(exc)
            if friendly:
                raise RuntimeError(friendly) from exc
            raise

    duration_sec = float(info.get("duration") or 0.0)
    if duration_sec <= 0:
        raise RuntimeError("Could not determine remote video duration for input range selection.")
    title = str(info.get("title") or info.get("id") or url)
    return InputMetadata(
        source=url,
        duration_sec=duration_sec,
        display_name=title,
        is_remote=True,
    )


def resolve_input_metadata(input_str: str, temp_dir: str = "temp", *, announce: bool = False) -> InputMetadata:
    if is_url(input_str):
        try:
            import yt_dlp
        except ImportError as e:
            raise RuntimeError(
                "yt-dlp is not installed. Install dependencies (pip install -r requirements.txt) "
                "or use a local video file."
            ) from e

        ca_bundle = configure_yt_dlp_tls()
        return _resolve_url_metadata_with_yt_dlp(yt_dlp, input_str, temp_dir, announce=announce)

    p = Path(input_str)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {input_str}")

    from app.probe import probe_video

    info = probe_video(str(p.resolve()))
    return InputMetadata(
        source=str(p.resolve()),
        duration_sec=info.duration_sec,
        display_name=p.name,
        is_remote=False,
    )


def _normalize_selected_range(
    duration_sec: float,
    input_start_sec: Optional[float],
    input_end_sec: Optional[float],
) -> Optional[tuple[float, float]]:
    duration_sec = float(duration_sec or 0.0)
    if duration_sec <= 0:
        if input_start_sec is None and input_end_sec is None:
            return None
        raise RuntimeError("Input duration is unknown; cannot validate the selected range.")

    start_sec = 0.0 if input_start_sec is None else float(input_start_sec)
    end_sec = duration_sec if input_end_sec is None else float(input_end_sec)

    if start_sec < 0:
        raise RuntimeError("Input range start must be >= 0.")
    if end_sec <= start_sec:
        raise RuntimeError("Input range end must be greater than start.")
    if start_sec >= duration_sec:
        raise RuntimeError(
            f"Input range start {start_sec:.3f}s is outside the source duration {duration_sec:.3f}s."
        )
    if end_sec > duration_sec + 0.01:
        raise RuntimeError(
            f"Input range end {end_sec:.3f}s is beyond the source duration {duration_sec:.3f}s."
        )

    end_sec = min(end_sec, duration_sec)
    if start_sec <= 0.0 and abs(end_sec - duration_sec) <= 0.01:
        return None
    return start_sec, end_sec


def _download_ranges_callback(start_sec: float, end_sec: float):
    from yt_dlp.utils import download_range_func

    return download_range_func(
        chapters=None,
        ranges=[(float(start_sec), float(end_sec))],
        from_info=False,
    )


def download_video(
    url: str,
    temp_dir: str,
    input_start_sec: Optional[float] = None,
    input_end_sec: Optional[float] = None,
    metadata: Optional[InputMetadata] = None,
) -> str:
    """Download video via yt-dlp into temp_dir. Returns path to downloaded file."""
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is not installed. Install dependencies (pip install -r requirements.txt) "
            "or use a local video file."
        ) from e

    configure_yt_dlp_tls()

    selected_range = None
    if input_start_sec is not None or input_end_sec is not None:
        metadata = metadata or _resolve_url_metadata_with_yt_dlp(yt_dlp, url, temp_dir, announce=False)
        selected_range = _normalize_selected_range(
            metadata.duration_sec,
            input_start_sec,
            input_end_sec,
        )
        if selected_range is not None:
            start_sec, end_sec = selected_range
            console.print(
                f"[cyan]Downloading selected range: {start_sec:.1f}s - {end_sec:.1f}s[/cyan]"
            )
            return _download_remote_range_with_yt_dlp(yt_dlp, url, temp_dir, start_sec, end_sec)

    ydl_opts = _base_yt_dlp_opts(temp_dir)
    console.print(f"[cyan]Downloading from: {url}[/cyan]")
    return _download_with_retry(yt_dlp, url, ydl_opts, temp_dir)


def _trim_local_video(
    input_path: str,
    temp_dir: str,
    start_sec: float,
    end_sec: float,
) -> str:
    source = Path(input_path).resolve()
    suffix = source.suffix or ".mp4"
    out_path = Path(temp_dir) / (
        f"{safe_filename(source.stem)}__trim_{int(round(start_sec * 1000))}_{int(round(end_sec * 1000))}{suffix}"
    )
    if out_path.exists():
        console.print(f"[green]Using existing trimmed input: {out_path}[/green]")
        return str(out_path)

    cmd = [
        ffmpeg_exe(),
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-to",
        f"{end_sec:.3f}",
        "-i",
        str(source),
        "-map",
        "0",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-reset_timestamps",
        "1",
        str(out_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            "Failed to trim the selected input range. "
            f"ffmpeg returned {result.returncode}: {result.stderr[-1200:]}"
        )
    console.print(f"[green]Trimmed input range: {out_path}[/green]")
    return str(out_path)


def resolve_input(
    input_str: str,
    temp_dir: str,
    input_start_sec: Optional[float] = None,
    input_end_sec: Optional[float] = None,
) -> ResolvedInput:
    """Resolve input to a local working file path and preserve source metadata."""
    if is_url(input_str):
        metadata = None
        selected_range = None
        if input_start_sec is not None or input_end_sec is not None:
            metadata = resolve_input_metadata(input_str, temp_dir=temp_dir, announce=False)
            selected_range = _normalize_selected_range(
                metadata.duration_sec,
                input_start_sec,
                input_end_sec,
            )
        working_path = download_video(
            input_str,
            temp_dir,
            input_start_sec=input_start_sec,
            input_end_sec=input_end_sec,
            metadata=metadata,
        )
        return ResolvedInput(
            source=input_str,
            working_path=working_path,
            delete_target=working_path,
            duration_sec=metadata.duration_sec if metadata is not None else None,
            is_remote=True,
            selected_range=selected_range,
        )

    p = Path(input_str)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {input_str}")
    resolved = str(p.resolve())
    metadata = None
    selected_range = None
    working_path = resolved
    if input_start_sec is not None or input_end_sec is not None:
        metadata = resolve_input_metadata(resolved, temp_dir=temp_dir, announce=False)
        selected_range = _normalize_selected_range(
            metadata.duration_sec,
            input_start_sec,
            input_end_sec,
        )
        if selected_range is not None:
            start_sec, end_sec = selected_range
            working_path = _trim_local_video(resolved, temp_dir, start_sec, end_sec)
    return ResolvedInput(
        source=resolved,
        working_path=working_path,
        delete_target=resolved,
        duration_sec=metadata.duration_sec if metadata is not None else None,
        is_remote=False,
        selected_range=selected_range,
    )
