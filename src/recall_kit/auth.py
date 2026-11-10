"""Scoped API tokens for the HTTP transport.

Tokens live only in the environment, and only as SHA-256 hashes:

    RECALL_TOKENS="laptop:read,write:<sha256>;cron:read:<sha256>;admin:read,write,forget,admin:<sha256>"

`rk token new --name laptop --scopes read,write` prints a fresh secret (give it to the client)
and the line to add to RECALL_TOKENS on the server. Revoking = delete the line + restart.

Scopes:  read   recall, history, resume, brief, list
         write  remember, correct, project updates
         forget hard deletion
         admin  approve quarantined memories, reindex
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass

SCOPES = ("read", "write", "forget", "admin")


class AuthError(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    name: str
    scopes: frozenset[str]


LOCAL = Principal("local-stdio", frozenset(SCOPES))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(name: str, scopes: list[str]) -> tuple[str, str]:
    bad = [s for s in scopes if s not in SCOPES]
    if bad or not scopes:
        raise ValueError(f"unknown scopes {bad}; choose from {SCOPES}")
    if not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("token name: letters, digits, - and _ only")
    secret = "rk_" + secrets.token_urlsafe(32)
    return secret, f"{name}:{','.join(scopes)}:{hash_token(secret)}"


def parse_tokens(spec: str | None = None) -> dict[str, Principal]:
    spec = os.environ.get("RECALL_TOKENS", "") if spec is None else spec
    table: dict[str, Principal] = {}
    for entry in filter(None, (e.strip() for e in spec.split(";"))):
        name, scopes, digest = entry.split(":")
        table[digest.lower()] = Principal(name, frozenset(s for s in scopes.split(",") if s in SCOPES))
    return table


def authenticate(headers: Mapping[str, str] | None, table: dict[str, Principal]) -> Principal:
    if headers is None:  # stdio: the client launched us as a local subprocess
        return LOCAL
    value = headers.get("authorization") or headers.get("Authorization") or ""
    if not value.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    digest = hash_token(value[7:].strip())
    for known, principal in table.items():
        if hmac.compare_digest(known, digest):
            return principal
    raise AuthError("invalid or revoked token")


def require(principal: Principal, scope: str) -> None:
    if scope not in principal.scopes:
        raise AuthError(f"token '{principal.name}' lacks the '{scope}' scope")
