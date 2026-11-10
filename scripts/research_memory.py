#!/usr/bin/env python3
"""Search and maintain Kappa / Plaquette research records without network access or experiments.

Search is case-insensitive literal ranked OR matching, not semantic retrieval.
Validation checks declared metadata and provenance syntax, not source bytes.
records.json is the editable source; INDEX.md is generated from it.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

LOGGER = logging.getLogger("research_memory")
REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "docs" / "research_memory" / "records.json"
INDEX_PATH = CATALOG_PATH.with_name("INDEX.md")
HEX40 = re.compile(r"[0-9a-fA-F]{40}\Z")
REPOSITORY_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
RECORD_ID = re.compile(r"(?:KP|KAP|PLQ)-R[0-9]{3,}\Z")
VALIDATION_SCOPE = (
    "Declared metadata structure, identifiers, relationships and provenance "
    "syntax only; no remote lookup, source-byte verification, scientific "
    "validation or experimental execution."
)
SEARCH_MODE = "case-insensitive literal ranked OR; no semantic retrieval"


def emit(value: Any) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_catalog(data: Any) -> list[str]:
    """Return structural errors without reading any referenced source."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["catalog must be a JSON object"]

    def text_field(obj: dict[str, Any], key: str, where: str) -> None:
        if not nonempty_text(obj.get(key)):
            errors.append(f"{where}.{key} must be a nonempty string")

    def strings_field(obj: dict[str, Any], key: str, where: str) -> None:
        value = obj.get(key)
        if not isinstance(value, list) or any(not nonempty_text(x) for x in value):
            errors.append(f"{where}.{key} must be an array of nonempty strings")

    def commit_field(
        obj: dict[str, Any], key: str, where: str, *, nullable: bool = False
    ) -> None:
        if key not in obj:
            errors.append(
                f"{where}.{key} is required"
                + (
                    "; use explicit null when unknown or not applicable"
                    if nullable
                    else ""
                )
            )
            return
        value = obj[key]
        if nullable and value is None:
            return
        if not isinstance(value, str) or HEX40.fullmatch(value) is None:
            suffix = " or explicit null" if nullable else ""
            errors.append(f"{where}.{key} must be a full 40-hex commit SHA{suffix}")

    def commit_list(obj: dict[str, Any], key: str, where: str) -> None:
        value = obj.get(key)
        if not isinstance(value, list) or any(
            not isinstance(x, str) or HEX40.fullmatch(x) is None for x in value
        ):
            errors.append(f"{where}.{key} must be an array of full 40-hex commit SHAs")

    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        errors.append("schema_version must be integer 1")
    for key in ("repository", "recorded_on", "record_origin"):
        text_field(data, key, "catalog")
    repository = data.get("repository")
    if not isinstance(repository, str) or REPOSITORY_NAME.fullmatch(repository) is None:
        errors.append("repository must have owner/repository form")
    peer_repository = data.get("peer_repository")
    if (
        not isinstance(peer_repository, str)
        or REPOSITORY_NAME.fullmatch(peer_repository) is None
        or peer_repository == repository
    ):
        errors.append("peer_repository must name a distinct owner/repository")
    recorded_on = data.get("recorded_on")
    if isinstance(recorded_on, str):
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", recorded_on) is None:
                raise ValueError
            date.fromisoformat(recorded_on)
        except ValueError:
            errors.append("recorded_on must be a valid YYYY-MM-DD date")
    for key in ("main_base_commit", "source_snapshot_commit"):
        commit_field(data, key, "catalog")
    coverage = data.get("coverage_notes")
    if not (
        nonempty_text(coverage)
        or (
            isinstance(coverage, list)
            and bool(coverage)
            and all(nonempty_text(x) for x in coverage)
        )
    ):
        errors.append(
            "coverage_notes must be a nonempty string or array of nonempty strings"
        )
    records = data.get("records")
    if not isinstance(records, list) or not records:
        errors.append("records must be a nonempty array")
        return errors

    ids: set[str] = set()
    relationship_targets: list[tuple[str, str]] = []
    for number, record in enumerate(records):
        where = f"records[{number}]"
        if not isinstance(record, dict):
            errors.append(f"{where} must be an object")
            continue
        for key in (
            "id",
            "title",
            "kind",
            "workstream",
            "summary",
            "question",
            "motivation",
            "change",
            "interpretation",
            "execution_status",
            "evidence_level",
            "scientific_status",
            "approval_status",
            "status_basis",
        ):
            text_field(record, key, where)
        record_id = record.get("id")
        if isinstance(record_id, str):
            if RECORD_ID.fullmatch(record_id) is None:
                errors.append(f"{where}.id must be a stable identifier without spaces")
            if record_id in ids:
                errors.append(f"duplicate record id: {record_id}")
            ids.add(record_id)
        for key in (
            "conditions",
            "observed_results",
            "limits",
            "original_status_terms",
            "keywords",
        ):
            strings_field(record, key, where)

        provenance = record.get("provenance")
        if not isinstance(provenance, dict):
            errors.append(f"{where}.provenance must be an object")
        else:
            pwhere = f"{where}.provenance"
            if "repository" in provenance and (
                not isinstance(provenance["repository"], str)
                or REPOSITORY_NAME.fullmatch(provenance["repository"]) is None
            ):
                errors.append(f"{pwhere}.repository must have owner/repository form")
            for key in (
                "source_branch",
                "code_commit_note",
                "result_commit_note",
                "run_id_note",
            ):
                text_field(provenance, key, pwhere)
            for key in ("preparation_commits", "integration_commits"):
                commit_list(provenance, key, pwhere)
            for key in ("code_commit", "target_commit"):
                commit_field(provenance, key, pwhere, nullable=True)
            commit_field(provenance, "result_commit", pwhere, nullable=True)
            strings_field(provenance, "original_run_ids", pwhere)

        mirrors = record.get("mirrors", [])
        if not isinstance(mirrors, list):
            errors.append(f"{where}.mirrors must be an array")
        else:
            mirror_repositories: set[str] = set()
            for index, mirror in enumerate(mirrors):
                mwhere = f"{where}.mirrors[{index}]"
                if not isinstance(mirror, dict):
                    errors.append(f"{mwhere} must be an object")
                    continue
                mirror_repository = mirror.get("repository")
                if (
                    not isinstance(mirror_repository, str)
                    or REPOSITORY_NAME.fullmatch(mirror_repository) is None
                    or mirror_repository == repository
                ):
                    errors.append(f"{mwhere}.repository must name a distinct owner/repository")
                elif mirror_repository in mirror_repositories:
                    errors.append(f"{mwhere} repeats a mirror repository")
                else:
                    mirror_repositories.add(mirror_repository)
                if mirror.get("id") != record_id:
                    errors.append(f"{mwhere}.id must equal this record's stable ID")
                if mirror.get("path") != f"docs/research_memory/entries/{record_id}.md":
                    errors.append(f"{mwhere}.path must match the shared record ID")

        relations = record.get("relations")
        if not isinstance(relations, list):
            errors.append(f"{where}.relations must be an array")
        else:
            for index, relation in enumerate(relations):
                rwhere = f"{where}.relations[{index}]"
                if not isinstance(relation, dict):
                    errors.append(f"{rwhere} must be an object")
                    continue
                for key in ("id", "relation", "note"):
                    text_field(relation, key, rwhere)
                if nonempty_text(relation.get("id")):
                    relationship_targets.append((rwhere, relation["id"]))

        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{where}.evidence must be a nonempty array")
        else:
            for index, source in enumerate(evidence):
                ewhere = f"{where}.evidence[{index}]"
                if not isinstance(source, dict):
                    errors.append(f"{ewhere} must be an object")
                    continue
                for key in ("label", "role", "path"):
                    text_field(source, key, ewhere)
                source_repository = source.get("repository", repository)
                if (
                    not isinstance(source_repository, str)
                    or REPOSITORY_NAME.fullmatch(source_repository) is None
                ):
                    errors.append(f"{ewhere}.repository must have owner/repository form")
                commit_field(source, "commit", ewhere, nullable=True)
                if source.get("commit") is None:
                    text_field(source, "commit_note", ewhere)
                    if source.get("url") is not None:
                        errors.append(
                            f"{ewhere}.url must be null "
                            "until the source commit is known"
                        )
                else:
                    text_field(source, "url", ewhere)
                blob_sha = source.get("blob_sha")
                if not isinstance(blob_sha, str) or HEX40.fullmatch(blob_sha) is None:
                    errors.append(f"{ewhere}.blob_sha must be a full 40-hex blob SHA")
                path = source.get("path")
                if isinstance(path, str):
                    parts = path.split("/")
                    if (
                        not path
                        or PurePosixPath(path).is_absolute()
                        or "\\" in path
                        or any(part in ("", ".", "..") for part in parts)
                        or "\n" in path
                        or "\r" in path
                    ):
                        errors.append(
                            f"{ewhere}.path must be a relative repository file path"
                        )
                url = source.get("url")
                if (
                    isinstance(url, str)
                    and isinstance(path, str)
                    and isinstance(source.get("commit"), str)
                    and isinstance(source_repository, str)
                ):
                    try:
                        parsed = urlsplit(url)
                        expected = f"/{source_repository}/blob/{source['commit']}/{path}"
                        if (
                            parsed.scheme != "https"
                            or parsed.netloc != "github.com"
                            or parsed.query
                            or parsed.fragment
                            or unquote(parsed.path) != expected
                        ):
                            raise ValueError
                    except ValueError:
                        errors.append(
                            f"{ewhere}.url must match https://github.com/"
                            "repository/blob/commit/path exactly"
                        )
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append(f"{where}.artifacts must be an array")
        else:
            for index, artifact in enumerate(artifacts):
                awhere = f"{where}.artifacts[{index}]"
                if not isinstance(artifact, dict):
                    errors.append(f"{awhere} must be an object")
                    continue
                for key in ("label", "uri", "manifest_path", "verification", "note"):
                    text_field(artifact, key, awhere)
                uri = artifact.get("uri")
                if isinstance(uri, str) and not urlsplit(uri).scheme:
                    errors.append(f"{awhere}.uri must be a recorded artifact URI")
                manifest = artifact.get("manifest_path")
                manifest_repository = artifact.get("manifest_repository", repository)
                if (
                    not isinstance(manifest_repository, str)
                    or REPOSITORY_NAME.fullmatch(manifest_repository) is None
                ):
                    errors.append(f"{awhere}.manifest_repository must have owner/repository form")
                if isinstance(manifest, str) and (
                    not manifest
                    or PurePosixPath(manifest).is_absolute()
                    or any(part in ("", ".", "..") for part in manifest.split("/"))
                    or "\\" in manifest
                ):
                    errors.append(
                        f"{awhere}.manifest_path must be a repository file path"
                    )
                if (
                    isinstance(manifest, str)
                    and isinstance(evidence, list)
                    and not any(
                        isinstance(source, dict) and source.get("path") == manifest
                        and source.get("repository", repository) == manifest_repository
                        for source in evidence
                    )
                ):
                    errors.append(
                        f"{awhere}.manifest_path and manifest_repository must have a pinned entry in evidence"
                    )
                if artifact.get("verification") not in (
                    "recorded_in_repository_not_rechecked",
                    "object_listed_not_content_verified",
                    "selected_archive_members_reverified",
                    "exact_version_reverified",
                ):
                    errors.append(f"{awhere}.verification has an unsupported value")
        workstream = record.get("workstream")
        if isinstance(workstream, str) and (
            PurePosixPath(workstream).is_absolute()
            or any(part in ("", ".", "..") for part in workstream.split("/"))
            or "\\" in workstream
        ):
            errors.append(f"{where}.workstream must be a repository-relative path")
    for where, target in relationship_targets:
        if target not in ids:
            errors.append(f"{where}.id points to unknown record: {target}")
    return errors


