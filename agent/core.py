"""
Hand-Rolled Agent Core Orchestration Loop.

This orchestration loop contains NO LangChain, LlamaIndex, or other agent
frameworks. Every step of execution is explicit, readable, and inspectable:
1. Perceive: Receive user input.
2. Recall: Query memory for matching session data (INDISCRIMINATE in Phase 0/1).
3. Assemble: Inject recalled memories into context.
4. Model Invocation: Call swappable LLM client with tools.
5. Tool Execution & Provenance Memory Write: Execute tool, log, and persist output.
6. User Memory Write: Persist user interaction with provenance.
7. Respond: Emit final message and structured log events.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from agent.config import AgentConfig
from agent.llm import BaseLLMClient, LLMResponse, get_llm_client
from agent.logger import get_logger
from memory.manager import MemoryManager
from tools.registry import ToolRegistry, create_default_registry


class AgentCore:
    """
    Explicit, transparent agent loop.
    Controls the flow between LLM inference, tool execution, and persistent memory.
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        memory: Optional[MemoryManager] = None,
        tools: Optional[ToolRegistry] = None,
        llm: Optional[BaseLLMClient] = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.config.ensure_directories()
        self.logger = get_logger("agent_core")

        self.memory = memory or MemoryManager(
            sqlite_path=self.config.sqlite_db_path,
            chroma_dir=self.config.chroma_persist_dir,
            embedding_model_name=self.config.embedding_model_name,
        )
        self.tools = tools or create_default_registry()
        self.llm = llm or get_llm_client(self.config)

    def run_turn(
        self,
        user_message: str,
        session_id: str = "default_session",
        customer_id: Optional[str] = None,
    ) -> str:
        """
        Execute a single conversational turn.

        Args:
            user_message: Raw string message from the user.
            session_id: The session/thread identifier for persistence and recall.
            customer_id: Optional customer identity for cross-session history recall.

        Returns:
            Assistant's response string.
        """
        start_time = time.perf_counter()

        # If customer_id is not passed, attempt simple regex extraction for known IDs
        resolved_customer_id = customer_id
        if not resolved_customer_id:
            import re
            cust_match = re.search(r"\b(CUST-\d+)\b", user_message, re.IGNORECASE)
            if not cust_match:
                cust_match = re.search(r"\b(Acme Industrial Corp|Acme)\b", user_message, re.IGNORECASE)
            if cust_match:
                resolved_customer_id = cust_match.group(1)

        self.logger.info(
            "agent_turn_start",
            session_id=session_id,
            customer_id=resolved_customer_id or "",
            user_message_len=len(user_message),
            user_message_snippet=user_message[:80],
        )

        # =====================================================================
        # STEP 1: RECALL (INDISCRIMINATE & STRICT IDENTITY-BASED)
        # =====================================================================
        # ARCHITECTURAL DECISION FOR PHASE 0 & 1:
        # Cross-session memory retrieval in this step matches STRICTLY on
        # `session_id` and/or `customer_id` (identity matching).
        #
        # CRITICAL NAIVE BASELINE GUARANTEE:
        # - NO semantic similarity scoring or nearest-neighbor distance thresholding
        # - NO topic matching or relevance ranking against the current message
        # - NO scoring of "how relevant" a memory is to the current turn
        # - NO trust-tier gating, defense filtering, or sanitization
        #
        # All stored memories matching the session or customer identity—including
        # any poisoned instructions planted in earlier sessions—are recalled
        # unconditionally into the prompt context. This intentional vulnerability
        # establishes the observable baseline for Phase 2 attack experiments.
        # =====================================================================
        recalled = self.memory.recall_session(
            session_id=session_id,
            customer_id=resolved_customer_id,
        )
        recalled_facts = recalled.get("facts", [])
        recalled_memories = recalled.get("semantic_memories", [])

        # Format recalled memory context block
        context_lines: List[str] = []
        if recalled_facts:
            context_lines.append("--- RECALLED FACTS (STRUCTURED STORE) ---")
            for f in recalled_facts:
                context_lines.append(
                    f"- [{f.provenance.source} | trust:{f.provenance.trust_tier}] "
                    f"{f.entity}.{f.attribute} = {f.value}"
                )

        if recalled_memories:
            context_lines.append("--- RECALLED SESSION & CUSTOMER MEMORIES (VECTOR STORE) ---")
            for m in recalled_memories:
                context_lines.append(
                    f"- [{m.provenance.source} | trust:{m.provenance.trust_tier}] "
                    f"{m.content}"
                )

        memory_context_str = "\n".join(context_lines) if context_lines else "No previous memories for this session."

        # =====================================================================
        # STEP 2: ASSEMBLE PROMPT
        # =====================================================================
        full_system_prompt = (
            f"{self.config.system_prompt}\n\n"
            f"=== PERSISTENT SESSION & CUSTOMER MEMORY ===\n"
            f"{memory_context_str}\n"
            f"============================================"
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Retrieve tool schemas according to provider
        tool_schemas = self._get_tool_schemas()

        # =====================================================================
        # STEP 3: MODEL CALL (FIRST PASS)
        # =====================================================================
        llm_resp: LLMResponse = self.llm.generate(messages=messages, tools=tool_schemas)

        final_response_text = ""

        # =====================================================================
        # STEP 4: TOOL EXECUTION & PROVENANCE MEMORY WRITE
        # =====================================================================
        if llm_resp.has_tool_calls:
            # Append assistant's tool-call request to message log
            messages.append({
                "role": "assistant",
                "content": llm_resp.content or "",
            })

            for tc in llm_resp.tool_calls:
                self.logger.info(
                    "tool_call_start",
                    session_id=session_id,
                    tool_name=tc.name,
                    tool_args=tc.arguments,
                )

                # Extract customer_id from tool args or resolved_customer_id
                tool_customer_id = resolved_customer_id or tc.arguments.get("customer_id") or ""

                # Execute tool
                tool_output = self.tools.execute(tc.name, tc.arguments)
                tool_output_str = json.dumps(tool_output)

                self.logger.info(
                    "tool_call_complete",
                    session_id=session_id,
                    tool_name=tc.name,
                    tool_output_snippet=tool_output_str[:120],
                )

                # CRITICAL REQUIREMENT: Every tool output written to memory carries
                # explicit provenance metadata identifying source and trust_tier.
                self.memory.remember(
                    content=f"Tool {tc.name} output: {tool_output_str}",
                    source=f"tool_output:{tc.name}",
                    session_id=session_id,
                    customer_id=tool_customer_id,
                    actor="tool",
                    trust_tier="unclassified",
                    metadata={"tool_name": tc.name, "tool_args": tc.arguments},
                )

                # Append tool result to conversation history for model synthesis
                messages.append({
                    "role": "tool",
                    "content": tool_output_str,
                })

            # Re-invoke LLM with tool output to generate final natural response
            synthesis_resp = self.llm.generate(messages=messages, tools=tool_schemas)
            final_response_text = synthesis_resp.content or "Tool action performed successfully."
        else:
            final_response_text = llm_resp.content or "I have processed your request."

        # =====================================================================
        # STEP 5: REMEMBER USER INTERACTION WITH PROVENANCE
        # =====================================================================
        self.memory.remember(
            content=user_message,
            source="user_chat",
            session_id=session_id,
            customer_id=resolved_customer_id or "",
            actor="user",
            trust_tier="unclassified",
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        self.logger.info(
            "agent_turn_complete",
            session_id=session_id,
            latency_ms=elapsed_ms,
            response_snippet=final_response_text[:80],
        )

        return final_response_text

    def _get_tool_schemas(self) -> Optional[List[Dict[str, Any]]]:
        """Format tool schemas based on the active provider."""
        provider = self.config.model_provider.lower()
        if provider == "anthropic":
            return self.tools.get_anthropic_schemas()
        # Default to OpenAI-compatible function schema (works for OpenAI, Ollama, Mock)
        return self.tools.get_openai_schemas()
