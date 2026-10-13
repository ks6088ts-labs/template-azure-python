import base64
import binascii
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import HTTPException, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "cache-control": "no-store",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                docs = scope.get("path") in {"/docs", "/redoc"}
                policy = (
                    "default-src 'none'; frame-ancestors 'none'; "
                    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                    "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'"
                    if docs
                    else "default-src 'none'; frame-ancestors 'none'"
                )
                present = {key.lower() for key, _value in headers}
                configured = {**SECURITY_HEADERS, "content-security-policy": policy}
                headers.extend(
                    (key.encode(), value.encode()) for key, value in configured.items() if key.encode() not in present
                )
                if scope.get("scheme") == "https" and b"strict-transport-security" not in present:
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _principal(header: str) -> Mapping[str, Any]:
    if len(header) > 16384:
        raise ValueError("Principal is too large")
    payload = json.loads(base64.b64decode(header, validate=True))
    if not isinstance(payload, dict):
        raise ValueError("Principal must be an object")
    if not isinstance(payload.get("auth_typ"), str) or not payload["auth_typ"].strip():
        raise ValueError("Principal has no authentication type")
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("Principal has no claims")
    if any(
        not isinstance(claim, dict) or not isinstance(claim.get("typ"), str) or not isinstance(claim.get("val"), str)
        for claim in claims
    ):
        raise ValueError("Principal has malformed claims")
    identity_types = {
        "sub",
        "oid",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
        "http://schemas.microsoft.com/identity/claims/objectidentifier",
    }
    if not any(claim["typ"] in identity_types and claim["val"].strip() for claim in claims):
        raise ValueError("Principal has no identity")
    return payload


def authentication_dependency(mode: str, required_role: str | None) -> Callable[[Request], Awaitable[None]]:
    async def authenticate(request: Request) -> None:
        if mode == "none":
            return
        # This is a platform assertion, not token verification. Easy Auth must protect
        # the origin and strip caller-supplied principal headers before forwarding.
        headers = request.headers.getlist("x-ms-client-principal")
        if len(headers) != 1:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            principal = _principal(headers[0])
        except (ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error, RecursionError):
            raise HTTPException(status_code=401, detail="Authentication required") from None
        if required_role:
            role_type = principal.get("role_typ", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role")
            if not isinstance(role_type, str) or not any(
                claim["typ"] == role_type and claim["val"] == required_role for claim in principal["claims"]
            ):
                raise HTTPException(status_code=403, detail="Required role is missing")

    return authenticate