def load_catalog() -> dict[str, Any]:
    with CATALOG_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def flattened_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(flattened_text(x) for x in value.values())
    if isinstance(value, list):
        return " ".join(flattened_text(x) for x in value)
    return value if isinstance(value, str) else ""


def filtered_records(
    data: dict[str, Any], kind: str | None, workstream: str | None = None
) -> list[dict[str, Any]]:
    return [
        record
        for record in data["records"]
        if (kind is None or record["kind"].casefold() == kind.casefold())
        and (
            workstream is None
            or workstream.casefold() in record["workstream"].casefold()
        )
    ]


def record_summary(record: dict[str, Any]) -> dict[str, Any]:
    summary = {
        key: record[key]
        for key in (
            "id",
            "title",
            "kind",
            "workstream",
            "summary",
            "execution_status",
            "evidence_level",
            "scientific_status",
            "approval_status",
        )
    }
    summary["entry"] = f"docs/research_memory/entries/{record['id']}.md"
    summary["mirrors"] = record.get("mirrors", [])
    return summary


def search_records(
    records: list[dict[str, Any]], terms: list[str], limit: int
) -> dict[str, Any]:
    unique_terms: dict[str, str] = {}
    for term in terms:
        unique_terms.setdefault(term.casefold(), term)
    matches = []
    for record in records:
        # One contribution per term and field group, regardless of repetition.
        groups = [
            (record["title"].casefold(), 8),
            (" ".join(record["keywords"]).casefold(), 8),
            (record["summary"].casefold(), 4),
            (record["question"].casefold(), 4),
            (
                flattened_text(
                    {
                        key: value
                        for key, value in record.items()
                        if key not in ("title", "keywords", "summary", "question")
                    }
                ).casefold(),
                1,
            ),
        ]
        matched_terms = []
        score = 0
        for normalized, original in unique_terms.items():
            term_score = sum(weight for text, weight in groups if normalized in text)
            if term_score:
                matched_terms.append(original)
                score += term_score
        if matched_terms:
            matches.append(
                {
                    **record_summary(record),
                    "score": score,
                    "matched_terms": matched_terms,
                }
            )
    matches.sort(key=lambda row: (-row["score"], -len(row["matched_terms"]), row["id"]))
    return {
        "status": "MATCHES" if matches else "NO_MATCH",
        "search_mode": SEARCH_MODE,
        "query_terms": list(unique_terms.values()),
        "total_matches": len(matches),
        "returned": min(len(matches), limit),
        "results": matches[:limit],
    }


