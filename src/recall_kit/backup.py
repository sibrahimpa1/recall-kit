"""Encrypted backups with a verified restore.

Format (`.rkb`): MAGIC | salt(16) | nonce(12) | AES-256-GCM(tar.gz of the store)
Key = scrypt(passphrase, salt). The passphrase comes from RECALL_BACKUP_PASSPHRASE only.
The archive contains the markdown files, project files, audit log and the full .git history;
the SQLite index is left out and rebuilt on restore (it is derived data).
A manifest of sha256 hashes rides inside the archive and is checked after every restore.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import shutil
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"RKBACKUP1"
EXCLUDE = {"index.sqlite", "index.sqlite-wal", "index.sqlite-shm", ".lock"}


class BackupError(RuntimeError):
    pass


def _passphrase(passphrase: str | None) -> bytes:
    value = passphrase or os.environ.get("RECALL_BACKUP_PASSPHRASE")
    if not value or len(value) < 12:
        raise BackupError("set RECALL_BACKUP_PASSPHRASE (12+ characters) to create or restore backups")
    return value.encode()


def _key(passphrase: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase)


def _files(home: Path) -> list[Path]:
    out = []
    for p in sorted(home.rglob("*")):
        if p.is_file() and p.name not in EXCLUDE and not p.name.endswith(".tmp"):
            out.append(p)
    return out


def _manifest(home: Path) -> dict[str, str]:
    return {
        str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in _files(home)
        if ".git" not in p.relative_to(home).parts
    }


def create(home: Path, out_dir: Path, *, passphrase: str | None = None) -> dict[str, Any]:
    pw = _passphrase(passphrase)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(home)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in _files(home):
            tar.add(p, arcname=str(p.relative_to(home)))
        data = json.dumps({"created": datetime.now(UTC).isoformat(), "files": manifest}).encode()
        info = tarfile.TarInfo("MANIFEST.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    blob = MAGIC + salt + nonce + AESGCM(_key(pw, salt)).encrypt(nonce, buf.getvalue(), MAGIC)
    name = f"recall-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}.rkb"
    path = out_dir / name
    path.write_bytes(blob)
    os.chmod(path, 0o600)
    return {"path": str(path), "bytes": len(blob), "files": len(manifest)}


def _decrypt(path: Path, pw: bytes) -> bytes:
    blob = path.read_bytes()
    if not blob.startswith(MAGIC):
        raise BackupError(f"{path} is not a recall-kit backup")
    salt = blob[len(MAGIC) : len(MAGIC) + 16]
    nonce = blob[len(MAGIC) + 16 : len(MAGIC) + 28]
    try:
        return AESGCM(_key(pw, salt)).decrypt(nonce, blob[len(MAGIC) + 28 :], MAGIC)
    except InvalidTag as exc:
        raise BackupError("wrong passphrase or the backup was modified") from exc


def restore(
    path: Path, target: Path, *, passphrase: str | None = None, force: bool = False
) -> dict[str, Any]:
    pw = _passphrase(passphrase)
    if target.exists() and any(target.iterdir()):
        if not force:
            raise BackupError(f"{target} is not empty; pass --force to replace it")
        shutil.rmtree(target)
    plain = _decrypt(path, pw)
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
        tar.extractall(target, filter="data")
    manifest = json.loads((target / "MANIFEST.json").read_text())
    (target / "MANIFEST.json").unlink()
    actual = _manifest(target)
    bad = sorted(k for k, v in manifest["files"].items() if actual.get(k) != v)
    if bad:
        raise BackupError(f"restore verification failed for {bad}")
    from .store import MemoryStore  # late import: the store rebuilds the index on open

    store = MemoryStore(target)
    doctor = store.doctor()
    stats = store.stats()
    store.close()
    return {
        "restored_to": str(target),
        "files_verified": len(manifest["files"]),
        "backup_created": manifest["created"],
        "active_memories": stats["active"],
        "doctor_ok": doctor["ok"],
    }


def verify(path: Path, *, passphrase: str | None = None) -> dict[str, Any]:
    """Restore into a throwaway directory and run the store's own consistency check."""
    with tempfile.TemporaryDirectory(prefix="recall-verify-") as tmp:
        return restore(path, Path(tmp) / "store", passphrase=passphrase)


def prune(out_dir: Path, keep: int) -> list[str]:
    files = sorted(out_dir.glob("recall-*.rkb"))
    removed = files[:-keep] if keep > 0 else []
    for p in removed:
        p.unlink()
    return [str(p) for p in removed]
