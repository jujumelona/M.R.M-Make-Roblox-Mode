"""Command Line Interface (CLI) for R.M.M (Roblox Mod & Experience AI)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import CompleteRobloxAISession
from .luau_analyzer import LuauStaticAnalyzer
from .open_cloud import RobloxOpenCloudClient
from .pre_design_research import RobloxPreDesignResearch
import json


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rmm",
        description="R.M.M: Roblox Mod & Experience AI - Automated planning, Luau generation, and .rbxlx production",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: plan
    plan_parser = subparsers.add_parser("plan", help="Generate game design plan from prompt")
    plan_parser.add_argument("prompt", type=str, help="Natural language experience description")
    plan_parser.add_argument("--output", "-o", type=str, default="rmm-output", help="Output directory")
    plan_parser.add_argument("--mode", choices=["new_experience", "existing_experience_addon"],
                             default="new_experience", help="New place or additive add-on for an owned Experience")

    # Command: research: execute actual source discovery without generating a place.
    research_parser = subparsers.add_parser(
        "research", help="Fetch Roblox official docs and preserve request RAG evidence"
    )
    research_parser.add_argument("prompt", type=str)
    research_parser.add_argument("--output", "-o", type=str, default="rmm-output/pre_design_research.json")
    research_parser.add_argument("--offline", action="store_true",
                                 help="Use labelled local catalogue, no live official docs")
    
    # Command: revise
    revise_parser = subparsers.add_parser("revise", help="Revise an existing saved plan")
    revise_parser.add_argument("feedback", type=str, help="Revision instructions")
    revise_parser.add_argument("--plan-file", "-p", type=str, default="rmm-output/proposal.json")

    # Command: build
    build_parser = subparsers.add_parser("build", help="Build Luau scripts, .rbxlx place, and project ZIP")
    build_parser.add_argument("--plan-file", "-p", type=str, default="rmm-output/proposal.json")
    build_parser.add_argument("--output", "-o", type=str, default="rmm-output")
    build_parser.add_argument("--source-only", action="store_true", help="Generate code without compiling .rbxlx")

    # Command: analyze
    analyze_parser = subparsers.add_parser("analyze", help="Run Luau static analysis and syntax checks")
    analyze_parser.add_argument("directory", type=str, default=".", nargs="?")

    # Command: publish
    publish_parser = subparsers.add_parser("publish", help="Publish .rbxlx to Roblox via Open Cloud")
    publish_parser.add_argument("--universe", "-u", type=str, required=True, help="Universe ID")
    publish_parser.add_argument("--place", "-p", type=str, required=True, help="Place ID")
    publish_parser.add_argument("--file", "-f", type=str, required=True, help="Path to .rbxlx file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "plan":
        session = CompleteRobloxAISession(output_root=args.output)
        reply = session.plan(args.prompt, project_mode=args.mode)
        print(reply.message)
        print(f"\n[Plan saved to {args.output}/proposal.json]")

    elif args.command == "research":
        evidence = RobloxPreDesignResearch(live_enabled=not args.offline).research(args.prompt)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({
            "status": evidence["status"],
            "queries": len(evidence["queries"]),
            "verified_document_excerpts": sum(
                x["provider"] == "official_docs" for x in evidence["evidence"]
            ),
            "unimplemented": evidence["ledger"]["unimplemented_facets"],
            "provider_failures": evidence["provider_failures"],
            "saved_to": str(output),
        }, indent=2, ensure_ascii=False))
        if evidence["status"] in ("unresolved", "partial"):
            sys.exit(2)

    elif args.command == "revise":
        session = CompleteRobloxAISession()
        session.load_plan(args.plan_file)
        reply = session.revise(args.feedback)
        print(reply.message)
        print(f"\n[Plan revised and updated at {args.plan_file}]")

    elif args.command == "build":
        session = CompleteRobloxAISession(output_root=args.output)
        session.load_plan(args.plan_file)
        result = session.build(source_only=args.source_only)
        if result.metadata.get("addon_prepared"):
            print("\nExisting-Experience addon sources prepared (NOT verified or published).")
            print(f"Addon ZIP: {result.project_zip_path}")
        elif result.success:
            print(f"\nBuild complete: {result.metadata.get('release_status', 'built_unverified')}")
            print("Roblox Studio gameplay playtest: NOT RUN (optional local step).")
            if result.rbxlx_path:
                print(f"🎮 Roblox Place File: {result.rbxlx_path}")
            if result.project_zip_path:
                print(f"📦 Project ZIP File: {result.project_zip_path}")
        else:
            print("\nBuild failed during planning, code generation, lint, or Rojo packaging.")
            sys.exit(1)

    elif args.command == "analyze":
        analyzer = LuauStaticAnalyzer()
        root = Path(args.directory)
        files = {str(p): p.read_text(encoding="utf-8") for p in root.rglob("*.luau")}
        report = analyzer.analyze_files(files)
        print(f"Analyzed {report.files_analyzed} files:")
        for diag in report.diagnostics:
            print(f"[{diag.severity}] {diag.file_path}:{diag.line_number} ({diag.rule}): {diag.message}")
        sys.exit(0 if report.passed else 1)

    elif args.command == "publish":
        client = RobloxOpenCloudClient()
        res = client.publish_place(args.universe, args.place, args.file)
        print(f"Publish result: {res}")


if __name__ == "__main__":
    main()
