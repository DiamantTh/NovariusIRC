"""Verified offline backup archives for one NovariusIRC instance."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import BackupConfig
from .database import DatabaseError, SQLiteDatabase


class BackupError(RuntimeError):
    """Raised when creating, verifying, or restoring a backup fails."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    created_at: datetime
    compressed: bool


class BackupManager:
    """Creates a self-verifying archive without copying SQLite files directly."""

    def __init__(
        self,
        config: BackupConfig,
        database: SQLiteDatabase,
        instance_name: str,
        data_root: Path,
    ) -> None:
        self.config = config
        self.database = database
        self.instance_name = instance_name
        self.data_root = data_root
        self.directory = Path(config.directory)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _snapshot_database(self, destination: Path) -> None:
        try:
            with sqlite3.connect(self.database.path) as source, sqlite3.connect(
                destination
            ) as target:
                source.backup(target)
        except sqlite3.Error as exc:
            raise BackupError(f"SQLite backup failed: {exc}") from exc

    def _copy_data(self, destination: Path) -> list[Path]:
        copied: list[Path] = []
        if not self.config.include_data or not self.data_root.is_dir():
            return copied
        archive_root = self.directory.resolve()
        database_path = self.database.path.resolve()
        database_artifacts = {
            database_path,
            Path(f"{database_path}-wal"),
            Path(f"{database_path}-shm"),
        }
        for source in self.data_root.rglob("*"):
            if source.is_symlink() or not source.is_file():
                continue
            resolved = source.resolve()
            if resolved in database_artifacts or resolved.is_relative_to(archive_root):
                continue
            relative = source.relative_to(self.data_root)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target)
        return copied

    def create(self) -> BackupResult:
        if not self.config.enabled:
            raise BackupError("backups are disabled in [backups]")
        try:
            self.database.check()
        except DatabaseError as exc:
            raise BackupError(str(exc)) from exc
        self.directory.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now(UTC)
        timestamp = created_at.strftime("%Y%m%dT%H%M%SZ")
        name = f"{self.instance_name}_{timestamp}"
        with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=self.directory) as raw:
            staging = Path(raw)
            snapshot = staging / "database.sqlite3"
            self._snapshot_database(snapshot)
            data_files = self._copy_data(staging / "data")
            files = [snapshot, *data_files]
            manifest = {
                "format": 1,
                "bot_name": self.instance_name,
                "backend": "sqlite",
                "created_at": created_at.isoformat(),
                "database_schema": self.database.check().schema_version,
                "files": [
                    {
                        "path": str(file.relative_to(staging)),
                        "size": file.stat().st_size,
                        "sha256": self._sha256(file),
                    }
                    for file in files
                ],
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            tar_path = self.directory / f"{name}.tar"
            with tarfile.open(tar_path, "x") as archive:
                archive.add(staging / "manifest.json", arcname="manifest.json")
                for file in files:
                    archive.add(file, arcname=str(file.relative_to(staging)))
            if (
                self.config.compression == "bzip3"
                and tar_path.stat().st_size >= self.config.compression_min_bytes
            ):
                compressed = tar_path.with_suffix(".tar.bz3")
                try:
                    with compressed.open("xb") as output:
                        subprocess.run(
                            ["bzip3", "-c", str(tar_path)],
                            check=True,
                            stdout=output,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                except FileNotFoundError as exc:
                    raise BackupError("bzip3 is not installed") from exc
                except subprocess.CalledProcessError as exc:
                    raise BackupError(f"bzip3 failed: {exc.stderr.strip()}") from exc
                tar_path.unlink()
                return BackupResult(compressed, created_at, True)
            return BackupResult(tar_path, created_at, False)

    def list(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(
            [*self.directory.glob(f"{self.instance_name}_*.tar"), *self.directory.glob(f"{self.instance_name}_*.tar.bz3")],
            reverse=True,
        )
