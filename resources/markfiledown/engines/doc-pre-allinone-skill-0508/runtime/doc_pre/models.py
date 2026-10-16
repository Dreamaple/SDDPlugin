from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .utils import relative_to_root


@dataclass(slots=True)
class SourceDocument:
    document_id: str
    filename: str
    media_type: str
    extension: str
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RouteDecision:
    route: str
    confidence: float
    rationale: str


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    kind: str
    role: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PageRecord:
    page_number: int
    route_hint: str
    screenshot_path: str | None = None
    needs_visual_review: bool = False
    diagram_candidate: bool = False
    tile_paths: list[str] = field(default_factory=list)
    region_paths: list[str] = field(default_factory=list)
    text_length: int | None = None
    image_count: int | None = None
    char_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TableRecord:
    table_id: str
    source_kind: str
    csv_path: str | None = None
    preview_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentTask:
    task_id: str
    kind: str
    description: str
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkingBundle:
    bundle_dir: Path
    source_document: SourceDocument
    route_decision: RouteDecision
    draft_markdown: str = ""
    final_markdown: str = ""
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    page_records: list[PageRecord] = field(default_factory=list)
    table_records: list[TableRecord] = field(default_factory=list)
    agent_tasks: list[AgentTask] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    compatibility_outputs: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def layout_paths(self) -> dict[str, Path]:
        artifacts_dir = self.bundle_dir / "artifacts"
        return {
            "root": self.bundle_dir,
            "artifacts": artifacts_dir,
            "images": artifacts_dir / "images",
            "pages": artifacts_dir / "pages",
            "regions": artifacts_dir / "regions",
            "tables": artifacts_dir / "tables",
            "evidence": self.bundle_dir / "evidence",
            "markdown": self.bundle_dir / "markdown",
            "diagnostics": self.bundle_dir / "diagnostics",
            "compatibility": self.bundle_dir / "compatibility",
        }

    def ensure_layout(self) -> None:
        for path in self.layout_paths().values():
            path.mkdir(parents=True, exist_ok=True)

    def add_diagnostic(self, message: str) -> None:
        self.diagnostics.append(message)

    def add_artifact(
        self,
        *,
        kind: str,
        role: str,
        path: Path,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        record = ArtifactRecord(
            artifact_id=f"artifact-{len(self.artifacts) + 1:04d}",
            kind=kind,
            role=role,
            path=relative_to_root(path, self.bundle_dir),
            metadata=metadata or {},
        )
        self.artifacts.append(record)
        return record

    def add_agent_task(
        self,
        *,
        kind: str,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTask:
        task = AgentTask(
            task_id=f"task-{len(self.agent_tasks) + 1:04d}",
            kind=kind,
            description=description,
            metadata=metadata or {},
        )
        self.agent_tasks.append(task)
        return task

    def manifest(self) -> dict[str, Any]:
        return {
            "bundle_dir": self.bundle_dir.as_posix(),
            "source_document": asdict(self.source_document),
            "route_decision": asdict(self.route_decision),
            "artifacts": [asdict(record) for record in self.artifacts],
            "page_records": [asdict(record) for record in self.page_records],
            "table_records": [asdict(record) for record in self.table_records],
            "agent_tasks": [asdict(task) for task in self.agent_tasks],
            "diagnostics": list(self.diagnostics),
            "compatibility_outputs": dict(self.compatibility_outputs),
            "metadata": dict(self.metadata),
        }
