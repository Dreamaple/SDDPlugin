from __future__ import annotations

import mimetypes
from pathlib import Path

from ..models import SourceDocument, WorkingBundle
from ..routing import route_source_document
from ..utils import build_document_id


class LocalFileInputAdapter:
    def load(self, file_path: str | Path, output_root: str | Path) -> WorkingBundle:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Input file not found: {path}")

        media_type, _ = mimetypes.guess_type(path.name)
        source_document = SourceDocument(
            document_id=build_document_id(path),
            filename=path.name,
            media_type=media_type or "application/octet-stream",
            extension=path.suffix.lower(),
            source_path=str(path),
            metadata={
                "size_bytes": path.stat().st_size,
            },
        )

        bundle_dir = Path(output_root).expanduser().resolve() / source_document.document_id
        bundle = WorkingBundle(
            bundle_dir=bundle_dir,
            source_document=source_document,
            route_decision=route_source_document(source_document),
        )
        bundle.ensure_layout()
        return bundle
