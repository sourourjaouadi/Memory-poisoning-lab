"""
Log Viewer & Timeline Visualizer for the Memory Poisoning Lab.

Parses structured JSONL records from `logs/agent.jsonl` and renders a clean,
human-readable chronological timeline for live auditing and testing.

Usage examples:
  python view_logs.py
  python view_logs.py --tail 10
  python view_logs.py --session-id session_acme_01
  python view_logs.py --event memory_write
  python view_logs.py --follow
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


def format_log_event(event: Dict[str, Any]) -> str:
    """Format a single JSON log record into a readable timeline item."""
    ts = event.get("timestamp", "").replace("T", " ")[:19]
    session = event.get("session_id", "GLOBAL")
    event_type = event.get("event", "unknown")

    prefix = f"{ts} [{session}]"

    if event_type == "agent_turn_start":
        snippet = event.get("user_message_snippet", "")
        cust = f" (Customer: {event['customer_id']})" if event.get("customer_id") else ""
        return f"{prefix} ▶ [TURN START]{cust} User: \"{snippet}\""

    elif event_type == "memory_read":
        facts_count = event.get("recalled_facts_count", 0)
        sem_count = event.get("recalled_semantic_count", 0)
        cust = f" (Customer: {event['customer_id']})" if event.get("customer_id") else ""
        return (
            f"{prefix} 📖 [MEMORY READ]{cust} Recalled: "
            f"{facts_count} facts (SQLite), {sem_count} memories (ChromaDB)"
        )

    elif event_type == "tool_call_start":
        tool_name = event.get("tool_name", "unknown")
        args_str = json.dumps(event.get("tool_args", {}))
        return f"{prefix} ⚡ [TOOL CALL] {tool_name}({args_str})"

    elif event_type == "tool_call_complete":
        tool_name = event.get("tool_name", "unknown")
        output = event.get("tool_output_snippet", "")
        return f"{prefix} ✔ [TOOL RESULT] {tool_name} -> {output}"

    elif event_type == "memory_write":
        mtype = event.get("memory_type", "memory")
        source = event.get("source", "unknown")
        trust = event.get("trust_tier", "unclassified")
        snippet = event.get("content_snippet", "") or event.get("value", "")
        h = event.get("content_hash", "")[:12]
        return (
            f"{prefix} 💾 [MEMORY WRITE] ({mtype.upper()}) source={source} "
            f"trust={trust} hash={h}.. -> \"{snippet}\""
        )

    elif event_type == "agent_turn_complete":
        latency = event.get("latency_ms", 0.0)
        snippet = event.get("response_snippet", "")
        return f"{prefix} ⏹ [TURN COMPLETE] ({latency}ms) Agent: \"{snippet}\"\n"

    else:
        # Generic event fallback
        return f"{prefix} • [{event_type.upper()}] {json.dumps(event)}"


def read_logs(file_path: Path) -> list[Dict[str, Any]]:
    """Read all valid JSON lines from log file."""
    if not file_path.exists():
        return []
    records = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def follow_logs(file_path: Path, session_id: Optional[str] = None, event_type: Optional[str] = None) -> None:
    """Stream new log events live as they are written (like tail -f)."""
    print(f"Streaming live events from {file_path} (Press Ctrl+C to stop)...")
    last_size = 0

    while True:
        try:
            if file_path.exists():
                curr_size = file_path.stat().st_size
                if curr_size > last_size:
                    with file_path.open("r", encoding="utf-8") as f:
                        f.seek(last_size)
                        new_lines = f.readlines()
                        last_size = curr_size

                        for line in new_lines:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                                if session_id and record.get("session_id") != session_id:
                                    continue
                                if event_type and record.get("event") != event_type:
                                    continue
                                print(format_log_event(record))
                            except Exception:
                                continue
            time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopped live log streaming.")
            break


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Timeline Log Viewer for Memory Poisoning Lab")
    parser.add_argument("--file", default="logs/agent.jsonl", help="Path to JSONL log file")
    parser.add_argument("--session-id", default=None, help="Filter by session ID")
    parser.add_argument("--event", default=None, help="Filter by event type (e.g. memory_write, tool_call_start)")
    parser.add_argument("--tail", type=int, default=30, help="Number of recent events to display (default: 30)")
    parser.add_argument("-f", "--follow", action="store_true", help="Live follow mode (tail -f)")

    args = parser.parse_args()
    log_path = Path(args.file)

    if args.follow:
        follow_logs(log_path, session_id=args.session_id, event_type=args.event)
        sys.exit(0)

    if not log_path.exists():
        print(f"[-] Log file not found at: {log_path}")
        sys.exit(0)

    records = read_logs(log_path)
    if args.session_id:
        records = [r for r in records if r.get("session_id") == args.session_id]
    if args.event:
        records = [r for r in records if r.get("event") == args.event]

    displayed = records[-args.tail:] if args.tail else records

    print("\n" + "=" * 90)
    print(f"  [AGENT LOG TIMELINE] — Showing {len(displayed)} events from {log_path}")
    if args.session_id:
        print(f"  Filter Session: {args.session_id}")
    if args.event:
        print(f"  Filter Event:   {args.event}")
    print("=" * 90 + "\n")

    for r in displayed:
        print(format_log_event(r))

    print("=" * 90)


if __name__ == "__main__":
    main()
