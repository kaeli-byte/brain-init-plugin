from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
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


def append_event(run_dir: Path, event: TraceEvent) -> None:
    forbidden_keys = _forbidden_keys_in(event.data)
    if forbidden_keys:
        names = ", ".join(sorted(forbidden_keys))
        raise ValueError(f"forbidden trace data keys: {names}")

    encoded = json.dumps(asdict(event), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES:
        raise ValueError(f"trace event exceeds {MAX_EVENT_BYTES} bytes")

    with (run_dir / "events.jsonl").open("ab") as events_file:
        events_file.write(encoded + b"\n")


def read_events(run_dir: Path) -> list[TraceEvent]:
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        return []

    events: list[TraceEvent] = []
    with events_path.open(encoding="utf-8") as events_file:
        for line in events_file:
            if line.strip():
                events.append(TraceEvent(**json.loads(line)))
    return events
