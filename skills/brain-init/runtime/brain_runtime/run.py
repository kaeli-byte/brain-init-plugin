from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
from typing import Any, Iterator

from .budget import FanoutRequest, advise_fanout, record_budget_metric
from .contracts import ArtifactRef, BudgetSpec, RunSpec
from .trace import (
    TraceEvent,
    append_event,
    open_regular_nofollow,
    read_json_nofollow,
    validate_event,
)


RUNTIME_VERSION = "0.1.0"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str, label: str) -> str:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"{label} must be a safe path component")
    return value


def _require_beneath(path: Path, root: Path, message: str) -> Path:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(message) from error
    return path


def _reject_ownership_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"symlinked runtime ownership path is not allowed: {path}")


def run_dir_for(vault: Path, run_id: str) -> Path:
    safe_run_id = _safe_component(run_id, "run ID")
    vault_root = vault.resolve()
    brain_root = vault_root / ".brain"
    lexical_runs_root = brain_root / "runs"
    lexical_run_dir = lexical_runs_root / safe_run_id
    for ownership_path in (brain_root, lexical_runs_root, lexical_run_dir):
        _reject_ownership_symlink(ownership_path)
    runs_root = _require_beneath(
        lexical_runs_root.resolve(),
        vault_root,
        "runtime run directory escapes the vault",
    )
    run_dir = _require_beneath(
        lexical_run_dir.resolve(),
        runs_root,
        "run ID escapes the vault run directory",
    )
    return run_dir


def _run_id(operation: str) -> str:
    _safe_component(operation, "operation")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{operation}-{secrets.token_hex(4)}"


def create_run(vault: Path, spec: RunSpec) -> str:
    vault_root = vault.resolve()
    run_id = _run_id(spec.operation)
    run_dir = run_dir_for(vault_root, run_id)
    inputs = []
    for input_ref in spec.input_refs:
        requested = Path(input_ref)
        if requested.is_absolute():
            raise ValueError(f"input reference must be vault-relative: {input_ref}")
        if ".." in requested.parts:
            raise ValueError(
                f"input reference must not contain parent traversal: {input_ref}"
            )
        resolved = (vault_root / requested).resolve()
        _require_beneath(
            resolved,
            vault_root,
            f"input reference escapes the vault: {input_ref}",
        )
        if not resolved.is_file():
            raise FileNotFoundError(
                f"input reference does not exist or is not a file: {input_ref}"
            )
        inputs.append({
            "path": resolved.relative_to(vault_root).as_posix(),
            "sha256": sha256_file(resolved),
        })
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = _timestamp()
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
    save_manifest(vault_root, run_id, manifest)
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
    return read_json_nofollow(manifest_path)


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


@contextmanager
def run_lock(vault: Path, run_id: str) -> Iterator[None]:
    run_dir = run_dir_for(vault, run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run state does not exist: {run_id}")
    descriptor = open_regular_nofollow(
        run_dir / ".lock",
        os.O_RDWR | os.O_APPEND | os.O_CREAT,
    )
    with os.fdopen(descriptor, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_json(path: Path, payload: Any) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.stem}-",
        suffix=".json",
        delete=False,
    ) as temporary_file:
        json.dump(payload, temporary_file, indent=2, sort_keys=True)
        temporary_file.write("\n")
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(path)


def plan_run(vault: Path, run_id: str, request: FanoutRequest) -> dict[str, Any]:
    vault_root = vault.resolve()
    with run_lock(vault_root, run_id):
        manifest = load_manifest(vault_root, run_id)
        if manifest["status"] != "running":
            raise ValueError(f"run is already completed: {run_id}")
        run_dir = run_dir_for(vault_root, run_id)
        decision = advise_fanout(
            request,
            BudgetSpec.from_dict(manifest["budget"]),
        )
        payload = {
            "exceeds_one_context": request.exceeds_one_context,
            "decision": decision.to_dict(),
        }
        _write_json(run_dir / "plan.json", payload)
        append_event(run_dir, TraceEvent(
            ts=_timestamp(),
            kind="plan.section_map",
            operation=manifest["operation"],
            run_id=run_id,
            label="section map recorded",
            data={"slice_count": len(request.slices)},
        ))
        append_event(run_dir, TraceEvent(
            ts=_timestamp(),
            kind="plan.fanout",
            operation=manifest["operation"],
            run_id=run_id,
            label="fanout advised",
            data={
                "mode": decision.mode,
                "max_workers": decision.max_workers,
                "reason": decision.reason,
            },
        ))
        return payload


def record_event(
    vault: Path,
    run_id: str,
    kind: str,
    label: str,
    data: dict[str, Any] | None = None,
) -> None:
    vault_root = vault.resolve()
    with run_lock(vault_root, run_id):
        manifest = load_manifest(vault_root, run_id)
        if manifest["status"] != "running":
            raise ValueError(f"run is already completed: {run_id}")
        append_event(run_dir_for(vault_root, run_id), TraceEvent(
            ts=_timestamp(),
            kind=kind,
            operation=manifest["operation"],
            run_id=run_id,
            label=label,
            data=data or {},
        ))
        updated = manifest
        if kind == "worker.finish":
            updated = record_budget_metric(updated, "workers")
        if label.startswith("attempt."):
            updated = record_budget_metric(updated, "attempts")
        if updated is not manifest:
            save_manifest(vault_root, run_id, updated)


