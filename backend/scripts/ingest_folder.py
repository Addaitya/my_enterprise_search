"""Recursively ingest PDF/TXT/CSV from a local folder (ops CLI, no HTTP).

Run::

    cd backend
    uv run python -m scripts.ingest_folder /path/to/folder
    uv run python -m scripts.ingest_folder /path/to/folder --dry-run
    uv run python -m scripts.ingest_folder /path/to/folder --fail-fast
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.services.ingest.folder_walk import ClassifiedFile, classify_tree
from app.services.ingest.local_file import ingest_local_bytes
from app.services.minio_store import MinioStore

LARGE_FILE_WARN_BYTES = 512 * 1024 * 1024


@dataclass
class FileOutcome:
    relative_posix: str
    status: str
    file_id: UUID | None = None
    chunk_count: int | None = None
    object_store_path: str | None = None
    error: str | None = None


@dataclass
class FolderRunResult:
    ingested: int = 0
    failed: int = 0
    skipped_type: int = 0
    skipped_hidden: int = 0
    eligible: int = 0
    outcomes: list[FileOutcome] = field(default_factory=list)
    stopped_early: bool = False

    @property
    def exit_code(self) -> int:
        return 0 if self.failed == 0 else 1


def _line(tag: str, rest: str) -> str:
    prefix = f"[{tag}]"
    if len(prefix) < 8:
        prefix = prefix.ljust(8)
    else:
        prefix = prefix + " "
    return prefix + rest


def _emit_skip(emit: Callable[[str], None], item: ClassifiedFile) -> None:
    if item.kind == "hidden":
        emit(_line("skip", f"{item.relative_posix}  (hidden)"))
    elif item.kind == "unsupported":
        emit(_line("skip", f"{item.relative_posix}  (unsupported extension)"))


def ingest_folder(
    root: Path,
    *,
    dry_run: bool = False,
    fail_fast: bool = False,
    emit: Callable[[str], None] | None = None,
) -> FolderRunResult:
    """Walk ``root`` and ingest eligible files sequentially. Does not follow symlinks."""
    emit = emit or print
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"folder not found: {root}")

    classified = classify_tree(root)
    result = FolderRunResult()

    if dry_run:
        for item in classified:
            if item.kind == "eligible":
                emit(_line("ingest", item.relative_posix))
                result.eligible += 1
                result.outcomes.append(
                    FileOutcome(relative_posix=item.relative_posix, status="eligible")
                )
            else:
                _emit_skip(emit, item)
                if item.kind == "hidden":
                    result.skipped_hidden += 1
                    status = "skip_hidden"
                else:
                    result.skipped_type += 1
                    status = "skip_type"
                result.outcomes.append(
                    FileOutcome(relative_posix=item.relative_posix, status=status)
                )
        emit("")
        emit(
            f"ingested=0  failed=0  skipped_type={result.skipped_type}  "
            f"skipped_hidden={result.skipped_hidden}  eligible={result.eligible}"
        )
        return result

    settings = get_settings()
    store = MinioStore(settings)
    with Session(bind=get_engine()) as db:
        for item in classified:
            if item.kind == "hidden":
                _emit_skip(emit, item)
                result.skipped_hidden += 1
                result.outcomes.append(
                    FileOutcome(relative_posix=item.relative_posix, status="skip_hidden")
                )
                continue
            if item.kind == "unsupported":
                _emit_skip(emit, item)
                result.skipped_type += 1
                result.outcomes.append(
                    FileOutcome(relative_posix=item.relative_posix, status="skip_type")
                )
                continue

            result.eligible += 1
            if item.size_bytes >= LARGE_FILE_WARN_BYTES:
                emit(
                    _line(
                        "warn",
                        f"{item.relative_posix}  size >= 512 MiB (in-memory ingest)",
                    )
                )
            try:
                data = item.path.read_bytes()
            except OSError as exc:
                emit(_line("fail", f"{item.relative_posix}  {exc}"))
                result.failed += 1
                result.outcomes.append(
                    FileOutcome(
                        relative_posix=item.relative_posix,
                        status="fail",
                        error=str(exc),
                    )
                )
                if fail_fast:
                    result.stopped_early = True
                    break
                continue

            try:
                ingested = ingest_local_bytes(
                    db,
                    data=data,
                    filename=item.path.name,
                    original_source=item.relative_posix,
                    settings=settings,
                    store=store,
                )
            except Exception as exc:  # noqa: BLE001 — per-file; continue unless fail-fast
                emit(_line("fail", f"{item.relative_posix}  {exc}"))
                result.failed += 1
                result.outcomes.append(
                    FileOutcome(
                        relative_posix=item.relative_posix,
                        status="fail",
                        error=str(exc),
                    )
                )
                if fail_fast:
                    result.stopped_early = True
                    break
                continue

            emit(
                _line(
                    "ok",
                    f"{item.relative_posix}  file_id={ingested.file_id}  "
                    f"chunks={ingested.chunk_count}",
                )
            )
            result.ingested += 1
            result.outcomes.append(
                FileOutcome(
                    relative_posix=item.relative_posix,
                    status="ok",
                    file_id=ingested.file_id,
                    chunk_count=ingested.chunk_count,
                    object_store_path=ingested.object_store_path,
                )
            )

    emit("")
    emit(
        f"ingested={result.ingested}  failed={result.failed}  "
        f"skipped_type={result.skipped_type}  skipped_hidden={result.skipped_hidden}"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.ingest_folder",
        description="Recursively ingest PDF/TXT/CSV files from a local folder.",
    )
    parser.add_argument("folder", help="Root directory to walk (must exist)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify files only; do not write stores",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first ingest failure",
    )
    args = parser.parse_args(argv)
    root = Path(args.folder)
    if not root.exists() or not root.is_dir():
        print(f"folder not found: {root}", file=sys.stderr)
        return 1
    result = ingest_folder(root, dry_run=args.dry_run, fail_fast=args.fail_fast)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
