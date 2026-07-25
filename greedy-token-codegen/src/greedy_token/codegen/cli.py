"""CLI handlers for codegen commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from greedy_token.codegen.schema import TARGETS, TestSuite
from greedy_token.codegen.extractor import extract_from_pytest
from greedy_token.codegen.generator import generate_project


def cmd_codegen_extract(args: argparse.Namespace) -> int:
    """Extract meta-schema from pytest tests."""
    tests_dir = Path(args.tests_dir)
    if not tests_dir.is_dir():
        print(f"codegen: tests directory not found: {tests_dir}", file=sys.stderr)
        return 1

    try:
        suite = extract_from_pytest(
            tests_dir,
            name=args.name or tests_dir.parent.name,
            version=args.version,
            description=args.description,
        )
    except Exception as e:
        print(f"codegen: extraction failed: {e}", file=sys.stderr)
        return 1

    stats = {
        "name": suite.name,
        "version": suite.version,
        "modules": len(suite.modules),
        "tests": sum(len(m.tests) for m in suite.modules),
        "fixtures": len(suite.global_fixtures) + sum(len(m.fixtures) for m in suite.modules),
    }

    if args.output:
        output = Path(args.output)
        suite.to_file(output)
        print(f"Meta-schema written to: {output}")
        print(f"  Modules: {stats['modules']}")
        print(f"  Tests:   {stats['tests']}")
        print(f"  Fixtures: {stats['fixtures']}")
    elif args.json:
        print(suite.to_json())
    else:
        print(json.dumps(stats, indent=2))

    return 0


def cmd_codegen_generate(args: argparse.Namespace) -> int:
    """Generate test project from meta-schema."""
    if args.target not in TARGETS:
        available = ", ".join(sorted(TARGETS.keys()))
        print(f"codegen: unknown target: {args.target}", file=sys.stderr)
        print(f"Available targets: {available}", file=sys.stderr)
        return 1

    if args.schema:
        schema_path = Path(args.schema)
        if not schema_path.is_file():
            print(f"codegen: schema file not found: {schema_path}", file=sys.stderr)
            return 1
        suite = TestSuite.from_file(schema_path)
    elif args.tests_dir:
        tests_dir = Path(args.tests_dir)
        if not tests_dir.is_dir():
            print(f"codegen: tests directory not found: {tests_dir}", file=sys.stderr)
            return 1
        suite = extract_from_pytest(
            tests_dir,
            name=args.name or tests_dir.parent.name,
        )
    else:
        print("codegen: provide --schema or --tests-dir", file=sys.stderr)
        return 1

    output_dir = Path(args.output)

    try:
        report = generate_project(
            suite,
            args.target,
            output_dir,
            overwrite=args.overwrite,
        )
    except RuntimeError as e:
        print(f"codegen: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Generated {args.target} project in: {output_dir}")
        print(f"  Files created: {len(report['files_created'])}")
        if report["files_skipped"]:
            print(f"  Files skipped: {len(report['files_skipped'])} (use --overwrite)")
        if report["warnings"]:
            print(f"  Warnings: {len(report['warnings'])}")
            for warning in report["warnings"]:
                print(f"    - {warning}")

    return 0


def cmd_codegen_list_targets(args: argparse.Namespace) -> int:
    """List available code generation targets."""
    if args.json:
        print(json.dumps(TARGETS, indent=2))
    else:
        print("Available codegen targets:\n")
        for target_id, config in sorted(TARGETS.items()):
            lang = config["language"]
            framework = config["test_framework"]
            build = config["build_tool"]
            print(f"  {target_id}")
            print(f"    Language:   {lang}")
            print(f"    Framework:  {framework}")
            print(f"    Build tool: {build}")
            print()

    return 0


def cmd_codegen_matrix(args: argparse.Namespace) -> int:
    """Generate CI matrix workflow for all targets."""
    if args.schema:
        schema_path = Path(args.schema)
        if not schema_path.is_file():
            print(f"codegen: schema file not found: {schema_path}", file=sys.stderr)
            return 1
        suite = TestSuite.from_file(schema_path)
    elif args.tests_dir:
        tests_dir = Path(args.tests_dir)
        if not tests_dir.is_dir():
            print(f"codegen: tests directory not found: {tests_dir}", file=sys.stderr)
            return 1
        suite = extract_from_pytest(
            tests_dir,
            name=args.name or tests_dir.parent.name,
        )
    else:
        print("codegen: provide --schema or --tests-dir", file=sys.stderr)
        return 1

    targets = args.targets.split(",") if args.targets else list(TARGETS.keys())
    output_dir = Path(args.output)

    matrix = _generate_matrix_workflow(suite, targets, output_dir)

    if args.json:
        print(json.dumps(matrix, indent=2))
    else:
        workflow_path = output_dir / ".github" / "workflows" / "matrix-test.yml"
        print(f"Generated CI matrix workflow: {workflow_path}")
        print(f"  Targets: {', '.join(targets)}")

    return 0


def _generate_matrix_workflow(
    suite: TestSuite,
    targets: list[str],
    output_dir: Path,
) -> dict:
    """Generate GitHub Actions matrix workflow."""
    workflows_dir = output_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    java_targets = [t for t in targets if TARGETS.get(t, {}).get("language") == "java"]
    ts_targets = [t for t in targets if TARGETS.get(t, {}).get("language") == "typescript"]

    workflow = f"""name: Test Matrix

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
"""

    if java_targets:
        workflow += """  java-tests:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        target: [{java_matrix}]
    steps:
      - uses: actions/checkout@v4
      - name: Set up JDK 17
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
      - name: Run tests
        working-directory: generated/${{{{ matrix.target }}}}
        run: ./gradlew test
      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results-${{{{ matrix.target }}}}
          path: generated/${{{{ matrix.target }}}}/build/allure-results

