"""
Main CLI entrypoint for the Memory Poisoning Lab.

Run interactive chat sessions with persistent memory across restarts:
  python main.py
  python main.py --session-id user_alice
  python main.py --message "What is the status of invoice INV-1001?"
"""

from __future__ import annotations

import argparse
import sys
from agent.config import AgentConfig
from agent.core import AgentCore
from agent.logger import setup_logging


def print_banner(config: AgentConfig, session_id: str) -> None:
    print("=" * 68)
    print("      🛡️  MEMORY POISONING LAB — PHASE 0 FOUNDATION  🛡️")
    print("=" * 68)
    print(f"  • Model Provider:    {config.model_provider}")
    print(f"  • Session ID:        {session_id}")
    print(f"  • Vector Store:      ChromaDB ({config.chroma_persist_dir})")
    print(f"  • Pinned Embedding:  {config.embedding_model_name}")
    print(f"  • Structured Store:  SQLite ({config.sqlite_db_path})")
    print(f"  • Log File:          {config.logs_dir}/agent.jsonl")
    print("-" * 68)
    print("  Special Commands:")
    print("    /memories       - View recalled vector memories for this session")
    print("    /facts          - View recalled structured facts")
    print("    /set <ent> <att> <val> - Manually write a structured fact")
    print("    /exit or /quit  - End interactive chat")
    print("=" * 68 + "\n")


def interactive_loop(agent: AgentCore, session_id: str) -> None:
    print_banner(agent.config, session_id)
    while True:
        try:
            user_input = input(f"[{session_id}] You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting session.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
            print("Goodbye.")
            break

        if user_input.lower() == "/memories":
            recalled = agent.memory.recall_session(session_id)
            items = recalled.get("semantic_memories", [])
            print(f"\n--- Stored Semantic Memories ({len(items)}) ---")
            for idx, item in enumerate(items, 1):
                print(f"{idx}. [{item.provenance.source} | trust:{item.provenance.trust_tier} | {item.provenance.timestamp}]")
                print(f"   {item.content}\n")
            continue

        if user_input.lower() == "/facts":
            recalled = agent.memory.recall_session(session_id)
            facts = recalled.get("facts", [])
            print(f"\n--- Stored Structured Facts ({len(facts)}) ---")
            for idx, fact in enumerate(facts, 1):
                print(f"{idx}. [{fact.provenance.source} | trust:{fact.provenance.trust_tier}] {fact.entity}.{fact.attribute} = {fact.value}")
            print()
            continue

        if user_input.lower().startswith("/set "):
            parts = user_input[5:].split(maxsplit=2)
            if len(parts) == 3:
                ent, att, val = parts
                agent.memory.record_fact(
                    entity=ent,
                    attribute=att,
                    value=val,
                    source="manual_cli",
                    session_id=session_id,
                    trust_tier="unclassified",
                )
                print(f"Fact recorded: {ent}.{att} = {val}\n")
            else:
                print("Usage: /set <entity> <attribute> <value>\n")
            continue

        response = agent.run_turn(user_message=user_input, session_id=session_id)
        print(f"\nAgent > {response}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Memory Poisoning Lab - Support Agent CLI")
    parser.add_argument("--session-id", default="session_demo", help="Session ID for persistence")
    parser.add_argument("--provider", default=None, help="Override model provider (mock, openai, anthropic, ollama)")
    parser.add_argument("--message", default=None, help="Execute a single turn and output response")
    args = parser.parse_args()

    config = AgentConfig()
    if args.provider:
        config.model_provider = args.provider

    setup_logging(logs_dir=config.logs_dir)
    agent = AgentCore(config=config)

    if args.message:
        reply = agent.run_turn(user_message=args.message, session_id=args.session_id)
        print(reply)
        sys.exit(0)

    interactive_loop(agent, args.session_id)


if __name__ == "__main__":
    main()
