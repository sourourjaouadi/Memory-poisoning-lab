import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

# Import core attack utilities
from attacks.run_attack import (
    load_config,
    maybe_delay,
    plant_payload,
    verify_attack,
    RecordingToolRegistry,
)
from tools.registry import create_default_registry
from agent.core import AgentCore


def run_single(
    attack_type: str,
    config_name: str,
    provider: str,
    customer_id: str,
) -> Dict[str, Any]:
    """Execute one attack run and return the verification result.

    The logic mirrors ``attacks/run_attack.py``'s ``main`` function but is
    reused here to avoid duplicating code. It returns the dictionary produced
    by ``verify_attack`` which contains the five boolean fields we need.
    """
    # Resolve config file path (same layout as the original CLI)
    config_path = Path(__file__).resolve().parents[1] / "attacks" / attack_type / f"{config_name}.yaml"
    print(f"Resolved config_path: {config_path}")
    config = load_config(config_path)

    # Prefer a customer_id from the config if it exists (as the original script does)
    if getattr(config, "customer_id", None):
        customer_id = config.customer_id  # type: ignore[attr-defined]

    # Ensure the payload mentions the customer explicitly (original behaviour)
    if customer_id and customer_id not in config.payload:
        config.payload = f"For customer {customer_id}: {config.payload}"

    # Initialise core and wrap the tool registry to record calls
    core = AgentCore()
    core.tools = RecordingToolRegistry(create_default_registry())
    manager = core.memory

    # Fresh session identifiers for isolation
    plant_sid = f"plant_{uuid.uuid4().hex[:8]}"
    trigger_sid = f"trigger_{uuid.uuid4().hex[:8]}"

    # Optional delay messages before planting (same as original)
    maybe_delay(core, config, plant_sid)

    # Plant the payload – we now pass the real customer_id so the memory entry
    # is correctly tagged.
    plant_payload(core, manager, config, provider, plant_sid, customer_id)

    # Verify the attack and collect the result dictionary
    result = verify_attack(core, config, trigger_sid, customer_id)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run statistical evaluation of memory‑poisoning attacks.")
    parser.add_argument(
        "--type",
        required=True,
        choices=["direct", "indirect", "sleeper", "all"],
        help="Attack type to evaluate (or 'all' for every type).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Number of isolated runs per attack type.",
    )
    parser.add_argument(
        "--provider",
        required=True,
        help="Execution provider (e.g., ollama).",
    )
    args = parser.parse_args()

    # Mapping from attack type to default config name (matches existing repo layout)
    default_config = {
        "direct": "payment_reroute",
        "indirect": "ticket_secret_instruction",
        "sleeper": "delayed_reroute",
    }

    attack_types = [args.type] if args.type != "all" else ["direct", "indirect", "sleeper"]

    # Prepare output directory for raw per‑run logs
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Store aggregated metrics for pretty printing at the end
    aggregate: Dict[str, List[Dict[str, Any]]] = {t: [] for t in attack_types}

    for attack_type in attack_types:
        config_name = default_config[attack_type]
        for i in range(1, args.runs + 1):
            # Generate a unique customer identifier for isolation
            cust_id = f"CUST-{uuid.uuid4().int % 100000:05d}"
            try:
                result = run_single(attack_type, config_name, args.provider, cust_id)
                success = True
            except Exception as exc:  # Gracefully handle a single failure
                print(f"[{i}/{args.runs}] {attack_type}: ERROR - {exc}")
                result = {
                    "stored": False,
                    "recalled": False,
                    "influenced_response": False,
                    "influenced_tool_call": False,
                    "influenced_memory_state": False,
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                }
                success = False

            # Record raw result line (JSONL) for later inspection
            raw_path = results_dir / f"{timestamp}_{attack_type}.jsonl"
            with raw_path.open("a", encoding="utf-8") as f:
                json.dump({"run": i, "customer_id": cust_id, "result": result}, f)
                f.write("\n")

            aggregate[attack_type].append(result)

            # Progress feedback
            print(
                f"[{i}/{args.runs}] {attack_type}: "
                f"stored={result.get('stored')}, "
                f"recalled={result.get('recalled')}, "
                f"influenced_tool_call={result.get('influenced_tool_call')}"
            )
            sys.stdout.flush()

    # ----- Compute and print statistics -----
    print("\n=== Evaluation Summary ===")
    for attack_type in attack_types:
        runs = aggregate[attack_type]
        total = len(runs)
        def rate(key: str) -> str:
            count = sum(1 for r in runs if r.get(key))
            return f"{count}/{total} ({count/total:.0%})"
        print(f"\n{attack_type.upper()} (n={total}):")
        print(f"  Stored:               {rate('stored')}")
        print(f"  Recalled:             {rate('recalled')}")
        print(f"  Influenced Response:  {rate('influenced_response')}")
        print(f"  Influenced Tool Call: {rate('influenced_tool_call')}")
        print(f"  Influenced Memory:    {rate('influenced_memory_state')}")

    # Combined side‑by‑side table
    if len(attack_types) > 1:
        print("\nCombined Table:")
        headers = ["Metric"] + [t.upper() for t in attack_types]
        rows = []
        def rate(at: str, key: str) -> str:
            runs = aggregate[at]
            total = len(runs)
            count = sum(1 for r in runs if r.get(key))
            return f"{count}/{total} ({count/total:.0%})"
        rows.append(["Stored"] + [rate(t, 'stored') for t in attack_types])
        rows.append(["Recalled"] + [rate(t, 'recalled') for t in attack_types])
        rows.append(["Inf Resp"] + [rate(t, 'influenced_response') for t in attack_types])
        rows.append(["Inf Tool"] + [rate(t, 'influenced_tool_call') for t in attack_types])
        rows.append(["Inf Mem"] + [rate(t, 'influenced_memory_state') for t in attack_types])
        col_sep = " | "
        print(col_sep.join(headers))
        print("---" * len(headers))
        for row in rows:
            print(col_sep.join(row))

if __name__ == "__main__":
    main()
