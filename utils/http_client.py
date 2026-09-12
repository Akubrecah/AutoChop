"""
AutoChop AI Studio - Standard Library HTTP Client
Provides zero-dependency HTTP client utilities using urllib.request.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("autochop.utils.http_client")


@dataclass
class HttpResponse:
    """Standardized HTTP response object."""
    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> dict[str, Any]:
        if not self.content:
            return {}
        return json.loads(self.text)


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    data: bytes | Any | None = None,
    json_data: Any | None = None,
    files: dict[str, bytes] | None = None,
    form_data: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> HttpResponse:
    """
    Executes an HTTP request using urllib.request.
    Catches HTTPError to preserve status_code, headers, and error response bodies.
    """
    final_url = url
    if params:
        query_string = urllib.parse.urlencode(params)
        sep = "&" if "?" in final_url else "?"
        final_url = f"{final_url}{sep}{query_string}"

    req_headers = dict(headers or {})

    req_body: bytes | None = None

    if json_data is not None:
        req_body = json.dumps(json_data).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json; charset=UTF-8")
    elif files is not None or form_data is not None:
        # Build multipart/form-data
        boundary = "----AutoChopBoundary7MA4YWxkTrZu0gW"
        req_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        body_parts: list[bytes] = []

        if form_data:
            for k, v in form_data.items():
                body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
                body_parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
                body_parts.append(f"{v}\r\n".encode("utf-8"))

        if files:
            for field_name, file_bytes in files.items():
                body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
                body_parts.append(
                    f'Content-Disposition: form-data; name="{field_name}"; filename="blob"\r\n'.encode("utf-8")
                )
                body_parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
                body_parts.append(file_bytes)
                body_parts.append(b"\r\n")

        body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        req_body = b"".join(body_parts)
    elif isinstance(data, bytes):
        req_body = data
    elif isinstance(data, str):
        req_body = data.encode("utf-8")
    elif data is not None:
        # File-like object
        if hasattr(data, "read"):
            req_body = data.read()
            if isinstance(req_body, str):
                req_body = req_body.encode("utf-8")

    req = urllib.request.Request(
        url=final_url,
        data=req_body,
        headers=req_headers,
        method=method.upper(),
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_bytes = resp.read()
            resp_headers = dict(resp.headers)
            return HttpResponse(
                status_code=resp.status,
                headers=resp_headers,
                content=resp_bytes,
            )
    except urllib.error.HTTPError as http_err:
        err_bytes = http_err.read()
        err_headers = dict(http_err.headers) if http_err.headers else {}
        return HttpResponse(
            status_code=http_err.code,
            headers=err_headers,
            content=err_bytes,
        )
    except urllib.error.URLError as url_err:
        raise RuntimeError(f"Network connection failed: {url_err.reason}") from url_err


def http_get(url: str, **kwargs: Any) -> HttpResponse:
    return http_request("GET", url, **kwargs)


def http_post(url: str, **kwargs: Any) -> HttpResponse:
    return http_request("POST", url, **kwargs)


def http_put(url: str, **kwargs: Any) -> HttpResponse:
    return http_request("PUT", url, **kwargs)