def _shadow_verdict(run_dir: Path) -> bool | None:
    verification_path = run_dir / "verification.json"
    if not verification_path.exists() and not verification_path.is_symlink():
        return None
    payload = read_json_nofollow(verification_path)
    verdict = payload.get("accepted") if isinstance(payload, dict) else None
    if not isinstance(verdict, bool):
        raise ValueError("verification report accepted verdict must be a boolean")
    return verdict


def finish_run(vault: Path, run_id: str, shadow_verdict: bool | None = None) -> None:
    vault_root = vault.resolve()
    with run_lock(vault_root, run_id):
        manifest = load_manifest(vault_root, run_id)
        if manifest["status"] != "running":
            raise ValueError(f"run is already completed: {run_id}")
        run_dir = run_dir_for(vault_root, run_id)
        if shadow_verdict is None:
            shadow_verdict = _shadow_verdict(run_dir)
        completed_at = _timestamp()
        manifest["status"] = "completed"
        manifest["completed_at"] = completed_at
        manifest["shadow_verdict"] = shadow_verdict
        save_manifest(vault_root, run_id, manifest)
        append_event(run_dir, TraceEvent(
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
    with run_lock(vault_root, run_id):
        manifest = load_manifest(vault_root, run_id)
        if manifest["status"] != "running":
            raise ValueError(f"run is already completed: {run_id}")
        artifacts: list[ArtifactRef] = []
        declared_paths: set[str] = set()
        for path_text in paths:
            requested = Path(path_text)
            if requested.is_absolute():
                raise ValueError(f"artifact path must be vault-relative: {path_text}")
            resolved = (vault_root / requested).resolve()
            try:
                relative = resolved.relative_to(vault_root)
            except ValueError as error:
                raise ValueError(f"artifact path escapes vault: {path_text}") from error
            normalized_path = relative.as_posix()
            if normalized_path in declared_paths:
                raise ValueError(f"duplicate artifact path: {normalized_path}")
            if not resolved.is_file():
                raise FileNotFoundError(
                    f"artifact file does not exist: {normalized_path}"
                )
            declared_paths.add(normalized_path)
            artifacts.append(ArtifactRef(
                kind=_artifact_kind(relative),
                path=normalized_path,
                sha256=sha256_file(resolved),
            ))

        event = TraceEvent(
            ts=_timestamp(),
            kind="artifact.declare",
            operation=manifest["operation"],
            run_id=run_id,
            label="artifacts declared",
            data={
                "count": len(artifacts),
                "paths": [artifact.path for artifact in artifacts],
            },
        )
        validate_event(event)

        run_dir = run_dir_for(vault_root, run_id)
        _write_json(
            run_dir / "artifacts.json",
            {"artifacts": [artifact.to_dict() for artifact in artifacts]},
        )
        append_event(run_dir, event)
        return artifacts


def snapshot_tree(vault: Path, run_id: str, root: str) -> dict[str, Any]:
    vault_root = vault.resolve()
    with run_lock(vault_root, run_id):
        manifest = load_manifest(vault_root, run_id)
        if manifest["status"] != "running":
            raise ValueError(f"run is already completed: {run_id}")

        requested = Path(root)
        if requested.is_absolute():
            raise ValueError(f"snapshot root must be vault-relative: {root}")
        if ".." in requested.parts:
            raise ValueError(
                f"snapshot root must not contain parent traversal: {root}"
            )
        normalized_root = requested.as_posix()
        lexical_root = vault_root / requested
        if lexical_root.is_symlink():
            raise ValueError(f"snapshot root is a symlink: {root}")
        root_path = lexical_root.resolve()
        _require_beneath(
            root_path,
            vault_root,
            f"snapshot root escapes the vault: {root}",
        )
        if not root_path.is_dir():
            raise ValueError(f"snapshot root is not a directory: {root}")

        entries: list[dict[str, str]] = []
        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
            for name in dirnames:
                candidate = Path(dirpath) / name
                if candidate.is_symlink():
                    raise ValueError(
                        f"snapshot tree contains a symlinked directory: {candidate}"
                    )
            for name in filenames:
                candidate = Path(dirpath) / name
                if candidate.is_symlink():
                    raise ValueError(
                        f"snapshot tree contains a symlinked file: {candidate}"
                    )
                if candidate.suffix != ".md":
                    continue
                if not stat.S_ISREG(candidate.lstat().st_mode):
                    raise ValueError(
                        f"snapshot tree contains a non-regular markdown file: {candidate}"
                    )
                relative = candidate.relative_to(vault_root).as_posix()
                entries.append({"path": relative, "sha256": sha256_file(candidate)})
        entries.sort(key=lambda item: item["path"])

        payload: dict[str, Any] = {"root": normalized_root, "files": entries}
        run_dir = run_dir_for(vault_root, run_id)
        _write_json(run_dir / "baseline.json", payload)
        append_event(run_dir, TraceEvent(
            ts=_timestamp(),
            kind="snapshot.complete",
            operation=manifest["operation"],
            run_id=run_id,
            label="snapshot completed",
            data={"root": normalized_root, "file_count": len(entries)},
        ))
        return payload
