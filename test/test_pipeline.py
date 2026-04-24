from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

DEFAULT_REPO_URL = "https://github.com/AXERA-TECH/pulsar2-docs"
DEFAULT_TABLE = "pulsar2-doc_test"
DEFAULT_DB_SUBDIR = "pulsar2_rtd_test"
DEFAULT_QUERY = "quick start"


@dataclass(frozen=True)
class CmdResult:
    cmd: list[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str
    parsed_json: dict[str, Any] | None


@dataclass(frozen=True)
class PipelineArtifacts:
    root: Path
    run_id: str
    repo_url: str
    table: str
    db_dir: Path
    chunk_output_dir: Path
    report_path: Path


ROOT = Path(__file__).resolve().parents[1]
RTD_SCRIPT = ROOT / "rtd-to-chunk" / "scripts" / "chunk.py"
BUILD_DB_SCRIPT = ROOT / "chunk-to-db" / "scripts" / "build_db.py"
SERVER_DB_SCRIPT = ROOT / "pulsar2-doc-search" / "scripts" / "server_db.py"
CHUNK_OUTPUT_ROOT = ROOT / "rtd-to-chunk" / "scripts" / "tmp"
SEARCH_ASSETS_DIR = ROOT / "pulsar2-doc-search" / "assets"


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
    return CmdResult(
        cmd=cmd,
        cwd=cwd,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        parsed_json=_extract_last_json(proc.stdout),
    )


def _extract_last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _assert_cmd_ok(result: CmdResult, step_name: str) -> None:
    assert result.returncode == 0, (
        f"{step_name} failed\n"
        f"cmd: {' '.join(result.cmd)}\n"
        f"cwd: {result.cwd}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _assert_rtd_chunk_json_schema(file_path: Path) -> None:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{file_path}: root must be object"

    for field in ("run_id", "doc_id", "source", "url", "title", "chunks", "classification"):
        assert field in payload, f"{file_path}: missing field `{field}`"

    assert isinstance(payload["run_id"], str), f"{file_path}: run_id must be string"
    assert isinstance(payload["doc_id"], str), f"{file_path}: doc_id must be string"
    assert isinstance(payload["source"], str), f"{file_path}: source must be string"
    assert isinstance(payload["url"], str), f"{file_path}: url must be string"
    assert isinstance(payload["title"], str), f"{file_path}: title must be string"

    classification = payload["classification"]
    assert isinstance(classification, dict), f"{file_path}: classification must be object"
    for field in ("document_type", "confidence", "reasoning", "matched_signals"):
        assert field in classification, f"{file_path}: classification missing `{field}`"
    assert isinstance(classification["document_type"], str), f"{file_path}: document_type must be string"
    assert isinstance(classification["confidence"], (int, float)), f"{file_path}: confidence must be number"
    assert isinstance(classification["reasoning"], str), f"{file_path}: reasoning must be string"
    assert isinstance(classification["matched_signals"], list), f"{file_path}: matched_signals must be list"

    chunks = payload["chunks"]
    assert isinstance(chunks, list), f"{file_path}: chunks must be list"
    assert chunks, f"{file_path}: chunks must not be empty"
    for idx, chunk in enumerate(chunks):
        assert isinstance(chunk, dict), f"{file_path}: chunk[{idx}] must be object"
        for field in (
            "chunk_id",
            "doc_type",
            "chunk_type",
            "title",
            "url",
            "section_path",
            "display_text",
            "retrieval_text",
            "structured_data",
            "metadata",
        ):
            assert field in chunk, f"{file_path}: chunk[{idx}] missing `{field}`"

        assert isinstance(chunk["chunk_id"], str), f"{file_path}: chunk[{idx}].chunk_id must be string"
        assert isinstance(chunk["doc_type"], str), f"{file_path}: chunk[{idx}].doc_type must be string"
        assert isinstance(chunk["chunk_type"], str), f"{file_path}: chunk[{idx}].chunk_type must be string"
        assert isinstance(chunk["title"], str), f"{file_path}: chunk[{idx}].title must be string"
        assert isinstance(chunk["url"], str), f"{file_path}: chunk[{idx}].url must be string"
        assert isinstance(chunk["section_path"], list), f"{file_path}: chunk[{idx}].section_path must be list"
        assert isinstance(chunk["display_text"], str), f"{file_path}: chunk[{idx}].display_text must be string"
        assert isinstance(chunk["retrieval_text"], str), f"{file_path}: chunk[{idx}].retrieval_text must be string"
        assert chunk["structured_data"] is None or isinstance(
            chunk["structured_data"], dict
        ), f"{file_path}: chunk[{idx}].structured_data must be object|null"
        assert isinstance(chunk["metadata"], dict), f"{file_path}: chunk[{idx}].metadata must be object"


@pytest.fixture(scope="module")
def artifacts() -> PipelineArtifacts:
    run_id = f"pulsar2_test_{uuid.uuid4().hex[:10]}"
    db_dir = SEARCH_ASSETS_DIR / DEFAULT_DB_SUBDIR
    report_path = SEARCH_ASSETS_DIR / f"test_report_{run_id}.json"
    chunk_output_dir = CHUNK_OUTPUT_ROOT / run_id

    SEARCH_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    yield PipelineArtifacts(
        root=ROOT,
        run_id=run_id,
        repo_url=DEFAULT_REPO_URL,
        table=DEFAULT_TABLE,
        db_dir=db_dir,
        chunk_output_dir=chunk_output_dir,
        report_path=report_path,
    )

    shutil.rmtree(chunk_output_dir, ignore_errors=True)
    shutil.rmtree(CHUNK_OUTPUT_ROOT, ignore_errors=True)
    shutil.rmtree(db_dir, ignore_errors=True)
    report_path.unlink(missing_ok=True)


def _run_rtd_to_chunk(artifacts: PipelineArtifacts) -> CmdResult:
    cmd = [
        sys.executable,
        str(RTD_SCRIPT),
        "--input-url",
        artifacts.repo_url,
        "--output-dir",
        str(CHUNK_OUTPUT_ROOT),
        "--max-concurrency",
        "4",
        "--run-id",
        artifacts.run_id,
    ]
    return _run_cmd(cmd, artifacts.root)


def _run_build_db(artifacts: PipelineArtifacts) -> CmdResult:
    cmd = [
        sys.executable,
        str(BUILD_DB_SCRIPT),
        "--input-dir",
        str(artifacts.chunk_output_dir),
        "--db-dir",
        str(artifacts.db_dir),
        "--table",
        artifacts.table,
        "--mode",
        "overwrite",
        "--embedding-provider",
        "none",
    ]
    return _run_cmd(cmd, artifacts.root)


def _run_server_action(artifacts: PipelineArtifacts, action: str, *, query: str = "", limit: int = 3) -> CmdResult:
    cmd = [
        sys.executable,
        str(SERVER_DB_SCRIPT),
        "--db-dir",
        str(artifacts.db_dir),
        "--table",
        artifacts.table,
        "--action",
        action,
        "--limit",
        str(limit),
        "--embedding-provider",
        "none",
    ]
    if query:
        cmd.extend(["--query", query])
    return _run_cmd(cmd, artifacts.root)


def test_pipeline_e2e_with_default_rtd_repo(artifacts: PipelineArtifacts) -> None:
    rtd_result = _run_rtd_to_chunk(artifacts)
    _assert_cmd_ok(rtd_result, "rtd-to-chunk")

    assert artifacts.chunk_output_dir.exists(), f"chunk output dir missing: {artifacts.chunk_output_dir}"
    chunk_files = [p for p in artifacts.chunk_output_dir.glob("*.json") if not p.name.startswith("_")]
    assert chunk_files, f"no chunk json files in: {artifacts.chunk_output_dir}"
    for chunk_file in chunk_files:
        _assert_rtd_chunk_json_schema(chunk_file)

    build_result = _run_build_db(artifacts)
    _assert_cmd_ok(build_result, "build_db")
    parsed_build = build_result.parsed_json or {}
    assert parsed_build.get("status") == "ok", f"unexpected build_db output: {build_result.stdout}"
    assert parsed_build.get("table") == artifacts.table

    list_tables = _run_server_action(artifacts, "list-tables")
    _assert_cmd_ok(list_tables, "server_db list-tables")
    parsed_list = list_tables.parsed_json or {}
    assert parsed_list.get("status") == "ok"
    assert artifacts.table in parsed_list.get("tables", [])

    health = _run_server_action(artifacts, "health")
    _assert_cmd_ok(health, "server_db health")
    parsed_health = health.parsed_json or {}
    assert parsed_health.get("status") == "ok"
    assert parsed_health.get("table") == artifacts.table
    assert parsed_health.get("has_retrieval_text") is True

    fts = _run_server_action(artifacts, "fts-search", query=DEFAULT_QUERY)
    _assert_cmd_ok(fts, "server_db fts-search")
    parsed_fts = fts.parsed_json or {}
    assert parsed_fts.get("status") == "ok"
