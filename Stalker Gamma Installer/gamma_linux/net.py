"""HTTP helpers: resumable downloads with retries, no third-party modules."""

import http.client
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from . import VERSION
from .common import Cancelled, events, is_no_space, log

USER_AGENT = f"gamma-linux-launcher/{VERSION}"
CHUNK = 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener()
_opener_noredirect = urllib.request.build_opener(_NoRedirect)


def open_url(url: str, headers: dict = None, redirect: bool = True, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return (_opener if redirect else _opener_noredirect).open(req, timeout=timeout)


def get_text(url: str) -> str:
    with open_url(url) as r:
        return r.read().decode("utf-8", "replace")


def get_redirect(url: str) -> str:
    """Return where `url` redirects to (without following it)."""
    try:
        with open_url(url, redirect=False) as r:
            return r.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            return urljoin(url, e.headers["Location"])
        raise


def _filename_from_headers(headers) -> str:
    cd = headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    return unquote(m.group(1)).strip() if m else ""


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name or "download.bin"


def download(url: str, dest_dir: Path, filename: str = None, on_bytes=None) -> Path:
    """Download `url` into `dest_dir`, resuming a previous partial download."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / ".download.part"
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    try:
        resp = open_url(url, headers=headers, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:
            part.unlink()
            return download(url, dest_dir, filename, on_bytes)
        raise
    with resp:
        if have and resp.status != 206:
            have = 0
        length = resp.headers.get("Content-Length")
        total = int(length) + have if length and length.isdigit() else None
        name = filename or _filename_from_headers(resp.headers) or os.path.basename(unquote(urlparse(resp.geturl()).path))
        with open(part, "ab" if have else "wb") as f:
            while True:
                events.check_cancel()
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                if on_bytes:
                    on_bytes(len(chunk))
    size = part.stat().st_size
    if total is not None and size != total:
        raise IOError(f"incomplete download ({size} of {total} bytes)")
    final = dest_dir / safe_filename(name)
    os.replace(part, final)
    return final


RETRY_WAITS = (5, 20, 60)


def with_retries(what: str, fn, waits=RETRY_WAITS):
    """Run fn(), retrying network hiccups. Missing files and blocks are not retried forever."""
    for attempt in range(len(waits) + 1):
        events.check_cancel()
        try:
            return fn()
        except Cancelled:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (404, 410) or attempt == len(waits):
                raise
            wait = 90 if e.code == 429 else waits[attempt]
            if e.code == 403 and attempt >= 1:
                raise
            log(f"    {what}: HTTP {e.code}, retrying in {wait}s")
        except (urllib.error.URLError, http.client.HTTPException, socket.timeout,
                ConnectionError, TimeoutError, IOError) as e:
            if is_no_space(e) or attempt == len(waits):
                raise
            wait = waits[attempt]
            log(f"    {what}: {e}, retrying in {wait}s")
        for _ in range(wait):
            events.check_cancel()
            time.sleep(1)
