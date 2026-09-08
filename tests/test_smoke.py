"""
Pytest smoke tests for Phase 0 Foundation Setup.

Verifies:
1. Provenance schema enforcement and SHA-256 integrity hash.
2. Memory persistence across simulated process restarts for both stores (SQLite & ChromaDB).
3. End-to-end agent turn with mock tool invocation and provenance tagging.
4. Structured JSONL logging to logs/agent.jsonl.
5. Indiscriminate recall behavior (Phase 0/1 requirement).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config import AgentConfig
from agent.core import AgentCore
from agent.llm import MockLLMClient
from agent.logger import setup_logging
from memory.manager import MemoryManager
from memory.schema import Provenance, SemanticMemoryItem, StructuredFact
from tools.registry import create_default_registry


@pytest.fixture
def temp_env(tmp_path: Path):
    """Provides isolated temp directories for database, chroma, and logs."""
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    chroma_dir = data_dir / "chroma"
    sqlite_path = data_dir / "memory.db"

    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    config = AgentConfig(
        model_provider="mock",
        data_dir=str(data_dir),
        logs_dir=str(logs_dir),
        sqlite_db_path=str(sqlite_path),
        chroma_persist_dir=str(chroma_dir),
        embedding_model_name="all-MiniLM-L6-v2",
    )
    setup_logging(logs_dir=str(logs_dir), log_filename="test_agent.jsonl")

    return {
        "config": config,
        "sqlite_path": str(sqlite_path),
        "chroma_dir": str(chroma_dir),
        "logs_dir": str(logs_dir),
        "log_file": logs_dir / "test_agent.jsonl",
    }


def test_provenance_schema_validation():
    """Verify that provenance schema sets all required fields and calculates SHA-256 hash."""
    prov = Provenance(
        source="user_chat",
        trust_tier="unclassified",
        session_id="session_test_01",
        actor="user",
        content_hash="abc123hash",
    )
    assert prov.source == "user_chat"
    assert prov.trust_tier == "unclassified"
    assert prov.session_id == "session_test_01"
    assert prov.actor == "user"
    assert prov.timestamp != ""

    fact = StructuredFact.create(
        entry_id="fact-1",
        entity="user_42",
        attribute="tier",
        value="enterprise",
        source="user_chat",
        session_id="session_test_01",
    )
    assert fact.provenance.trust_tier == "unclassified"
    assert fact.provenance.content_hash != ""

    item = SemanticMemoryItem.create(
        entry_id="mem-1",
        content="User requested a quota increase",
        source="user_chat",
        session_id="session_test_01",
    )
    assert item.provenance.source == "user_chat"
    assert len(item.provenance.content_hash) == 64  # Valid SHA-256 hex length


def test_memory_persistence_across_restart(temp_env):
    """
    Test that data written to both SQLite and Chroma persists when the
    memory manager is destroyed and re-instantiated on the same directory.
    """
    sqlite_path = temp_env["sqlite_path"]
    chroma_dir = temp_env["chroma_dir"]
    session_id = "persistence_test_session"

    # Step 1: Initialize manager and write to both stores
    manager1 = MemoryManager(
        sqlite_path=sqlite_path,
        chroma_dir=chroma_dir,
    )

    # Structured store write
    fact = manager1.record_fact(
        entity="customer_corp",
        attribute="billing_plan",
        value="Tier-3-Dedicated",
        source="tool_output:crm_sync",
        session_id=session_id,
        trust_tier="unclassified",
    )
    assert fact.entity == "customer_corp"

    # Vector store write
    mem = manager1.remember(
        content="Customer requested emergency downtime maintenance on Saturday.",
        source="user_chat",
        session_id=session_id,
        actor="user",
        trust_tier="unclassified",
    )
    assert mem.id != ""

    # Step 2: Simulate complete restart by deleting instance and creating a new one
    del manager1

    manager2 = MemoryManager(
        sqlite_path=sqlite_path,
        chroma_dir=chroma_dir,
    )

    # Step 3: Verify persistence in structured store
    recalled_fact = manager2.get_fact(entity="customer_corp", attribute="billing_plan")
    assert recalled_fact is not None
    assert recalled_fact.value == "Tier-3-Dedicated"
    assert recalled_fact.provenance.source == "tool_output:crm_sync"
    assert recalled_fact.provenance.trust_tier == "unclassified"
    assert recalled_fact.provenance.session_id == session_id

    # Step 4: Verify persistence in vector store
    recalled_session = manager2.recall_session(session_id=session_id)
    assert len(recalled_session["facts"]) == 1
    assert len(recalled_session["semantic_memories"]) == 1

    persisted_mem = recalled_session["semantic_memories"][0]
    assert "emergency downtime maintenance" in persisted_mem.content
    assert persisted_mem.provenance.source == "user_chat"
    assert persisted_mem.provenance.trust_tier == "unclassified"


def test_agent_turn_and_tool_call_with_provenance(temp_env):
    """
    Test full agent conversational turn with tool execution:
    1. Send user message asking for invoice INV-1001.
    2. Confirm tool is executed and result returned.
    3. Confirm tool output is persisted to memory with 'source=tool_output:invoice_lookup'.
    4. Confirm user message is persisted with 'source=user_chat'.
    5. Verify structured JSONL logging contains matching events.
    """
    config = temp_env["config"]
    agent = AgentCore(config=config)
    session_id = "agent_tool_test_session"

    response = agent.run_turn(
        user_message="Could you please check the status of invoice INV-1001?",
        session_id=session_id,
    )

    # Check response from mock client
    assert "INV-1001" in response
    assert "Acme Industrial Corp" in response

    # Check memory persistence
    recalled = agent.memory.recall_session(session_id=session_id)
    memories = recalled["semantic_memories"]

    # We expect 2 writes: 1 tool output write, 1 user input write
    sources = [m.provenance.source for m in memories]
    assert "tool_output:invoice_lookup" in sources
    assert "user_chat" in sources

    # Check provenance fields on tool output write
    tool_mem = next(m for m in memories if m.provenance.source == "tool_output:invoice_lookup")
    assert tool_mem.provenance.actor == "tool"
    assert tool_mem.provenance.trust_tier == "unclassified"
    assert "Acme Industrial Corp" in tool_mem.content

    # Check JSONL log file output
    log_file = Path(temp_env["log_file"])
    assert log_file.exists()

    log_lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    event_names = [line.get("event") for line in log_lines]

    assert "agent_turn_start" in event_names
    assert "tool_call_start" in event_names
    assert "tool_call_complete" in event_names
    assert "memory_write" in event_names
    assert "agent_turn_complete" in event_names


def test_indiscriminate_recall(temp_env):
    """
    Verify that in Phase 0/1, recall is strictly indiscriminate:
    It returns all records matching session_id without any trust filtering.
    """
    config = temp_env["config"]
    agent = AgentCore(config=config)
    session_id = "indiscriminate_session"

    # Write multiple memories with different sources & actors
    agent.memory.remember(
        content="Legitimate tool data",
        source="tool_output:invoice_lookup",
        session_id=session_id,
        actor="tool",
        trust_tier="unclassified",
    )
    agent.memory.remember(
        content="Potentially adversarial user instruction",
        source="user_chat",
        session_id=session_id,
        actor="user",
        trust_tier="unclassified",
    )

    recalled = agent.memory.recall_session(session_id=session_id)
    assert len(recalled["semantic_memories"]) == 2
    contents = [m.content for m in recalled["semantic_memories"]]
    assert "Legitimate tool data" in contents
    assert "Potentially adversarial user instruction" in contents
