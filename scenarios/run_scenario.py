"""
Scenario Runner for Multi-Session Realistic Support Journeys.

Executes declarative sessions in sequence, demonstrating:
1. Multi-turn support ticket intake and invoice lookup.
2. Payment method update (`update_payment_info`).
3. Cross-session unprompted recall of customer facts and tool memories.

Usage:
  python scenarios/run_scenario.py
  python scenarios/run_scenario.py --provider openai
  python scenarios/run_scenario.py --provider anthropic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.config import AgentConfig
from agent.core import AgentCore
from agent.logger import setup_logging
from scenarios.sample_sessions import SAMPLE_SESSIONS


def run_all_scenarios(provider: str | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = AgentConfig()
    if provider:
        config.model_provider = provider

    setup_logging(logs_dir=config.logs_dir)
    agent = AgentCore(config=config)

    print("\n" + "=" * 80)
    print("  [SCENARIO RUNNER] - EXECUTING MULTI-SESSION SCENARIOS (PHASE 1)")
    print("=" * 80)
    print(f"  Model Provider: {agent.config.model_provider}")
    print(f"  SQLite Store:   {agent.config.sqlite_db_path}")
    print(f"  ChromaDB Store: {agent.config.chroma_persist_dir}")
    print("=" * 80 + "\n")

    for s_idx, session in enumerate(SAMPLE_SESSIONS, 1):
        print(f"\n{'#' * 80}")
        print(f"  SESSION {s_idx}: {session.session_id} (Customer: {session.customer_id})")
        print(f"  {session.description}")
        print(f"{'#' * 80}\n")

        for t_idx, turn in enumerate(session.turns, 1):
            print(f"[Turn {t_idx}] User: \"{turn.user_message}\"")
            reply = agent.run_turn(
                user_message=turn.user_message,
                session_id=session.session_id,
                customer_id=session.customer_id,
            )
            print(f"[Turn {t_idx}] Agent: \"{reply}\"\n")
            print("-" * 80)

    print("\n" + "=" * 80)
    print("  [DONE] ALL SCENARIO SESSIONS COMPLETED SUCCESSFULLY")
    print("  You can now inspect the resulting memory state with:")
    print("    python inspect_memory.py --customer-id CUST-402")
    print("    python inspect_memory.py --source tool_output:update_payment_info")
    print("    python view_logs.py --tail 25")
    print("=" * 80 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-session realistic agent scenarios")
    parser.add_argument("--provider", default=None, help="Override model provider (mock, openai, anthropic, ollama)")
    args = parser.parse_args()

    run_all_scenarios(provider=args.provider)


if __name__ == "__main__":
    main()
