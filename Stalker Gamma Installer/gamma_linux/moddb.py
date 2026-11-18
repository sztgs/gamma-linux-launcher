"""ModDB: turn an `/addons/start/<id>` link into a real file URL, read MD5 from the addon page.

ModDB pages are requested one at a time with a pause in between so the
launcher stays polite; the actual file transfers (CDN mirrors) run in parallel.
"""

import html
import re
import threading
import time

from . import net

BASE = "https://www.moddb.com"
_page_lock = threading.Lock()
_last_request = [0.0]
PAGE_INTERVAL = 1.5


def _page(url: str, redirect_only: bool = False) -> str:
    with _page_lock:
        wait = _last_request[0] + PAGE_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return net.get_redirect(url) if redirect_only else net.get_text(url)
        finally:
            _last_request[0] = time.monotonic()


def file_id(url: str):
    m = re.search(r"/(?:addons|downloads)/start/(\d+)", url)
    return m.group(1) if m else None


def addon_info(info_url: str) -> dict:
    """Filename and MD5 listed on the addon page (best effort)."""
    text = _page(info_url)
    result = {}
    for key, label in (("filename", "Filename"), ("md5", "MD5 Hash")):
        m = re.search(rf"<h5>\s*{label}\s*</h5>\s*<span[^>]*>\s*([^<]+?)\s*</span>", text, re.I)
        if m:
            result[key] = html.unescape(m.group(1)).strip()
    if "md5" in result and not re.fullmatch(r"[0-9a-fA-F]{32}", result["md5"]):
        del result["md5"]
    return result


def _mirror_links(page_url: str, fid: str) -> list:
    text = html.unescape(_page(page_url))
    links = []
    for m in re.finditer(rf"(?:https?://www\.moddb\.com)?(/(?:downloads|addons)/mirror/{fid}/[^\"'\s<>]+)", text):
        link = BASE + m.group(1)
        if link not in links:
            links.append(link)
    return links


def mirror_links(start_url: str) -> list:
    fid = file_id(start_url)
    links = _mirror_links(start_url, fid)
    if len(links) < 2:
        try:
            for link in _mirror_links(start_url.rstrip("/") + "/all", fid):
                if link not in links:
                    links.append(link)
        except Exception:
            pass
    return links


def resolve_mirror(mirror_url: str) -> str:
    return _page(mirror_url, redirect_only=True)
