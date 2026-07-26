from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
from typing import Any

from .contracts import ArtifactRef, RunSpec
from .trace import TraceEvent, append_event


RUNTIME_VERSION = "0.1.0"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_dir_for(vault: Path, run_id: str) -> Path:
    return vault / ".brain" / "runs" / run_id


def _run_id(operation: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{operation}-{secrets.token_hex(4)}"


def create_run(vault: Path, spec: RunSpec) -> str:
    run_id = _run_id(spec.operation)
    run_dir = run_dir_for(vault, run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = _timestamp()
    inputs = [
        {"path": input_ref, "sha256": sha256_file(vault / input_ref)}
        for input_ref in spec.input_refs
        if (vault / input_ref).is_file()
    ]
    manifest = {
        "run_id": run_id,
        "runtime_version": RUNTIME_VERSION,
        "operation": spec.operation,
        "mode": spec.mode,
        "profile": spec.profile,
        "status": "running",
        "started_at": started_at,
        "completed_at": None,
        "budget": spec.budget.to_dict(),
        "inputs": inputs,
        "metadata": spec.metadata,
        "metrics": {
            "workers": 0,
            "attempts": 0,
            "semantic_verifier_calls": 0,
        },
    }
    save_manifest(vault, run_id, manifest)
    append_event(run_dir, TraceEvent(
        ts=started_at,
        kind="run.start",
        operation=spec.operation,
        run_id=run_id,
        label="run created",
        data={"mode": spec.mode, "profile": spec.profile},
    ))
    return run_id


def load_manifest(vault: Path, run_id: str) -> dict[str, Any]:
    manifest_path = run_dir_for(vault, run_id) / "manifest.json"
    with manifest_path.open(encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


def save_manifest(vault: Path, run_id: str, manifest: dict[str, Any]) -> None:
    run_dir = run_dir_for(vault, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=run_dir,
        prefix=".manifest-",
        suffix=".json",
        delete=False,
    ) as temporary_file:
        json.dump(manifest, temporary_file, indent=2, sort_keys=True)
        temporary_file.write("\n")
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(run_dir / "manifest.json")


def finish_run(vault: Path, run_id: str, shadow_verdict: bool | None = None) -> None:
    manifest = load_manifest(vault, run_id)
    completed_at = _timestamp()
    manifest["status"] = "completed"
    manifest["completed_at"] = completed_at
    manifest["shadow_verdict"] = shadow_verdict
    save_manifest(vault, run_id, manifest)
    append_event(run_dir_for(vault, run_id), TraceEvent(
        ts=completed_at,
        kind="run.finish",
        operation=manifest["operation"],
        run_id=run_id,
        label="run completed",
        data={"shadow_verdict": shadow_verdict},
    ))


def _artifact_kind(relative_path: Path) -> str:
    parts = relative_path.parts
    if len(parts) < 3 or parts[0] != "wiki":
        return "wiki_page"
    return {
        "analyses": "analysis",
        "applications": "application",
        "claims": "claim",
        "companies": "company",
        "concepts": "concept",
        "indexes": "index",
        "industries": "industry",
        "logs": "log",
        "markets": "market",
        "patent-families": "patent-family",
        "people": "person",
        "processes": "process",
        "products": "product",
        "queries": "query",
        "regulations": "regulation",
        "sources": "source",
        "standards": "standard",
        "technologies": "technology",
    }.get(parts[1], "wiki_page")


def declare_artifacts(vault: Path, run_id: str, paths: list[str]) -> list[ArtifactRef]:
    vault_root = vault.resolve()
    artifacts: list[ArtifactRef] = []
    for path_text in paths:
        requested = Path(path_text)
        if requested.is_absolute():
            raise ValueError(f"artifact path must be vault-relative: {path_text}")
        resolved = (vault_root / requested).resolve()
        try:
            relative = resolved.relative_to(vault_root)
        except ValueError as error:
            raise ValueError(f"artifact path escapes vault: {path_text}") from error
        if not resolved.is_file():
            raise FileNotFoundError(f"artifact file does not exist: {relative.as_posix()}")
        artifacts.append(ArtifactRef(
            kind=_artifact_kind(relative),
            path=relative.as_posix(),
            sha256=sha256_file(resolved),
        ))

    run_dir = run_dir_for(vault_root, run_id)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=run_dir,
        prefix=".artifacts-",
        suffix=".json",
        delete=False,
    ) as temporary_file:
        json.dump(
            {"artifacts": [artifact.to_dict() for artifact in artifacts]},
            temporary_file,
            indent=2,
            sort_keys=True,
        )
        temporary_file.write("\n")
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(run_dir / "artifacts.json")

    manifest = load_manifest(vault_root, run_id)
    append_event(run_dir, TraceEvent(
        ts=_timestamp(),
        kind="artifact.declare",
        operation=manifest["operation"],
        run_id=run_id,
        label="artifacts declared",
        data={
            "count": len(artifacts),
            "paths": [artifact.path for artifact in artifacts],
        },
    ))
    return artifacts