def one_line(text: str) -> str:
    return " ".join(text.split())


def markdown_text(text: str) -> str:
    return one_line(text).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


KIND_LABELS = {
    "empirical_comparison": "실험 비교",
    "diagnostic_reanalysis": "재분석·진단",
    "evidence_correction": "정정·검증",
    "theory_audit": "이론 검토",
    "literature_review": "문헌 조사",
    "qualification": "적합성 검증",
    "archived_research": "과거 연구 묶음",
    "research_design": "연구 설계",
    "engineering_qualification": "구현·무결성 검증",
    "non_inference_audit": "비추론 감사",
    "source_discovery": "자료 조사",
}


def table_text(value: str) -> str:
    return markdown_text(value).replace("|", "\\|")


def render_index(data: dict[str, Any]) -> str:
    records = sorted(data["records"], key=lambda record: record["id"])
    base = data["source_snapshot_commit"]
    repo_url = f"https://github.com/{data['repository']}"
    lines = [
        f"# 연구 자산 색인 — {data['repository'].split('/')[-1]}",
        "",
        "질문과 관련된 기록을 먼저 고르고, ID를 열어 "
        "조건·관측·해석·한계와 원래 근거를 확인한다.",
        "이 목록과 ID별 페이지는 [records.json](records.json)에서 생성한다. "
        "[사용·기록 안내](README.md)를 따른다.",
        "",
        f"- 색인 갱신일: {data['recorded_on']}",
        f"- 연구 기록: {len(records)}개. 실행 횟수·독립 표본 수와 구분한다.",
        f"- 확인한 근거 스냅샷: [{base[:12]}]({repo_url}/commit/{base})",
        "- 현재 상태·남은 근거: [STATUS.md](STATUS.md)",
        "- 수록 범위와 점검: [COVERAGE.md](COVERAGE.md), [검증 기록](VALIDATION.md)",
        f"- 관련 저장소: [{data['peer_repository']}](https://github.com/{data['peer_repository']})",
        "- 같은 ID의 명시된 mirror는 같은 자산의 다른 보관 위치다. "
        "복사본을 독립 실행·독립 표본으로 세지 않는다. 새 기록의 mirror는 자동 생성하지 않는다.",
        "",
        "저장소 루트에서 `python3 scripts/research_memory.py search <핵심어>`로 찾고, "
        "`show <ID>`로 한 기록을 읽을 수 있다. "
        "`--workstream`과 `--kind`로 범위를 좁힌다.",
        "문자 일치 검색의 `NO_MATCH`는 관련 연구가 없다는 판정이 아니다. "
        "다른 표현이나 아래 목록도 확인한다.",
        "",
        "## 연구 기록",
        "",
        "| ID | 질문·핵심 결과 | 종류 | 연구 묶음 |",
        "|---|---|---|---|",
    ]
    for record in records:
        record_id = record["id"]
        workstream = record["workstream"]
        workstream_source = next(
            (
                source
                for source in record["evidence"]
                if source["commit"]
                and source["path"].startswith(workstream.rstrip("/") + "/")
            ),
            None,
        )
        workstream_url = (
            f"https://github.com/{workstream_source.get('repository', data['repository'])}"
            f"/tree/{workstream_source['commit']}/{workstream}"
            if workstream_source
            else f"../../{workstream}"
        )
        lines.append(
            f"| [{record_id}](entries/{record_id}.md) | "
            f"{table_text(record['title'])} | "
            f"{table_text(KIND_LABELS.get(record['kind'], record['kind']))} | "
            f"[{table_text(workstream.split('/')[-1])}]({workstream_url}) |"
        )
    lines.extend(["", "## 배경 자료와 복원 입구", ""])
    for label, path in (
        ("저장소 사용법과 연구 배경", "README.md"),
        ("보존된 QPU 결과와 실행 메타데이터", "data/qpu"),
        ("보존된 simulator 결과와 실행 메타데이터", "data/sim"),
    ):
        lines.append(f"- [{label}](../../{path})")
    lines.append(
        f"- [관련 저장소의 현재 색인](https://github.com/{data['peer_repository']}"
        "/blob/main/docs/research_memory/INDEX.md) — 현재 탐색 입구이며 고정 원문 근거와 구분한다."
    )
    lines.extend(["", "## 읽을 때의 범위", ""])
    coverage = data["coverage_notes"]
    for note in [coverage] if isinstance(coverage, str) else coverage:
        lines.append(f"- {markdown_text(note)}")
    return "\n".join(lines) + "\n"


