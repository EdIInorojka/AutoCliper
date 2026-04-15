"""Video downloader using yt-dlp."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.utils.console import get_console

console = get_console()


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
        or "cafile:" in text and "certifi" in text
    )


def _download_with_yt_dlp(yt_dlp, url: str, ydl_opts: dict, temp_dir: str) -> str:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # yt-dlp merge_output_format may produce .mp4
        # Find the actual output file
        if "requested_downloads" in info and info["requested_downloads"]:
            for dl in info["requested_downloads"]:
                if dl.get("_filename"):
                    fn = dl["_filename"]
                    if os.path.exists(fn):
                        console.print(f"[green]Downloaded: {fn}[/green]")
                        return fn
        # Fallback: search temp_dir for most recent mp4
        p = Path(temp_dir)
        mp4s = list(p.glob("*.mp4"))
        if mp4s:
            mp4s.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            console.print(f"[green]Downloaded: {mp4s[0]}[/green]")
            return str(mp4s[0])

    raise RuntimeError(f"yt-dlp did not produce a file for {url}")


def download_video(url: str, temp_dir: str) -> str:
    """Download video via yt-dlp into temp_dir. Returns path to downloaded file."""
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is not installed. Install dependencies (pip install -r requirements.txt) "
            "or use a local video file."
        ) from e

    out_tmpl = os.path.join(temp_dir, "%(id)s.%(ext)s")
    ca_bundle = configure_yt_dlp_tls()
    if ca_bundle:
        console.print(f"[dim]Using CA bundle: {ca_bundle}[/dim]")

    ydl_opts = {
        "outtmpl": out_tmpl,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
        "retries": 3,
        "fragment_retries": 3,
    }

    console.print(f"[cyan]Downloading from: {url}[/cyan]")

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

    raise RuntimeError(f"yt-dlp did not produce a file for {url}")


def resolve_input(input_str: str, temp_dir: str) -> str:
    """Resolve input to a local file path. Downloads if URL."""
    if is_url(input_str):
        return download_video(input_str, temp_dir)
    else:
        p = Path(input_str)
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {input_str}")
        return str(p.resolve())