""".format(java_matrix=", ".join(f"'{t}'" for t in java_targets))

    if ts_targets:
        workflow += """  typescript-tests:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        target: [{ts_matrix}]
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        working-directory: generated/${{{{ matrix.target }}}}
        run: npm ci
      - name: Run tests
        working-directory: generated/${{{{ matrix.target }}}}
        run: npm test
      - name: Upload Allure Results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: allure-results-${{{{ matrix.target }}}}
          path: generated/${{{{ matrix.target }}}}/allure-results

""".format(ts_matrix=", ".join(f"'{t}'" for t in ts_targets))

    workflow += """  allure-report:
    needs: [{needs}]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Download all artifacts
        uses: actions/download-artifact@v4
        with:
          path: allure-results
          pattern: allure-results-*
          merge-multiple: true
      - name: Generate Allure Report
        uses: simple-elf/allure-report-action@master
        with:
          allure_results: allure-results
          allure_report: allure-report
      - name: Publish to GitHub Pages
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{{{ secrets.GITHUB_TOKEN }}}}
          publish_dir: allure-report
""".format(needs=", ".join(
        ["java-tests"] * bool(java_targets) + ["typescript-tests"] * bool(ts_targets)
    ))

    workflow_path = workflows_dir / "matrix-test.yml"
    workflow_path.write_text(workflow, encoding="utf-8")

    return {
        "workflow_path": str(workflow_path),
        "targets": targets,
        "java_targets": java_targets,
        "typescript_targets": ts_targets,
    }


def add_codegen_parser(sub: argparse._SubParsersAction) -> None:
    """Add codegen subcommand to CLI parser."""
    codegen = sub.add_parser(
        "codegen",
        help="Cross-language test code generation (crystallization)",
    )
    codegen_sub = codegen.add_subparsers(dest="codegen_command", required=True)

    extract = codegen_sub.add_parser(
        "extract",
        help="Extract meta-schema from pytest tests",
    )
    extract.add_argument("tests_dir", help="Path to pytest tests directory")
    extract.add_argument("--name", help="Suite name (default: parent directory name)")
    extract.add_argument("--version", default="1.0.0", help="Suite version")
    extract.add_argument("--description", help="Suite description")
    extract.add_argument("--output", "-o", help="Output JSON file path")
    extract.add_argument("--json", action="store_true", help="Full JSON output to stdout")
    extract.set_defaults(func=cmd_codegen_extract)

    generate = codegen_sub.add_parser(
        "generate",
        help="Generate test project from meta-schema or pytest tests",
    )
    generate.add_argument("--target", "-t", required=True, help="Target: java-junit5-gradle, typescript-vitest, etc.")
    generate.add_argument("--schema", "-s", help="Path to meta-schema JSON")
    generate.add_argument("--tests-dir", help="Path to pytest tests (extract on-the-fly)")
    generate.add_argument("--name", help="Suite name")
    generate.add_argument("--output", "-o", required=True, help="Output directory")
    generate.add_argument("--overwrite", action="store_true", help="Overwrite existing files")
    generate.add_argument("--json", action="store_true", help="JSON output")
    generate.set_defaults(func=cmd_codegen_generate)

    targets = codegen_sub.add_parser(
        "targets",
        help="List available code generation targets",
    )
    targets.add_argument("--json", action="store_true", help="JSON output")
    targets.set_defaults(func=cmd_codegen_list_targets)

    matrix = codegen_sub.add_parser(
        "matrix",
        help="Generate CI matrix workflow for all/selected targets",
    )
    matrix.add_argument("--schema", "-s", help="Path to meta-schema JSON")
    matrix.add_argument("--tests-dir", help="Path to pytest tests")
    matrix.add_argument("--name", help="Suite name")
    matrix.add_argument("--targets", help="Comma-separated list of targets (default: all)")
    matrix.add_argument("--output", "-o", required=True, help="Output directory")
    matrix.add_argument("--json", action="store_true", help="JSON output")
    matrix.set_defaults(func=cmd_codegen_matrix)