def render_entry(data: dict[str, Any], record: dict[str, Any]) -> str:
    repository = data["repository"]
    provenance = record["provenance"]
    provenance_repository = provenance.get("repository", repository)
    repo_url = f"https://github.com/{provenance_repository}"

    def commit_link(sha: str) -> str:
        return f"[{sha[:12]}]({repo_url}/commit/{sha})"

    lines = [
        f"# {record['id']} — {markdown_text(record['title'])}",
        "",
        "[전체 색인](../INDEX.md) · [기록·조회 방법](../README.md)",
        "",
        markdown_text(record["summary"]),
        "",
        f"- 종류: {markdown_text(KIND_LABELS.get(record['kind'], record['kind']))} "
        f"(`{record['kind']}`)",
        f"- 연구 묶음: `{record['workstream']}`",
        f"- 실행·조사 상태: {markdown_text(record['execution_status'])}",
        f"- 근거의 종류·수준: {markdown_text(record['evidence_level'])}",
        f"- 연구 판단: {markdown_text(record['scientific_status'])}",
        f"- 승인·진행 권한: {markdown_text(record['approval_status'])}",
        "- 원래 상태 표현: "
        f"{markdown_text(', '.join(record['original_status_terms']))}",
        f"- 상태 해석의 근거: {markdown_text(record['status_basis'])}",
    ]
    mirrors = record.get("mirrors", [])
    if mirrors:
        lines.extend(["", "## 같은 자산의 다른 보관 위치", ""])
        for mirror in mirrors:
            lines.append(
                f"- [{mirror['repository']} · {mirror['id']}]"
                f"(https://github.com/{mirror['repository']}/blob/main/{mirror['path']})"
            )
        lines.append(
            "현재 main의 같은 ID로 이동하는 탐색 링크다. 원문의 고정 commit·blob 근거는 아래에서 확인한다. "
            "같은 자산의 사본이므로 독립 실행이나 추가 표본으로 세지 않는다."
        )
    for heading, key in (
        ("질문", "question"),
        ("이유", "motivation"),
        ("시도·변경", "change"),
        ("조건", "conditions"),
        ("관측·확인한 내용", "observed_results"),
        ("해석", "interpretation"),
        ("한계와 미확인 사항", "limits"),
    ):
        lines.extend(["", f"## {heading}", ""])
        value = record[key]
        if isinstance(value, list):
            lines.extend(f"- {markdown_text(item)}" for item in value)
        else:
            lines.append(markdown_text(value))
    lines.extend(["", "## 실행 코드와 기록의 출처", ""])
    lines.append(f"- 이 절의 commit이 속한 저장소: `{provenance_repository}`")
    code = provenance["code_commit"]
    lines.append(
        "- 실행·구현 코드: "
        + (commit_link(code) + ". " if code else "")
        + markdown_text(provenance["code_commit_note"])
    )
    if provenance["target_commit"]:
        lines.append(f"- 검토 대상: {commit_link(provenance['target_commit'])}")
    lines.append(
        "- 결과·보고 스냅샷: "
        + (
            commit_link(provenance["result_commit"]) + ". "
            if provenance["result_commit"]
            else ""
        )
        + f"{markdown_text(provenance['result_commit_note'])}"
    )
    lines.append(f"- 당시 작업 브랜치: `{provenance['source_branch']}`")
    if provenance["preparation_commits"]:
        lines.append(
            "- 준비 기록: "
            + ", ".join(commit_link(sha) for sha in provenance["preparation_commits"])
        )
    if provenance["integration_commits"]:
        lines.append(
            "- 통합 기록: "
            + ", ".join(commit_link(sha) for sha in provenance["integration_commits"])
        )
    if provenance["original_run_ids"]:
        lines.append(
            "- 원 실행 ID: "
            + ", ".join(f"`{run_id}`" for run_id in provenance["original_run_ids"])
        )
    lines.append(f"- 실행 ID 설명: {markdown_text(provenance['run_id_note'])}")
    lines.extend(["", "## 원래 근거", ""])
    for source in record["evidence"]:
        if source["commit"]:
            lines.append(
                f"- [{markdown_text(source['label'])}]({source['url']}) — "
                f"{markdown_text(source['role'])}"
            )
        else:
            source_repository = source.get("repository", repository)
            source_label = (
                f"[{markdown_text(source['label'])}](../../../{source['path']})"
                if source_repository == repository
                else f"{markdown_text(source['label'])} — `{source_repository}:{source['path']}`"
            )
            lines.append(
                f"- {source_label} — "
                f"{markdown_text(source['role'])}; "
                f"고정 내용 blob `{source['blob_sha']}`. "
                f"{markdown_text(source['commit_note'])} "
                f"`python3 scripts/research_memory.py locate {record['id']}`는 "
                "이 저장소의 출처만 로컬 Git에서 찾고 외부 저장소 출처는 미조회로 표시한다."
            )
    lines.extend(["", "## 큰 자료의 위치와 보존 기록", ""])
    if not record["artifacts"]:
        lines.append(
            "이 기록에는 별도 외부 artifact 위치가 등록되어 있지 않다. "
            "Git의 근거 파일과 한계 설명을 확인한다."
        )
    for artifact in record["artifacts"]:
        manifest_source = next(
            (
                source
                for source in record["evidence"]
                if source["path"] == artifact["manifest_path"]
                and source.get("repository", repository) == artifact.get("manifest_repository", repository)
            ),
            None,
        )
        manifest_url = (
            manifest_source["url"]
            if manifest_source and manifest_source["url"]
            else (
                f"https://github.com/{manifest_source['repository']}/blob/main/{artifact['manifest_path']}"
                if manifest_source and manifest_source.get("repository", repository) != repository
                else f"../../../{artifact['manifest_path']}"
            )
        )
        lines.extend(
            [
                f"- **{markdown_text(artifact['label'])}**: `{artifact['uri']}`",
                f"  - [보존 manifest·receipt]({manifest_url})",
                f"  - 확인 수준: `{artifact['verification']}`. "
                f"{markdown_text(artifact['note'])}",
            ]
        )
        if manifest_source and manifest_source.get("repository", repository) != repository and not manifest_source["commit"]:
            lines.append("  - 외부 manifest 링크는 현재 main 탐색용이며, commit이 아직 고정되지 않았다.")
    lines.extend(["", "## 이전·후속 관계", ""])
    if not record["relations"]:
        lines.append("등록된 관계 없음. 관련 기록 검색과 원문을 함께 확인한다.")
    for relation in record["relations"]:
        lines.append(
            f"- [{relation['id']}]({relation['id']}.md) — "
            f"{markdown_text(relation['relation'])}: {markdown_text(relation['note'])}"
        )
    lines.extend(
        [
            "",
            "## 검색어",
            "",
            ", ".join(markdown_text(term) for term in record["keywords"]),
        ]
    )
    return "\n".join(lines) + "\n"


