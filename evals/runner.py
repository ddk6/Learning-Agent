from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.simple_agent import SimpleAgent  # noqa: E402
from app.config import AppConfig  # noqa: E402
from app.plugins import PluginContext, register_default_plugins  # noqa: E402
from app.storage.sqlite_store import (  # noqa: E402
    SQLiteAppStore,
    SQLiteMemoryStore,
    SQLiteProposalStore,
    SQLiteSessionState,
)
from app.tools.registry import ToolRegistry  # noqa: E402
from app.workflows.state_machine import StateMachine  # noqa: E402


DEFAULT_CASES_FILE = PROJECT_ROOT / "evals" / "minimal_cases.jsonl"
DEFAULT_KEEP_DIR = PROJECT_ROOT / "data" / "eval-runs"


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    user_input: str
    expected_contains: list[str]
    risk: str


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    category: str
    risk: str
    passed: bool
    missing: list[str]
    output: str
    error: str = ""


def main() -> int:
    args = parse_args()
    cases = load_cases(args.cases)

    if args.keep_db:
        database_file = create_kept_database_path()
        results = run_cases(cases, database_file=database_file, fail_fast=args.fail_fast)
        print(f"\nEval database kept at: {database_file}")
    else:
        # 默认使用一次性数据库，保证评测不会污染 data/learning_agent.db。
        with TemporaryDirectory(prefix="eval-", dir=PROJECT_ROOT / "data") as temp_dir:
            database_file = Path(temp_dir) / "learning_agent_eval.db"
            results = run_cases(cases, database_file=database_file, fail_fast=args.fail_fast)

    summary = build_summary(results)
    print_report(results, summary=summary, show_output=args.show_output)
    if args.results_file:
        append_results(args.results_file, results)
    if args.summary_file:
        write_summary(args.summary_file, summary, results)

    return 0 if all(result.passed for result in results) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the minimal offline eval cases against SimpleAgent.",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_FILE,
        help="JSONL eval case file. Defaults to evals/minimal_cases.jsonl.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed case.",
    )
    parser.add_argument(
        "--show-output",
        action="store_true",
        help="Print full output for each case.",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Keep the isolated eval SQLite database under data/eval-runs/.",
    )
    parser.add_argument(
        "--results-file",
        type=Path,
        help="Append JSONL eval results to the given file.",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        help="Write one JSON summary report to the given file.",
    )
    return parser.parse_args()


