"""Backup offline-safe de audit/board/state para Ciel (Fase 14 / F17).

Volca los tres volúmenes de estado a un directorio local (JSON/SQLite/S3
opcional) sin requerir red. Diseñado para correr como CronJob en k8s.

Componentes:
* audit: JSONL particionado por tenant/session (se copia el árbol de archivos).
* board: SQLite (se copia el .db; opcionalmente vía sqlite3 .backup).
* state: SQLite local del StateBackend (se copia el .sqlite) o se omite si es
  Postgres (en ese caso el DBA debe usar pg_dump).

Uso:
    uv run python scripts/backup_state.py \
        --audit-dir /var/lib/ciel/audit \
        --board-db /var/lib/ciel/board/board.db \
        --state-db /var/lib/ciel/state/state.sqlite \
        --out /tmp/ciel-backup

    # Con S3 opcional (sube el tarball resultante):
    CIEL_BACKUP_S3=s3://bucket/prefix uv run python scripts/backup_state.py ...
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_audit(audit_dir: Path, out_dir: Path) -> bool:
    """Copia el árbol JSONL particionado por tenant/session."""
    if not audit_dir.exists():
        print(f"[warn] audit dir no existe: {audit_dir}", file=sys.stderr)
        return False
    dest = out_dir / "audit"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(audit_dir, dest)
    n = sum(1 for _ in dest.rglob("*.jsonl"))
    print(f"[ok] audit: {n} archivos JSONL -> {dest}")
    return True


def backup_board_sqlite(board_db: Path, out_dir: Path) -> bool:
    """Copia el SQLite del board (vía .backup si hay sqlite3, si no copia)."""
    if not board_db.exists():
        print(f"[warn] board db no existe: {board_db}", file=sys.stderr)
        return False
    dest = out_dir / "board"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "board.bak"
    try:
        subprocess.run(
            ["sqlite3", str(board_db), f".backup {target}"],
            check=True,
            capture_output=True,
        )
        print(f"[ok] board: .backup -> {target}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.copy(board_db, target)
        print(f"[ok] board: copia directa -> {target}")
    return True


def backup_state_sqlite(state_db: Path, out_dir: Path) -> bool:
    """Copia el SQLite local del StateBackend (F15)."""
    if not state_db.exists():
        print(f"[warn] state db no existe: {state_db} (¿Postgres? omite)", file=sys.stderr)
        return False
    dest = out_dir / "state"
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "state.bak"
    try:
        subprocess.run(
            ["sqlite3", str(state_db), f".backup {target}"],
            check=True,
            capture_output=True,
        )
        print(f"[ok] state: .backup -> {target}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.copy(state_db, target)
        print(f"[ok] state: copia directa -> {target}")
    return True


def pack(out_dir: Path) -> Path:
    tar_path = out_dir.parent / f"ciel-backup-{_ts()}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(out_dir, arcname=out_dir.name)
    print(f"[ok] paquete: {tar_path}")
    return tar_path


def upload_s3(tar_path: Path, s3_prefix: str) -> bool:
    """Sube el tarball a S3 si hay CLI de aws o s3cmd. Optativo."""
    target = f"{s3_prefix.rstrip('/')}/{tar_path.name}"
    for cli, args in (
        ("aws", ["s3", "cp", str(tar_path), target]),
        ("s3cmd", ["cp", str(tar_path), target]),
    ):
        try:
            subprocess.run([cli, *args], check=True, capture_output=True)
            print(f"[ok] S3: subido {target} vía {cli}")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print("[warn] S3 no disponible (falta aws-cli/s3cmd); backup queda local", file=sys.stderr)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup offline-safe de Ciel audit/board/state")
    ap.add_argument("--audit-dir", default=os.getenv("CIEL_AUDIT_DIR", "audit"))
    ap.add_argument("--board-db", default=os.getenv("CIEL_BOARD_DB"))
    ap.add_argument("--state-db", default=os.getenv("CIEL_STATE_SQLITE"))
    ap.add_argument("--out", default=os.getenv("CIEL_BACKUP_OUT", "ciel-backup"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    backup_audit(Path(args.audit_dir), out_dir)
    if args.board_db:
        backup_board_sqlite(Path(args.board_db), out_dir)
    if args.state_db:
        backup_state_sqlite(Path(args.state_db), out_dir)

    tar_path = pack(out_dir)

    s3_prefix = os.getenv("CIEL_BACKUP_S3")
    if s3_prefix:
        upload_s3(tar_path, s3_prefix)
    else:
        print("[info] CIEL_BACKUP_S3 no configurado; backup solo local.")

    print(f"[done] backup completo en: {tar_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
