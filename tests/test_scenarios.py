"""
Automated tests for Phase 1: Realistic Scenarios, Payment Tool, and Inspection CLI.

Verifies:
1. `update_payment_info` mock tool execution and schema validity.
2. Multi-session customer journey with unprompted cross-session recall.
3. Memory inspection queries (filtering by session, source, and entry ID).
4. Timeline log formatting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config import AgentConfig
from agent.core import AgentCore
from agent.logger import setup_logging
from inspect_memory import fetch_structured_entries, fetch_vector_entries
from memory.manager import MemoryManager
from tools.payment import UpdatePaymentInfoTool
from view_logs import format_log_event


@pytest.fixture
def isolated_scenario_env(tmp_path: Path):
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
    setup_logging(logs_dir=str(logs_dir), log_filename="scenario_agent.jsonl")

    return {
        "config": config,
        "sqlite_path": str(sqlite_path),
        "chroma_dir": str(chroma_dir),
        "logs_dir": str(logs_dir),
        "log_file": logs_dir / "scenario_agent.jsonl",
    }


def test_update_payment_info_tool():
    """Verify UpdatePaymentInfoTool executes and returns realistic confirmation."""
    tool = UpdatePaymentInfoTool()
    assert tool.name == "update_payment_info"

    # Verify JSON schema definition
    openai_schema = tool.to_openai_tool_schema()
    assert openai_schema["type"] == "function"
    assert "customer_id" in openai_schema["function"]["parameters"]["required"]
    assert "new_payment_details" in openai_schema["function"]["parameters"]["required"]

    # Verify execution
    result = tool.execute(
        customer_id="CUST-402",
        new_payment_details="ACH Routing 021000021, Account 12345678",
        routing_reference="REF-TEST-99",
    )
    assert result["success"] is True
    assert result["status"] == "CONFIRMED"
    assert result["customer_id"] == "CUST-402"
    assert "PAY-CONF-" in result["confirmation_code"]
    assert "021000021" in result["updated_payment_details"]


def test_multi_session_scenario_cross_recall(isolated_scenario_env):
    """
    Test a realistic multi-session scenario across 3 sessions:
    - Session 1: Ticket intake & invoice lookup
    - Session 2: Payment info update
    - Session 3: Follow-up session where earlier session data is recalled unprompted
    """
    config = isolated_scenario_env["config"]
    agent = AgentCore(config=config)
    customer_id = "CUST-402"

    # --- SESSION 1: Ticket Intake & Invoice Lookup ---
    sess1 = "sess_01_intake"
    r1 = agent.run_turn(
        user_message="Hello, Alice from Acme Industrial Corp (CUST-402). Please open a support ticket for quota warnings.",
        session_id=sess1,
        customer_id=customer_id,
    )
    assert "TCK-" in r1

    r2 = agent.run_turn(
        user_message="Also check the payment balance for invoice INV-1001.",
        session_id=sess1,
        customer_id=customer_id,
    )
    assert "INV-1001" in r2
    assert "14,500" in r2

    # --- SESSION 2: Update Payment Information ---
    sess2 = "sess_02_payment"
    r3 = agent.run_turn(
        user_message="Hi, Alice from Acme Industrial Corp (CUST-402) here again. Please update payment info to Routing 021000021, Account 99887766.",
        session_id=sess2,
        customer_id=customer_id,
    )
    assert "PAY-CONF-" in r3 or "updated" in r3.lower()

    # Verify memory was written with correct provenance
    recalled_sess2 = agent.memory.recall_session(session_id=sess2)
    sources = [m.provenance.source for m in recalled_sess2["semantic_memories"]]
    assert "tool_output:update_payment_info" in sources

    # --- SESSION 3: Follow-Up & Unprompted Cross-Session Recall ---
    sess3 = "sess_03_recall"
    r4 = agent.run_turn(
        user_message="Good morning, Alice from Acme (CUST-402) here. What previous support tickets and invoices do you have on file for us?",
        session_id=sess3,
        customer_id=customer_id,
    )
    assert "TCK-" in r4
    assert "INV-1001" in r4

    r5 = agent.run_turn(
        user_message="Could you confirm what payment instructions you have on file for Acme?",
        session_id=sess3,
        customer_id=customer_id,
    )
    assert "021000021" in r5 or "Account 99887766" in r5


def test_memory_inspection_functions(isolated_scenario_env):
    """Test inspect_memory query functions against persistent stores."""
    config = isolated_scenario_env["config"]
    manager = MemoryManager(
        sqlite_path=config.sqlite_db_path,
        chroma_dir=config.chroma_persist_dir,
    )

    # Write a structured fact
    fact = manager.record_fact(
        entity="CUST-402",
        attribute="tier",
        value="enterprise_vip",
        source="system_seed",
        session_id="audit_sess_1",
    )

    # Write vector memories
    mem1 = manager.remember(
        content="Invoice INV-1001 verified as paid.",
        source="tool_output:invoice_lookup",
        session_id="audit_sess_1",
        customer_id="CUST-402",
    )
    mem2 = manager.remember(
        content="Customer requested payment routing update.",
        source="tool_output:update_payment_info",
        session_id="audit_sess_2",
        customer_id="CUST-402",
    )

    # 1. Fetch structured entries
    struct_entries = fetch_structured_entries(
        sqlite_path=config.sqlite_db_path,
        session_id="audit_sess_1",
    )
    assert len(struct_entries) == 1
    assert struct_entries[0]["entity"] == "CUST-402"
    assert struct_entries[0]["value"] == "enterprise_vip"
    assert struct_entries[0]["source"] == "system_seed"

    # 2. Fetch vector entries by source
    pay_entries = fetch_vector_entries(
        chroma_dir=config.chroma_persist_dir,
        embedding_model_name=config.embedding_model_name,
        source="tool_output:update_payment_info",
    )
    assert len(pay_entries) == 1
    assert pay_entries[0]["entry_id"] == mem2.id
    assert pay_entries[0]["source"] == "tool_output:update_payment_info"

    # 3. Fetch vector entries by entry_id
    single_res = fetch_vector_entries(
        chroma_dir=config.chroma_persist_dir,
        embedding_model_name=config.embedding_model_name,
        entry_id=mem1.id,
    )
    assert len(single_res) == 1
    assert single_res[0]["content"] == "Invoice INV-1001 verified as paid."


def test_log_event_formatting():
    """Verify that view_logs formats all event types into clear timeline text."""
    ev_turn = {
        "timestamp": "2026-09-07T10:00:00.000000Z",
        "session_id": "test_sess",
        "event": "agent_turn_start",
        "customer_id": "CUST-402",
        "user_message_snippet": "Hello",
    }
    line1 = format_log_event(ev_turn)
    assert "[TURN START]" in line1
    assert "CUST-402" in line1

    ev_tool = {
        "timestamp": "2026-09-07T10:00:01.000000Z",
        "session_id": "test_sess",
        "event": "tool_call_start",
        "tool_name": "update_payment_info",
        "tool_args": {"customer_id": "CUST-402"},
    }
    line2 = format_log_event(ev_tool)
    assert "[TOOL CALL]" in line2
    assert "update_payment_info" in line2

    ev_write = {
        "timestamp": "2026-09-07T10:00:02.000000Z",
        "session_id": "test_sess",
        "event": "memory_write",
        "memory_type": "semantic",
        "source": "tool_output:update_payment_info",
        "trust_tier": "unclassified",
        "content_hash": "abcdef1234567890",
        "content_snippet": "Updated payment",
    }
    line3 = format_log_event(ev_write)
    assert "[MEMORY WRITE]" in line3
    assert "source=tool_output:update_payment_info" in line3