def load_cases(path: Path) -> list[EvalCase]:
    if not path.exists():
        raise FileNotFoundError(f"Eval case file not found: {path}")

    cases: list[EvalCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
        cases.append(parse_case(data, path=path, line_number=line_number))

    if not cases:
        raise ValueError(f"No eval cases found in {path}")
    return cases


def parse_case(data: Any, *, path: Path, line_number: int) -> EvalCase:
    if not isinstance(data, dict):
        raise ValueError(f"Eval case at {path}:{line_number} must be a JSON object.")

    expected_contains = data.get("expected_contains")
    if not isinstance(expected_contains, list) or not all(
        isinstance(item, str) for item in expected_contains
    ):
        raise ValueError(
            f"Eval case at {path}:{line_number} must define expected_contains as string list."
        )

    return EvalCase(
        id=required_string(data, "id", path, line_number),
        category=required_string(data, "category", path, line_number),
        user_input=required_string(data, "input", path, line_number),
        expected_contains=expected_contains,
        risk=str(data.get("risk") or "unknown"),
    )


def required_string(data: dict[str, Any], key: str, path: Path, line_number: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Eval case at {path}:{line_number} must define non-empty {key!r}.")
    return value


def run_cases(
    cases: list[EvalCase],
    *,
    database_file: Path,
    fail_fast: bool,
) -> list[EvalResult]:
    agent = build_eval_agent(database_file)
    results: list[EvalResult] = []

    for case in cases:
        try:
            output = agent.run(case.user_input)
            missing = [
                expected
                for expected in case.expected_contains
                if expected not in output
            ]
            result = EvalResult(
                case_id=case.id,
                category=case.category,
                risk=case.risk,
                passed=not missing,
                missing=missing,
                output=output,
            )
        except Exception as exc:
            result = EvalResult(
                case_id=case.id,
                category=case.category,
                risk=case.risk,
                passed=False,
                missing=case.expected_contains,
                output="",
                error=str(exc),
            )

        results.append(result)
        if fail_fast and not result.passed:
            break

    return results


def build_eval_agent(database_file: Path) -> SimpleAgent:
    # 评测只覆盖确定性本地路径，故意不调用 load_config()，避免读取 .env 或触发 LLM。
    config = AppConfig(
        project_root=PROJECT_ROOT,
        notes_dir=PROJECT_ROOT / "notes",
        data_dir=database_file.parent,
        memory_file=database_file.parent / "memory.json",
        proposal_file=database_file.parent / "proposals.json",
        database_file=database_file,
        openai_api_key="",
        openai_model="",
        openai_base_url="https://api.openai.com/v1",
        temperature=0.0,
        web_search_provider="auto",
        tavily_api_key="",
        brave_search_api_key="",
    )

    registry = ToolRegistry()
    sqlite_store = SQLiteAppStore(database_file)
    memory_store = SQLiteMemoryStore(sqlite_store)
    session_state = SQLiteSessionState(sqlite_store, session_id="eval-runner")
    state_machine = StateMachine.from_file(
        PROJECT_ROOT / "app" / "workflows" / "experiment_proposal_state_machine.json"
    )
    proposal_store = SQLiteProposalStore(sqlite_store, state_machine=state_machine)

    # Plugin registration mirrors app.main.build_agent to avoid eval/CLI drift.
    register_default_plugins(registry, PluginContext(config=config, memory_store=memory_store))

    return SimpleAgent(
        config=config,
        registry=registry,
        memory_store=memory_store,
        proposal_store=proposal_store,
        session_state=session_state,
        runtime_store=sqlite_store,
    )


def create_kept_database_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = DEFAULT_KEEP_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir / "learning_agent_eval.db"


def build_summary(results: list[EvalResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": calculate_pass_rate(passed, total),
        "by_category": group_summary(results, key=lambda result: result.category),
        "by_risk": group_summary(results, key=lambda result: result.risk),
    }


def group_summary(results: list[EvalResult], *, key: Any) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[EvalResult]] = {}
    for result in results:
        grouped.setdefault(str(key(result)), []).append(result)
    summary: dict[str, dict[str, Any]] = {}
    for name, items in sorted(grouped.items()):
        passed = sum(1 for item in items if item.passed)
        summary[name] = {
            "total": len(items),
            "passed": passed,
            "failed": len(items) - passed,
            "pass_rate": calculate_pass_rate(passed, len(items)),
        }
    return summary


def calculate_pass_rate(passed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(passed / total, 4)


def print_report(
    results: list[EvalResult],
    *,
    summary: dict[str, Any],
    show_output: bool,
) -> None:
    print("# Eval Report")
    print(
        f"Total: {summary['total']} | Passed: {summary['passed']} | "
        f"Failed: {summary['failed']} | Pass rate: {summary['pass_rate']:.2%}"
    )
    print("")

    print("## By Category")
    for category, item in summary["by_category"].items():
        print(
            f"- {category}: {item['passed']}/{item['total']} passed "
            f"({item['pass_rate']:.2%})"
        )
    print("")

    print("## By Risk")
    for risk, item in summary["by_risk"].items():
        print(
            f"- {risk}: {item['passed']}/{item['total']} passed "
            f"({item['pass_rate']:.2%})"
        )
    print("")

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case_id} ({result.category}, risk={result.risk})")
        if result.error:
            print(f"  error: {result.error}")
        if result.missing:
            print(f"  missing: {', '.join(repr(item) for item in result.missing)}")
        if show_output:
            print("  output:")
            print(indent_text(result.output or "<empty>", "    "))


def append_results(path: Path, results: list[EvalResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluated_at = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as file:
        for result in results:
            file.write(
                json.dumps(
                    {
                        "evaluated_at": evaluated_at,
                        "case_id": result.case_id,
                        "category": result.category,
                        "risk": result.risk,
                        "passed": result.passed,
                        "missing": result.missing,
                        "error": result.error,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def write_summary(path: Path, summary: dict[str, Any], results: list[EvalResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "cases": [
            {
                "case_id": result.case_id,
                "category": result.category,
                "risk": result.risk,
                "passed": result.passed,
                "missing": result.missing,
                "error": result.error,
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def indent_text(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


if __name__ == "__main__":
    raise SystemExit(main())
