# logic/download.py
"""
ZIP packaging of a session's generated documents.

Shared by GET /download (zip what's in the session) and POST /download (zip a
fresh headless run). The whole archive is built in memory, so the caller can
delete the on-disk session folder as soon as this returns.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path


def zip_generated_docs(session_dir: Path) -> io.BytesIO:
    """Zip every generated_*.docx in a session folder (sorted, stable order).

    Entries keep the on-disk name (arcname=path.name) — name-agnostic, so a
    future change to the renderer's output naming flows into the archive with no
    edit here. Returns the archive as a seek-to-0 BytesIO.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(session_dir.glob("generated_*.docx")):
            zf.write(path, arcname=path.name)
    buf.seek(0)
    return buf