def generated_pages(data: dict[str, Any]) -> dict[Path, str]:
    pages = {INDEX_PATH: render_index(data)}
    for record in data["records"]:
        pages[INDEX_PATH.parent / "entries" / f"{record['id']}.md"] = render_entry(
            data, record
        )
    return pages


def maintain_generated_pages(data: dict[str, Any], *, check: bool) -> int:
    pages = generated_pages(data)
    stale = [
        path
        for path, content in pages.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    unexpected = sorted(set((INDEX_PATH.parent / "entries").glob("*.md")) - set(pages))
    if unexpected:
        LOGGER.error(
            "Unexpected entry pages exist; preserve history "
            "and reconcile catalog IDs explicitly."
        )
        emit(
            {
                "status": "UNEXPECTED_ENTRIES",
                "paths": [str(path) for path in unexpected],
                "written": False,
            }
        )
        return 1
    if check:
        emit(
            {
                "status": "STALE" if stale else "CURRENT",
                "page_count": len(pages),
                "stale_paths": [str(path.relative_to(REPO_ROOT)) for path in stale],
                "written": False,
            }
        )
        return 1 if stale else 0
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as destination:
            destination.write(pages[path])
    emit(
        {
            "status": "RENDERED" if stale else "UNCHANGED",
            "page_count": len(pages),
            "written_count": len(stale),
        }
    )
    return 0


def positive_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if result < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def locate_sources(data: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Find exact evidence blobs in local history without fetch or mutation."""

    def git(*arguments: str) -> str | None:
        process = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        return process.stdout.strip() if process.returncode == 0 else None

    if git("rev-parse", "--show-toplevel") is None:
        return {
            "status": "NO_LOCAL_GIT_HISTORY",
            "record": record["id"],
            "written": False,
        }
    results = []
    for source in record["evidence"]:
        pinned = source["commit"].lower() if source["commit"] else None
        expected = source["blob_sha"].lower()
        source_repository = source.get("repository", data["repository"])
        if source_repository != data["repository"]:
            results.append(
                {
                    "repository": source_repository,
                    "path": source["path"],
                    "blob_sha": expected,
                    "observed_object_sha": None,
                    "status": "EXTERNAL_REPOSITORY_NOT_SEARCHED",
                    "pinned_commit": pinned,
                    "commit": None,
                    "url": source.get("url"),
                }
            )
            continue
        candidates = (
            [pinned]
            if pinned
            else (
                git("log", "--all", "--format=%H", "--", source["path"]) or ""
            ).splitlines()
        )
        match = None
        status = "NOT_IN_LOCAL_HISTORY"
        actual_blob = None
        if pinned and git("cat-file", "-t", pinned) != "commit":
            status = "PINNED_COMMIT_NOT_AVAILABLE"
            candidates = []
        for commit in candidates:
            if not HEX40.fullmatch(commit):
                continue
            actual = git("rev-parse", "--verify", f"{commit}:{source['path']}")
            if actual is None:
                if pinned:
                    status = "PATH_NOT_AT_COMMIT"
                continue
            actual = actual.lower()
            if actual == expected or pinned:
                actual_blob = actual
                if git("cat-file", "-t", actual) != "blob":
                    status = "NOT_A_BLOB"
                    continue
            if actual == expected:
                match = commit
                status = "FOUND"
                break
            if pinned:
                status = "BLOB_MISMATCH"
        results.append(
            {
                "repository": source_repository,
                "path": source["path"],
                "blob_sha": expected,
                "observed_object_sha": actual_blob,
                "status": status,
                "pinned_commit": pinned,
                "commit": match,
                "url": f"https://github.com/{data['repository']}/blob/{match}/{source['path']}"
                if match
                else None,
            }
        )
    return {
        "status": "FOUND"
        if all(row["commit"] for row in results)
        else "UNRESOLVED_SOURCES",
        "record": record["id"],
        "sources": results,
        "written": False,
        "scope": "Exact path/blob lookup only; "
        "no fetch, authorization or scientific validation.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find and maintain Kappa / Plaquette research records "
        "without network or experiments.",
        epilog="Search is case-insensitive literal ranked OR matching, "
        "not semantic retrieval.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list concise records as JSON")
    listing.add_argument("--kind", help="filter by record kind")
    listing.add_argument(
        "--workstream", help="filter by a workstream path or substring"
    )
    search = commands.add_parser("search", help="rank literal OR term matches")
    search.add_argument(
        "terms", nargs="+", help="literal terms; quote phrases to keep them together"
    )
    search.add_argument("--kind", help="filter by record kind")
    search.add_argument("--workstream", help="filter by a workstream path or substring")
    search.add_argument("--limit", type=positive_integer, default=5)
    showing = commands.add_parser("show", help="show one full record as JSON")
    showing.add_argument("id", help="exact stable record ID")
    locating = commands.add_parser(
        "locate", help="find exact evidence blobs in local Git history without writing"
    )
    locating.add_argument("id", help="exact stable record ID")
    commands.add_parser(
        "validate", help="check declared structure and provenance syntax only"
    )
    render = commands.add_parser(
        "render",
        help="generate the compact index and per-record pages from records.json",
    )
    render.add_argument(
        "--check", action="store_true", help="check all generated pages without writing"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "search":
        args.terms = [term.strip() for term in args.terms if term.strip()]
        if not args.terms:
            parser.error("search requires at least one nonempty literal term")
    try:
        data = load_catalog()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        LOGGER.error("Cannot load %s: %s", CATALOG_PATH, exc)
        return 1
    errors = validate_catalog(data)
    if errors:
        LOGGER.error("Catalog validation failed with %d error(s).", len(errors))
        emit(
            {
                "status": "INVALID",
                "validation_scope": VALIDATION_SCOPE,
                "errors": errors,
            }
        )
        return 1
    if args.command == "validate":
        emit(
            {
                "status": "VALID",
                "record_count": len(data["records"]),
                "validation_scope": VALIDATION_SCOPE,
            }
        )
    elif args.command == "list":
        records = filtered_records(data, args.kind, args.workstream)
        emit(
            {
                "status": "OK",
                "kind": args.kind,
                "workstream": args.workstream,
                "record_count": len(records),
                "records": [
                    {
                        key: value
                        for key, value in record_summary(record).items()
                        if key != "summary"
                    }
                    for record in records
                ],
            }
        )
    elif args.command == "search":
        result = search_records(
            filtered_records(data, args.kind, args.workstream), args.terms, args.limit
        )
        result["kind"] = args.kind
        result["workstream"] = args.workstream
        emit(result)
    elif args.command in ("show", "locate"):
        record = next((r for r in data["records"] if r["id"] == args.id), None)
        if record is None:
            LOGGER.error("Unknown record ID: %s", args.id)
            return 1
        if args.command == "show":
            emit(record)
        else:
            try:
                result = locate_sources(data, record)
            except OSError as exc:
                LOGGER.error("Cannot read local Git history: %s", exc)
                return 1
            emit(result)
            return 0 if result["status"] == "FOUND" else 1
    elif args.command == "render":
        try:
            return maintain_generated_pages(data, check=args.check)
        except (OSError, UnicodeError) as exc:
            LOGGER.error("Cannot access generated research-memory pages: %s", exc)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
