from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a doc-pre working bundle from a local document.",
    )
    parser.add_argument("input", help="Path to the input file")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="output",
        help="Directory where the generated bundle will be written",
    )
    parser.add_argument(
        "--use-plugins",
        action="store_true",
        help="Forward plugin loading to the MarkItDown baseline adapter when available.",
    )
    parser.add_argument(
        "--agent-exec-mode",
        choices=["builtin", "external-command", "disabled"],
        default="builtin",
        help="Select how the agent review executor is executed.",
    )
    parser.add_argument(
        "--agent-command",
        default="",
        help="Optional external command used when --agent-exec-mode=external-command.",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Minimal output mode: only source.md, final.md, manifest.json and page assets. "
             "Skips evidence collection, agent review, and compatibility outputs.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    from .pipeline import DocumentPipeline
    from .workers import AgentReviewExecutor

    pipeline = DocumentPipeline(
        agent_review_executor=AgentReviewExecutor(
            enabled=args.agent_exec_mode != "disabled",
            mode=args.agent_exec_mode,
            external_command=args.agent_command or None,
        ),
        minimal=args.minimal,
    )
    pipeline.baseline_adapter.enable_plugins = args.use_plugins
    bundle = pipeline.run_local(args.input, args.output_dir)

    print(f"Bundle created: {bundle.bundle_dir}")
    print(f"Route: {bundle.route_decision.route}")
    print(f"Source markdown: {bundle.bundle_dir / 'source.md'}")
    print(f"Final markdown: {bundle.bundle_dir / 'final.md'}")
    print(f"Manifest: {bundle.bundle_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
