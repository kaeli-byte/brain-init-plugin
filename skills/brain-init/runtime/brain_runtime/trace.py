from dataclasses import asdict, dataclass, field
import errno
import json
import os
from pathlib import Path
import stat
from typing import Any


FORBIDDEN_TRACE_KEYS = {
    "messages", "transcript", "chain_of_thought", "source_text", "material", "full_text"
}
MAX_EVENT_BYTES = 8192


@dataclass(frozen=True)
class TraceEvent:
    ts: str
    kind: str
    operation: str
    run_id: str
    label: str
    data: dict[str, Any] = field(default_factory=dict)


def _forbidden_keys_in(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = FORBIDDEN_TRACE_KEYS.intersection(value)
        for child in value.values():
            keys.update(_forbidden_keys_in(child))
        return keys
    if isinstance(value, (list, tuple)):
        keys: set[str] = set()
        for child in value:
            keys.update(_forbidden_keys_in(child))
        return keys
    return set()


def validate_event(event: TraceEvent) -> bytes:
    forbidden_keys = _forbidden_keys_in(event.data)
    if forbidden_keys:
        names = ", ".join(sorted(forbidden_keys))
        raise ValueError(f"forbidden trace data keys: {names}")

    encoded = json.dumps(asdict(event), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES:
        raise ValueError(f"trace event exceeds {MAX_EVENT_BYTES} bytes")
    return encoded


def open_regular_nofollow(path: Path, flags: int) -> int:
    try:
        path_mode = path.lstat().st_mode
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(path_mode):
            raise ValueError(
                f"symlinked runtime ownership file is not allowed: {path}"
            )
        if not stat.S_ISREG(path_mode):
            raise ValueError(f"runtime ownership file is not regular: {path}")
    try:
        descriptor = os.open(
            path,
            flags | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ValueError(
                f"symlinked runtime ownership file is not allowed: {path}"
            ) from error
        if error.errno in {errno.EISDIR, errno.ENXIO}:
            raise ValueError(
                f"runtime ownership file is not regular: {path}"
            ) from error
        raise
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"runtime ownership file is not regular: {path}")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def read_json_nofollow(path: Path) -> Any:
    descriptor = open_regular_nofollow(path, os.O_RDONLY)
    with os.fdopen(descriptor, encoding="utf-8") as source_file:
        return json.load(source_file)


def append_event(run_dir: Path, event: TraceEvent) -> None:
    encoded = validate_event(event)
    descriptor = open_regular_nofollow(
        run_dir / "events.jsonl",
        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
    )
    with os.fdopen(descriptor, "ab") as events_file:
        events_file.write(encoded + b"\n")


def read_events(run_dir: Path) -> list[TraceEvent]:
    events_path = run_dir / "events.jsonl"
    if not events_path.exists() and not events_path.is_symlink():
        return []

    events: list[TraceEvent] = []
    descriptor = open_regular_nofollow(events_path, os.O_RDONLY)
    with os.fdopen(descriptor, encoding="utf-8") as events_file:
        for line in events_file:
            if line.strip():
                events.append(TraceEvent(**json.loads(line)))
    return events
