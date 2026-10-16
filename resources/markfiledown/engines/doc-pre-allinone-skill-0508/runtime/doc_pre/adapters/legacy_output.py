from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ..models import TableRecord, WorkingBundle
from ..utils import relative_to_root


SPREADSHEET_EXTENSIONS = {".csv", ".xlsx", ".xls"}


class LegacyOutputAdapter:
    def write(self, bundle: WorkingBundle) -> dict[str, str]:
        compatibility_dir = bundle.layout_paths()["compatibility"]
        compatibility_dir.mkdir(parents=True, exist_ok=True)

        final_markdown = bundle.final_markdown or bundle.draft_markdown
        markdown_name = f"{Path(bundle.source_document.filename).stem}.md"
        markdown_path = compatibility_dir / markdown_name
        markdown_path.write_text(final_markdown.rstrip() + "\n", encoding="utf-8")

        bundle.compatibility_outputs["single_markdown"] = relative_to_root(
            markdown_path, bundle.bundle_dir
        )
        bundle.add_artifact(
            kind="markdown",
            role="legacy-single-file",
            path=markdown_path,
        )

        primary_output_kind = "markdown"
        primary_output_path = bundle.compatibility_outputs["single_markdown"]

        if bundle.route_decision.route == "spreadsheet_pipeline":
            csv_outputs = self._write_spreadsheet_outputs(bundle, compatibility_dir)
            if csv_outputs.get("single_csv"):
                primary_output_kind = "csv"
                primary_output_path = csv_outputs["single_csv"]
            elif csv_outputs.get("csv_exports_index"):
                primary_output_kind = "csv-index"
                primary_output_path = csv_outputs["csv_exports_index"]

        summary_path = compatibility_dir / "legacy-summary.json"
        summary = {
            "document_id": bundle.source_document.document_id,
            "filename": bundle.source_document.filename,
            "route": bundle.route_decision.route,
            "single_markdown": bundle.compatibility_outputs["single_markdown"],
            "primary_output_kind": primary_output_kind,
            "primary_output_path": primary_output_path,
        }
        if "single_csv" in bundle.compatibility_outputs:
            summary["single_csv"] = bundle.compatibility_outputs["single_csv"]
        if "csv_exports_index" in bundle.compatibility_outputs:
            summary["csv_exports_index"] = bundle.compatibility_outputs["csv_exports_index"]
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        bundle.compatibility_outputs["legacy_summary"] = relative_to_root(
            summary_path, bundle.bundle_dir
        )
        bundle.add_artifact(
            kind="json",
            role="legacy-summary",
            path=summary_path,
        )

        return dict(bundle.compatibility_outputs)

    def _write_spreadsheet_outputs(
        self,
        bundle: WorkingBundle,
        compatibility_dir: Path,
    ) -> dict[str, str]:
        source_path = Path(bundle.source_document.source_path or "")
        extension = source_path.suffix.lower()
        if extension not in SPREADSHEET_EXTENSIONS or not source_path.exists():
            return {}

        tables_dir = bundle.layout_paths()["tables"]
        tables_dir.mkdir(parents=True, exist_ok=True)

        if extension == ".csv":
            csv_name = f"{source_path.stem}.csv"
            canonical_path = tables_dir / csv_name
            shutil.copyfile(source_path, canonical_path)
            compatibility_path = compatibility_dir / csv_name
            shutil.copyfile(canonical_path, compatibility_path)

            bundle.table_records = [
                TableRecord(
                    table_id="table-0001",
                    source_kind="csv-file",
                    csv_path=relative_to_root(canonical_path, bundle.bundle_dir),
                    preview_enabled=False,
                    metadata={"sheet_name": None},
                )
            ]
            bundle.add_artifact(
                kind="csv",
                role="spreadsheet-csv-export",
                path=canonical_path,
                metadata={"sheet_name": None},
            )
            bundle.compatibility_outputs["single_csv"] = relative_to_root(
                compatibility_path, bundle.bundle_dir
            )
            return {"single_csv": bundle.compatibility_outputs["single_csv"]}

        try:
            table_paths = self._export_excel_as_csv(source_path, tables_dir)
        except Exception as exc:
            bundle.add_diagnostic(f"Spreadsheet CSV export failed: {exc}")
            return {}

        compatibility_rows: list[dict[str, str]] = []
        bundle.table_records = []

        for index, exported in enumerate(table_paths, start=1):
            compatibility_path = compatibility_dir / exported["filename"]
            shutil.copyfile(exported["path"], compatibility_path)
            relative_csv_path = relative_to_root(exported["path"], bundle.bundle_dir)
            bundle.table_records.append(
                TableRecord(
                    table_id=f"table-{index:04d}",
                    source_kind="spreadsheet-sheet",
                    csv_path=relative_csv_path,
                    preview_enabled=False,
                    metadata={"sheet_name": exported["sheet_name"]},
                )
            )
            bundle.add_artifact(
                kind="csv",
                role="spreadsheet-csv-export",
                path=exported["path"],
                metadata={"sheet_name": exported["sheet_name"]},
            )
            compatibility_rows.append(
                {
                    "sheet_name": exported["sheet_name"],
                    "csv_path": relative_to_root(compatibility_path, bundle.bundle_dir),
                }
            )

        index_path = compatibility_dir / f"{source_path.stem}-csv-exports.json"
        index_payload = {
            "document_id": bundle.source_document.document_id,
            "filename": bundle.source_document.filename,
            "sheet_exports": compatibility_rows,
        }
        index_path.write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        bundle.add_artifact(
            kind="json",
            role="spreadsheet-csv-export-index",
            path=index_path,
        )
        bundle.compatibility_outputs["csv_exports_index"] = relative_to_root(
            index_path, bundle.bundle_dir
        )
        if len(compatibility_rows) == 1:
            bundle.compatibility_outputs["single_csv"] = compatibility_rows[0]["csv_path"]

        return {
            key: value
            for key, value in bundle.compatibility_outputs.items()
            if key in {"single_csv", "csv_exports_index"}
        }

    def _export_excel_as_csv(self, source_path: Path, tables_dir: Path) -> list[dict[str, Path | str]]:
        try:
            import pandas
        except ImportError as exc:  # pragma: no cover - dependency issue
            raise RuntimeError(
                "Spreadsheet CSV export requires pandas with openpyxl/xlrd installed."
            ) from exc

        workbook = pandas.read_excel(source_path, sheet_name=None, dtype=object)
        exported: list[dict[str, Path | str]] = []
        for index, (sheet_name, frame) in enumerate(workbook.items(), start=1):
            slug = self._sheet_slug(sheet_name, index)
            filename = f"{source_path.stem}--{slug}.csv"
            csv_path = tables_dir / filename
            normalized_frame = frame.where(frame.notna(), "")
            normalized_frame.to_csv(csv_path, index=False)
            exported.append(
                {
                    "sheet_name": sheet_name,
                    "filename": filename,
                    "path": csv_path,
                }
            )
        return exported

    def _sheet_slug(self, sheet_name: str, index: int) -> str:
        collapsed = re.sub(r"[^A-Za-z0-9]+", "-", sheet_name).strip("-").lower()
        if not collapsed:
            collapsed = f"sheet-{index:02d}"
        if not collapsed.startswith("sheet-"):
            collapsed = f"sheet-{index:02d}-{collapsed}"
        return collapsed[:80]
