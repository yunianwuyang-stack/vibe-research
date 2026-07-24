from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import atomic_write_json, canonical_json, sha256_bytes


class JournalError(ValueError):
    pass


def _event_hash(event: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in event.items() if key != "hash"}
    return sha256_bytes(canonical_json(unsigned))


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise JournalError(f"truncated_tail:{line_number}")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JournalError(f"invalid_json:{line_number}:{exc.msg}") from exc
            events.append(event)
    return events


def verify_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    previous = "0" * 64
    idempotency_keys: set[str] = set()
    for index, event in enumerate(events, start=1):
        if event.get("sequence") != index:
            raise JournalError(f"sequence:{index}")
        if event.get("prev_hash") != previous:
            raise JournalError(f"prev_hash:{index}")
        if event.get("hash") != _event_hash(event):
            raise JournalError(f"event_hash:{index}")
        key = event.get("idempotency_key")
        if not isinstance(key, str) or not key:
            raise JournalError(f"idempotency_key:{index}")
        if key in idempotency_keys:
            raise JournalError(f"duplicate_idempotency_key:{index}")
        idempotency_keys.add(key)
        previous = event["hash"]
    return {"events": len(events), "last_hash": previous}


def project(events: list[dict[str, Any]]) -> dict[str, Any]:
    verified = verify_events(events)
    state: dict[str, Any] = {
        "schema_version": "1.0",
        "last_event_id": None,
        "last_sequence": 0,
        "last_hash": "0" * 64,
        "phases": {},
        "findings": {},
    }
    for event in events:
        event_type = event["type"]
        payload = event.get("payload", {})
        if event_type == "phase_state":
            state["phases"][payload["phase_id"]] = payload["state"]
        elif event_type == "finding_state":
            state["findings"][payload["finding_id"]] = payload["state"]
        state["last_event_id"] = event["event_id"]
        state["last_sequence"] = event["sequence"]
        state["last_hash"] = event["hash"]
    if state["last_hash"] != verified["last_hash"]:
        raise JournalError("projection_hash")
    return state


def append_event(
    journal_path: Path,
    state_path: Path,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    events = read_events(journal_path)
    verified = verify_events(events)
    if any(event["idempotency_key"] == idempotency_key for event in events):
        raise JournalError("duplicate_idempotency_key")
    event = {
        "sequence": len(events) + 1,
        "event_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "idempotency_key": idempotency_key,
        "type": event_type,
        "payload": payload,
        "prev_hash": verified["last_hash"],
    }
    event["hash"] = _event_hash(event)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("ab") as handle:
        handle.write(canonical_json(event) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    events.append(event)
    atomic_write_json(state_path, project(events))
    return event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "append", "verify", "rebuild"))
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--type")
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--idempotency-key")
    args = parser.parse_args()
    try:
        if args.command == "init":
            if not args.journal.exists():
                args.journal.parent.mkdir(parents=True, exist_ok=True)
                args.journal.write_bytes(b"")
            atomic_write_json(args.state, project(read_events(args.journal)))
            result = {"verdict": "PASS", "events": len(read_events(args.journal))}
        elif args.command == "append":
            if not args.type or not args.idempotency_key:
                parser.error("append requires --type and --idempotency-key")
            event = append_event(
                args.journal,
                args.state,
                args.type,
                json.loads(args.payload),
                args.idempotency_key,
            )
            result = {"verdict": "PASS", "event_id": event["event_id"], "sequence": event["sequence"]}
        elif args.command == "verify":
            events = read_events(args.journal)
            verified = verify_events(events)
            saved_state = json.loads(args.state.read_text(encoding="utf-8"))
            if saved_state != project(events):
                raise JournalError("state_projection_mismatch")
            result = {"verdict": "PASS", **verified}
        else:
            events = read_events(args.journal)
            atomic_write_json(args.state, project(events))
            result = {"verdict": "PASS", "events": len(events)}
    except (JournalError, json.JSONDecodeError, KeyError, OSError) as exc:
        result = {"verdict": "FAIL", "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
