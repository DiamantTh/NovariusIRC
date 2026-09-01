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

    def restore(self, archive_path: Path, *, replace: bool, restore_data: bool) -> None:
        """Restore a verified archive; callers must explicitly allow replacement."""
        archive_path = archive_path.resolve()
        if not archive_path.is_file():
            raise BackupError(f"backup archive does not exist: {archive_path}")
        if self.database.path.exists() and not replace:
            raise BackupError("database exists; use --replace-database to restore")
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=self.directory) as raw:
            staging = Path(raw)
            tar_path = archive_path
            if archive_path.suffix == ".bz3":
                tar_path = staging / "archive.tar"
                try:
                    with tar_path.open("xb") as output:
                        subprocess.run(
                            ["bzip3", "-dc", str(archive_path)],
                            check=True,
                            stdout=output,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                except FileNotFoundError as exc:
                    raise BackupError("bzip3 is not installed") from exc
                except subprocess.CalledProcessError as exc:
                    raise BackupError(f"bzip3 failed: {exc.stderr.strip()}") from exc
            try:
                with tarfile.open(tar_path) as archive:
                    members = archive.getmembers()
                    if any(
                        member.issym() or member.islnk() or Path(member.name).is_absolute()
                        or ".." in Path(member.name).parts
                        for member in members
                    ):
                        raise BackupError("backup archive contains unsafe paths")
                    archive.extractall(staging / "contents", filter="data")
            except (tarfile.TarError, OSError) as exc:
                raise BackupError(f"cannot read backup archive: {exc}") from exc
            contents = staging / "contents"
            try:
                manifest = json.loads((contents / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BackupError("backup has no valid manifest") from exc
            if manifest.get("format") != 1 or manifest.get("bot_name") != self.instance_name:
                raise BackupError("backup does not belong to this bot instance")
            for item in manifest.get("files", []):
                path = contents / item["path"]
                if not path.is_file() or path.stat().st_size != item["size"] or self._sha256(path) != item["sha256"]:
                    raise BackupError(f"backup file verification failed: {item.get('path')}")
            snapshot = contents / "database.sqlite3"
            if not snapshot.is_file():
                raise BackupError("backup has no database snapshot")
            try:
                with sqlite3.connect(snapshot) as connection:
                    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise BackupError("backup database integrity check failed")
            except sqlite3.Error as exc:
                raise BackupError(f"backup database is invalid: {exc}") from exc
            self.database.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_database = self.database.path.with_suffix(".restore.tmp")
            shutil.copy2(snapshot, temporary_database)
            temporary_database.replace(self.database.path)
            for suffix in ("-wal", "-shm"):
                Path(f"{self.database.path}{suffix}").unlink(missing_ok=True)
            if restore_data:
                source_data = contents / "data"
                if source_data.is_dir():
                    for source in source_data.rglob("*"):
                        if source.is_file():
                            target = self.data_root / source.relative_to(source_data)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, target)
            try:
                self.database.check()
            except DatabaseError as exc:
                raise BackupError(f"restored database failed validation: {exc}") from exc
