from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RUNTIME_ROOT = SCRIPT_DIR / "runtime"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from doc_pre.pipeline import DocumentPipeline
from doc_pre.workers import AgentReviewExecutor
from doc_pre.workers.multimodal_reconstruction import MultimodalReconstructionWorker


PDF_EXTENSIONS = {".pdf"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def update_state(output_root: Path, status: str, **extra: object) -> None:
    payload = {
        "status": status,
        "updated_at": utc_now(),
    }
    payload.update(extra)
    write_json(output_root / ".pipeline-state.json", payload)


def write_intake_validation_report(output_root: Path, args: argparse.Namespace) -> None:
    input_file = Path(args.input_file).resolve()
    input_extension = input_file.suffix.lower() or "<none>"
    lines = [
        "# Intake Validation Report",
        "",
        f"- Checked at: {utc_now()}",
        f"- Input file: {input_file}",
        f"- Output root: {Path(args.output_root).resolve()}",
        f"- Declared source format hint: {args.source_format}",
        f"- Detected extension: {input_extension}",
        f"- Markdown style: {args.markdown_style}",
        f"- Include asset links: {args.asset_links}",
        f"- Agent review validation: {args.agent_review_validation}",
        f"- Agent exec mode: {args.agent_exec_mode if args.agent_review_validation == 'on' else 'disabled'}",
        "",
        "## Checks",
        f"- Input exists: {'yes' if input_file.is_file() else 'no'}",
        "- Portable runtime present: yes",
        f"- PDF multimodal path applicable: {'yes' if input_extension in PDF_EXTENSIONS else 'no'}",
        "",
        "## Notes",
        "- This portable bundle vendors the current doc_pre runtime under runtime/doc_pre.",
        "- SKILL.md is the primary agent entry; run.ps1 is the terminal validation adapter and empty-project fallback.",
        "- Output artifacts are written into outputRoot/<document_id>/.",
        "- Root-level state and intake reports stay directly under outputRoot/ for easy empty-project validation.",
    ]
    write_text(output_root / "intake-validation-report.md", "\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Portable evidence-first document markdown pipeline runner.",
    )
    parser.add_argument(
        "--input-file",
        "--input-pdf",
        dest="input_file",
        required=True,
        help="Path to the source document file.",
    )
    parser.add_argument("--output-root", required=True, help="Output root directory")
    parser.add_argument(
        "--source-format",
        default="auto",
        help="Optional format hint for the portable bundle. The runtime still routes from the input extension.",
    )
    parser.add_argument(
        "--markdown-style",
        default="technical",
        choices=["technical", "narrative", "audit-friendly"],
        help="Declared markdown rendering style for the output contract.",
    )
    parser.add_argument(
        "--agent-review-validation",
        "--pdf-agent-validation",
        "--agent-validation",
        dest="agent_review_validation",
        default="on",
        choices=["on", "off"],
        help="Whether agent review should execute after markdown generation when the input is routed as PDF.",
    )
    parser.add_argument(
        "--asset-links",
        default="on",
        choices=["on", "off"],
        help="Whether the runtime should expose asset links in sidecar markdown outputs.",
    )
    parser.add_argument(
        "--agent-exec-mode",
        default="builtin",
        choices=["builtin", "external-command", "disabled"],
        help="Readback backend used after the evidence pack is written.",
    )
    parser.add_argument(
        "--agent-command",
        default="",
        help="Optional external command used when --agent-exec-mode=external-command.",
    )
    parser.add_argument(
        "--use-plugins",
        default="off",
        choices=["on", "off"],
        help="Forward plugin loading to the MarkItDown baseline adapter when supported.",
    )
    parser.add_argument(
        "--multimodal-reconstruction",
        default="off",
        choices=["on", "off"],
        help="Enable multimodal LLM reconstruction from page screenshots + OCR text.",
    )
    parser.add_argument(
        "--anthropic-api-key",
        default="",
        help="Anthropic API key for multimodal reconstruction (or set ANTHROPIC_API_KEY env var).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    input_file = Path(args.input_file).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    if not input_file.is_file():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    update_state(
        output_root,
        "in-progress",
        input_file=str(input_file),
        source_format=args.source_format,
        markdown_style=args.markdown_style,
        agent_review_validation=args.agent_review_validation,
        agent_exec_mode=args.agent_exec_mode,
    )
    write_intake_validation_report(output_root, args)

    agent_validation_enabled = args.agent_review_validation == "on"
    executor = AgentReviewExecutor(
        enabled=agent_validation_enabled,
        mode=args.agent_exec_mode if agent_validation_enabled else "disabled",
        external_command=args.agent_command or None,
    )
    mm_worker = None
    if args.multimodal_reconstruction == "on":
        mm_worker = MultimodalReconstructionWorker(api_key=args.anthropic_api_key)
    pipeline = DocumentPipeline(agent_review_executor=executor, multimodal_reconstruction_worker=mm_worker)
    pipeline.baseline_adapter.enable_plugins = args.use_plugins == "on"
    bundle = pipeline.run_local(input_file, output_root)

    manifest_path = bundle.bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review_status = manifest.get("metadata", {}).get("agent_exec", {}).get("status", "unknown")
    route = manifest.get("route_decision", {}).get("route", "unknown")
    compatibility_outputs = manifest.get("compatibility_outputs", {})
    primary_output = compatibility_outputs.get("single_csv") or compatibility_outputs.get(
        "csv_exports_index"
    ) or compatibility_outputs.get("single_markdown")
    agent_review_request = str(bundle.bundle_dir / "markdown" / "agent-review-request.json")
    agent_review_response = str(bundle.bundle_dir / "markdown" / "agent-review-response.json")
    agent_review_report = str(bundle.bundle_dir / "markdown" / "agent-review-report.json")
    agent_review_summary = str(bundle.bundle_dir / "markdown" / "agent-review-summary.md")

    update_state(
        output_root,
        "completed",
        input_file=str(input_file),
        bundle_dir=str(bundle.bundle_dir),
        manifest=str(manifest_path),
        source_markdown=str(bundle.bundle_dir / "source.md"),
        final_markdown=str(bundle.bundle_dir / "final.md"),
        route=route,
        primary_output=primary_output,
        single_csv=compatibility_outputs.get("single_csv"),
        csv_exports_index=compatibility_outputs.get("csv_exports_index"),
        agent_review_request=agent_review_request,
        agent_review_response=agent_review_response,
        agent_review_report=agent_review_report,
        agent_review_summary=agent_review_summary,
        review_status=review_status,
    )

    print(f"Portable bundle root: {SCRIPT_DIR}")
    print(f"Output root: {output_root}")
    print(f"Bundle created: {bundle.bundle_dir}")
    print(f"Route: {route}")
    print(f"Primary output: {primary_output}")
    print(f"Agent review report: {agent_review_report}")
    print(f"Review status: {review_status}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()