"""
Minimal HTTPS helper (stdlib only) for weather, GitHub, uploads and scrapers.

Every call runs in a worker thread, is size-bounded, uses a timeout and refuses
non-HTTPS URLs and hosts outside an optional allowlist (including after
redirects), so user-supplied links cannot be turned into requests to internal
services.
"""

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Dict, Iterable, Optional, Tuple

USER_AGENT = "Mozilla/5.0 (compatible; Reze/2.x; +https://github.com/UnchartedAli/Reze)"
MAX_TEXT_BYTES = 2 * 1024 * 1024


class HttpError(Exception):
    """User-presentable network failure."""


def host_allowed(url: str, allowed: Optional[Iterable[str]]) -> bool:
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    if not allowed:
        return True
    host = parts.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in (a.lower() for a in allowed))


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    allowed: Optional[Iterable[str]] = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_allowed(newurl, self.allowed):
            raise HttpError("The server redirected to a host that is not allowed.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(allowed: Optional[Iterable[str]]):
    handler = _CheckedRedirect()
    handler.allowed = allowed
    return urllib.request.build_opener(handler)


def _request_sync(url, *, data=None, headers=None, timeout=15, allowed=None, max_bytes=MAX_TEXT_BYTES,
                  method=None, accept_errors=False):
    if not host_allowed(url, allowed):
        raise HttpError("Only https:// links to supported sites are allowed.")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with _opener(allowed).open(req, timeout=timeout) as resp:
            final = resp.geturl()
            if not host_allowed(final, allowed):
                raise HttpError("The final address is not an allowed host.")
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise HttpError("The response was larger than the allowed limit.")
            return resp.status, final, body
    except HttpError:
        raise
    except urllib.error.HTTPError as exc:
        if accept_errors:  # e.g. the Telegram Bot API explains 4xx errors in the JSON body
            return exc.code, url, exc.read(max_bytes)
        raise HttpError(f"The server answered HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HttpError(f"Network error: {getattr(exc, 'reason', exc)}") from exc


async def get_text(url: str, **kw) -> Tuple[str, str]:
    """Return ``(final_url, text)``."""
    _, final, body = await asyncio.to_thread(_request_sync, url, **kw)
    return final, body.decode("utf-8", errors="replace")


async def get_json(url: str, params: Optional[Dict[str, str]] = None, **kw):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    _, body = await get_text(url, **kw)
    try:
        return json.loads(body)
    except ValueError as exc:
        raise HttpError("The service returned invalid JSON.") from exc


def _download_sync(url, path, max_bytes, allowed, headers, timeout):
    if not host_allowed(url, allowed):
        raise HttpError("Only https:// links to supported sites are allowed.")
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with _opener(allowed).open(req, timeout=timeout) as resp:
            if not host_allowed(resp.geturl(), allowed):
                raise HttpError("The final address is not an allowed host.")
            declared = int(resp.headers.get("Content-Length") or 0)
            if declared and declared > max_bytes:
                raise HttpError(f"The file is {declared / 1048576:.1f} MB; the limit is {max_bytes // 1048576} MB.")
            written = 0
            with open(path, "wb") as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise HttpError(f"The file exceeds the {max_bytes // 1048576} MB limit.")
                    out.write(chunk)
            return written, resp.headers.get("Content-Type", "")
    except HttpError:
        _silent_remove(path)
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        _silent_remove(path)
        raise HttpError(f"Download failed: {getattr(exc, 'reason', exc)}") from exc


def _silent_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


async def download(url: str, path: str, *, max_bytes: int, allowed=None, headers=None, timeout=60):
    return await asyncio.to_thread(_download_sync, url, path, max_bytes, allowed, headers, timeout)


def multipart(fields: Dict[str, str], file_field: str, filename: str, content: bytes) -> Tuple[bytes, str]:
    """Build a multipart/form-data body. Returns ``(body, content_type)``."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
    parts.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{safe_name}"\r\n'
         "Content-Type: application/octet-stream\r\n\r\n").encode()
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


async def post_multipart(url, fields, file_field, filename, content, *, allowed=None, timeout=120, max_bytes=65536):
    body, ctype = multipart(fields, file_field, filename, content)
    _, _, resp = await asyncio.to_thread(
        _request_sync, url, data=body, headers={"Content-Type": ctype},
        timeout=timeout, allowed=allowed, max_bytes=max_bytes, method="POST",
    )
    return resp.decode("utf-8", errors="replace").strip()


def multipart_files(fields: Dict[str, str], files: Dict[str, Tuple[str, bytes, str]]) -> Tuple[bytes, str]:
    """multipart/form-data with several files: ``files = {field: (filename, content, mime)}``."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, content, mime) in files.items():
        safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{safe}"\r\n'
                      f"Content-Type: {mime}\r\n\r\n").encode())
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


async def post_form(url: str, fields: Dict[str, str], files: Optional[Dict[str, Tuple[str, bytes, str]]] = None, *,
                    allowed=None, timeout: int = 60, max_bytes: int = 1024 * 1024) -> Tuple[int, bytes]:
    """POST form fields (+ optional files). Returns ``(status, body)`` even for 4xx answers."""
    if files:
        body, ctype = multipart_files(fields, files)
    else:
        body, ctype = urllib.parse.urlencode(fields).encode(), "application/x-www-form-urlencoded"
    status, _, raw = await asyncio.to_thread(
        _request_sync, url, data=body, headers={"Content-Type": ctype}, timeout=timeout,
        allowed=allowed, max_bytes=max_bytes, method="POST", accept_errors=True,
    )
    return status, raw
