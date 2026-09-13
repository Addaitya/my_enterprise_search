"""Classify files under a local folder for ingest (no store I/O)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.services.ingest.detect import detect_file_type

Kind = Literal["eligible", "hidden", "unsupported"]


@dataclass(frozen=True)
class ClassifiedFile:
    path: Path
    relative_posix: str
    kind: Kind
    size_bytes: int


def is_hidden_relative(relative: Path) -> bool:
    """True if any path component under ROOT starts with ``.``."""
    return any(part.startswith(".") for part in relative.parts)


def classify_tree(root: Path) -> list[ClassifiedFile]:
    """Walk ``root`` (no symlink follow). Sort by relative POSIX path."""
    if not root.exists():
        raise FileNotFoundError(f"folder not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    root = root.resolve(strict=True)
    found: list[ClassifiedFile] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root)
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0
            if is_hidden_relative(rel):
                kind: Kind = "hidden"
            else:
                try:
                    detect_file_type(path.name)
                    kind = "eligible"
                except ValueError:
                    kind = "unsupported"
            found.append(
                ClassifiedFile(
                    path=path,
                    relative_posix=rel.as_posix(),
                    kind=kind,
                    size_bytes=size_bytes,
                )
            )
    found.sort(key=lambda item: item.relative_posix)
    return found
