"""Local filesystem staging for Drive-style resumable byte ranges.

Bytes are assembled here during initiate/PUT; MinIO is written once on complete
as a single full object (no MinIO chunking / multipart).
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings


class LocalStaging:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = Path(self.settings.ingest_local_staging_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, upload_id: str) -> Path:
        return self.root / f"{upload_id}.bin"

    def ensure(self, upload_id: str) -> str:
        """Create empty staging file; return path string stored on upload_sessions."""
        path = self.path_for(upload_id)
        path.write_bytes(b"")
        return str(path)

    def put_range(self, upload_id: str, start: int, data: bytes) -> int:
        """Append sequential bytes. ``start`` must equal current file size."""
        path = self.path_for(upload_id)
        if not path.exists():
            path.write_bytes(b"")
        current = path.stat().st_size
        if current != start:
            raise ValueError(f"non-sequential range: expected start={current}, got {start}")
        with path.open("ab") as fh:
            fh.write(data)
        return path.stat().st_size

    def read_bytes(self, upload_id: str) -> bytes:
        path = self.path_for(upload_id)
        if not path.exists():
            return b""
        return path.read_bytes()

    def delete(self, upload_id: str) -> None:
        path = self.path_for(upload_id)
        if path.exists():
            path.unlink()
