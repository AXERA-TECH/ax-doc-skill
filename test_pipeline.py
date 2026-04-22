#!/usr/bin/env python3
"""End-to-end validator for rtd-to-chunk -> chunk-to-db -> pulsar2-doc-search workflows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class CmdResult:
    cmd: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    parsed_json: dict[str, Any] | None


def _print_step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def _print_cmd_result(name: str, result: CmdResult) -> None:
    _print_step(name)
    print(f"cwd: {result.cwd}", flush=True)
    print("cmd:", " ".join(result.cmd), flush=True)
    print(f"returncode: {result.returncode}", flush=True)
    if result.stdout.strip():
        print("--- stdout ---", flush=True)
        print(result.stdout.strip(), flush=True)
    if result.stderr.strip():
        print("--- stderr ---", flush=True)
        print(result.stderr.strip(), flush=True)
    if result.parsed_json is not None:
        print("--- parsed_json ---", flush=True)
        print(json.dumps(result.parsed_json, ensure_ascii=False, indent=2), flush=True)


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="test_chunk_db_pipeline")
    parser.add_argument(
        "--repo-url",
        default="https://github.com/AXERA-TECH/pulsar2-docs",
        help="GitHub repo/tree URL passed to rtd-to-chunk.",
    )
    parser.add_argument(
        "--run-id",
        default=f"pulsar2_test_{_now_tag()}",
        help="Run id for rtd-to-chunk output folder.",
    )
    parser.add_argument(
        "--providers",
        default="none,openai",
        help="Comma separated embedding providers for build_db tests.",
    )
    parser.add_argument(
        "--table-base",
        default="pulsar2-doc-test",
        help="Base table name used for build_db/server_db tests.",
    )
    parser.add_argument(
        "--query",
        default="quick start",
        help="Search query used for server_db actions.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Result limit for search actions.",
    )
    return parser.parse_args()


def _run_cmd(cmd: list[str], cwd: Path) -> CmdResult:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    parsed = _extract_json(proc.stdout)
    return CmdResult(
        cmd=cmd,
        cwd=str(cwd),
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        parsed_json=parsed,
    )


def _extract_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _ensure_chunk_output(chunk_dir: Path) -> tuple[bool, str]:
    if not chunk_dir.exists() or not chunk_dir.is_dir():
        return False, f"chunk output dir missing: {chunk_dir}"
    files = [p for p in chunk_dir.glob("*.json") if not p.name.startswith("_")]
    if not files:
        return False, f"no chunk json found in: {chunk_dir}"
    return True, f"chunk files={len(files)}"


def _action_expectation(provider: str, action: str) -> tuple[str, str | None]:
    if action in {"vector-search", "hybrid-search"} and provider == "none":
        return "error", "embedding-provider openai"
    return "ok", None


def main() -> int:
    args = _parse_args()
    root = Path(__file__).resolve().parent

    rtd_scripts = root / "rtd-to-chunk" / "scripts"
    chunk_scripts = root / "chunk-to-db" / "scripts"
    search_scripts = root / "pulsar2-doc-search" / "scripts"
    chunk_output_root = rtd_scripts / "tmp"
    chunk_output_dir = chunk_output_root / args.run_id
    assets_dir = root / "pulsar2-doc-search" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    report_path = assets_dir / f"test_report_{args.run_id}.json"

    providers = [item.strip() for item in args.providers.split(",") if item.strip()]
    report: dict[str, Any] = {
        "status": "running",
        "repo_url": args.repo_url,
        "run_id": args.run_id,
        "chunk_output_dir": str(chunk_output_dir),
        "providers": providers,
        "steps": {},
    }

    rtd_cmd = [
        sys.executable,
        str(rtd_scripts / "execute.py"),
        "--input-url",
        args.repo_url,
        "--output-dir",
        str(chunk_output_root),
        "--router-mode",
        "rule",
        "--max-concurrency",
        "4",
        "--run-id",
        args.run_id,
    ]
    rtd_res = _run_cmd(rtd_cmd, root)
    _print_cmd_result("rtd-to-chunk execute", rtd_res)
    report["steps"]["rtd_to_chunk"] = {
        "result": rtd_res.__dict__,
    }

    chunk_ok, chunk_msg = _ensure_chunk_output(chunk_output_dir)
    _print_step("chunk output validation")
    print(f"ok: {chunk_ok}", flush=True)
    print(f"message: {chunk_msg}", flush=True)
    report["steps"]["chunk_output_validation"] = {
        "ok": chunk_ok,
        "message": chunk_msg,
    }
    if rtd_res.returncode != 0 or not chunk_ok:
        report["status"] = "failed"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "failed", "report_path": str(report_path)}, ensure_ascii=False))
        return 1

    report["steps"]["build_db"] = {}
    report["steps"]["server_db"] = {}
    overall_ok = True
    for provider in providers:
        db_dir = assets_dir / f"pulsar2_rtd_test_{provider}_{args.run_id}"
        table = f"{args.table_base}_{provider}"
        build_cmd = [
            sys.executable,
            str(chunk_scripts / "build_db.py"),
            "--input-dir",
            str(chunk_output_dir),
            "--db-dir",
            str(db_dir),
            "--table",
            table,
            "--mode",
            "overwrite",
            "--embedding-provider",
            provider,
        ]
        build_res = _run_cmd(build_cmd, root)
        _print_cmd_result(f"build_db provider={provider}", build_res)
        report["steps"]["build_db"][provider] = {
            "db_dir": str(db_dir),
            "table": table,
            "result": build_res.__dict__,
            "ok": build_res.returncode == 0 and (build_res.parsed_json or {}).get("status") == "ok",
        }

        if build_res.returncode != 0:
            overall_ok = False
            continue

        actions = ["list-tables", "health", "fts-search", "vector-search", "hybrid-search"]
        report["steps"]["server_db"][provider] = {}
        for action in actions:
            cmd = [
                sys.executable,
                str(search_scripts / "server_db.py"),
                "--db-dir",
                str(db_dir),
                "--table",
                table,
                "--action",
                action,
                "--limit",
                str(args.limit),
                "--embedding-provider",
                provider,
            ]
            if action in {"fts-search", "vector-search", "hybrid-search"}:
                cmd.extend(["--query", args.query])

            action_res = _run_cmd(cmd, root)
            expected_status, contains_text = _action_expectation(provider, action)
            parsed = action_res.parsed_json or {}
            actual_status = str(parsed.get("status", ""))
            msg = str(parsed.get("message", ""))
            ok = action_res.returncode == (0 if expected_status == "ok" else 1) and actual_status == expected_status
            if contains_text and contains_text not in msg:
                ok = False
            _print_cmd_result(f"server_db provider={provider} action={action}", action_res)
            print(f"expected_status: {expected_status}", flush=True)
            print(f"actual_status: {actual_status}", flush=True)
            print(f"action_ok: {ok}", flush=True)
            report["steps"]["server_db"][provider][action] = {
                "expected_status": expected_status,
                "result": action_res.__dict__,
                "ok": ok,
            }
            if not ok:
                overall_ok = False

    report["status"] = "ok" if overall_ok else "failed"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "report_path": str(report_path),
                "run_id": args.run_id,
            },
            ensure_ascii=False,
        )
    )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
