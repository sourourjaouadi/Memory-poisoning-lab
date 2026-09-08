"""
Swappable LLM Client Layer.

Provides a unified interface across:
1. MockLLMClient (deterministic mock client for offline tests & dry runs)
2. OpenAIClient (GPT-4o, GPT-4o-mini)
3. AnthropicClient (Claude 3.5 Sonnet)
4. OllamaClient (Local models via OpenAI-compatible endpoint)

Explicit and inspectable: no LangChain / LlamaIndex wrappers.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.config import AgentConfig
from agent.logger import get_logger


@dataclass
class ToolCall:
    """Represents a tool execution requested by the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class BaseLLMClient(ABC):
    """Abstract base class for model providers."""

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """
        Generate completion from message list with optional tools.
        messages format: [{'role': 'system'|'user'|'assistant'|'tool', 'content': ...}]
        """
        pass


class MockLLMClient(BaseLLMClient):
    """
    Deterministic mock client enabling full testing without live API keys.
    Simulates tool calling and response generation based on keyword triggers.
    """

    def __init__(self) -> None:
        self.logger = get_logger("mock_llm")

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        # Check the most recent message
        last_msg = messages[-1] if messages else {}
        role = last_msg.get("role", "")
        content = str(last_msg.get("content", ""))

        # If previous turn was a tool output, synthesize final response
        if role == "tool":
            try:
                tool_data = json.loads(content)
            except Exception:
                tool_data = {"raw": content}

            if "invoice" in tool_data:
                inv = tool_data["invoice"]
                return LLMResponse(
                    content=f"I checked invoice {inv.get('invoice_id')}. "
                            f"Customer is {inv.get('customer_name')}, amount is ${inv.get('amount_usd'):,.2f}, "
                            f"status is {inv.get('status')}, and it is due on {inv.get('due_date')}."
                )
            if "ticket" in tool_data:
                tck = tool_data["ticket"]
                return LLMResponse(
                    content=f"I have created support ticket {tck.get('ticket_id')} for {tck.get('customer_id')}. "
                            f"Priority: {tck.get('priority')}. Assigned queue: {tck.get('assigned_queue')}."
                )
            if "confirmation_code" in tool_data or "updated_payment_details" in tool_data:
                cust = tool_data.get("customer_id", "the customer")
                code = tool_data.get("confirmation_code", "CONFIRMED")
                details = tool_data.get("updated_payment_details", "")
                return LLMResponse(
                    content=f"Payment information for {cust} has been updated. "
                            f"Confirmation code: {code}. New details: {details}."
                )
            return LLMResponse(content=f"Tool operation completed: {content}")

        # Check if user message triggers invoice lookup
        inv_match = re.search(r"\b(INV-\d+)\b", content, re.IGNORECASE)
        if inv_match and tools:
            inv_id = inv_match.group(1).upper()
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call_{inv_id}",
                        name="invoice_lookup",
                        arguments={"invoice_id": inv_id},
                    )
                ]
            )

        # Check if user asks to update payment info
        pay_keywords = ["update payment", "change payment", "new payment", "routing number", "wire instructions", "bank account", "remittance"]
        if any(k in content.lower() for k in pay_keywords) and tools:
            # Extract customer if present or use default
            cust_match = re.search(r"\b(CUST-\d+)\b", content, re.IGNORECASE)
            if not cust_match:
                cust_match = re.search(r"\b(Acme Industrial Corp|Acme)\b", content, re.IGNORECASE)
            customer_id = cust_match.group(1) if cust_match else "CUST-402"
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call_pay_update_001",
                        name="update_payment_info",
                        arguments={
                            "customer_id": customer_id,
                            "new_payment_details": content,
                        },
                    )
                ]
            )

        # Check if user is asking about recalled memories / past session context (prioritized over ticket creation)
        system_text = ""
        for m in messages:
            if m.get("role") == "system":
                system_text += m.get("content", "")

        lower_msg = content.lower()
        if any(q in lower_msg for q in ["what is", "what are", "what previous", "do you remember", "confirm what", "on file", "history", "recall"]):
            recalled_elements = []
            if "update_payment_info" in system_text or "Routing" in system_text:
                pay_match = re.search(r"Routing\s+\d+,\s*Account\s+\d+", system_text)
                if not pay_match:
                    pay_match = re.search(r"updated_payment_details\\\":\s*\\\"([^\\\"]+)\\\"", system_text)
                if pay_match:
                    recalled_elements.append(f"payment instructions '{pay_match.group(0)}'")
                else:
                    recalled_elements.append("your updated payment details")

            if "TCK-" in system_text:
                tck_matches = re.findall(r"\b(TCK-\d+)\b", system_text)
                if tck_matches:
                    recalled_elements.append(f"support ticket {tck_matches[-1]}")

            if "INV-" in system_text:
                inv_matches = re.findall(r"\b(INV-\d+)\b", system_text)
                if inv_matches:
                    recalled_elements.append(f"invoice {inv_matches[0]}")

            if recalled_elements:
                elements_str = " and ".join(recalled_elements)
                return LLMResponse(
                    content=f"According to your account records, I have on file {elements_str}. Is there anything specific you would like to update or review?"
                )

        # Check if user asks for ticket creation (requires action verb)
        ticket_action_triggers = [
            "file a ticket", "file ticket", "open a ticket", "open ticket",
            "create a ticket", "create ticket", "submit a ticket", "submit ticket",
            "file a support request", "file support request", "file a support ticket", "support ticket"
        ]
        if any(w in lower_msg for w in ticket_action_triggers) and tools:
            cust_match = re.search(r"\b(CUST-\d+)\b", content, re.IGNORECASE)
            if not cust_match:
                cust_match = re.search(r"\b(Acme Industrial Corp|Acme)\b", content, re.IGNORECASE)
            customer_id = cust_match.group(1) if cust_match else "CUST-402"
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call_ticket_001",
                        name="support_ticket_intake",
                        arguments={
                            "customer_id": customer_id,
                            "issue_description": content,
                            "priority": "normal",
                        },
                    )
                ]
            )

        # Standard conversational response
        return LLMResponse(
            content=f"Thank you for contacting support. I have received your message: '{content}'. How else can I assist you today?"
        )


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI API (GPT-4o, GPT-4o-mini)."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import OpenAI
        self.model = model
        self.client = OpenAI(api_key=api_key)

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)
        choice = response.choices[0].message

        tool_calls: List[ToolCall] = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                args = {}
                if tc.function.arguments:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {"raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        return LLMResponse(content=choice.content, tool_calls=tool_calls)


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic API (Claude 3.5 Sonnet)."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022") -> None:
        from anthropic import Anthropic
        self.model = model
        self.client = Anthropic(api_key=api_key)

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        # Extract system prompt if present
        system_text = ""
        user_messages: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text += msg.get("content", "") + "\n"
            else:
                user_messages.append(msg)

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": user_messages,
        }
        if system_text:
            kwargs["system"] = system_text
        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        text_content = ""
        tool_calls: List[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        return LLMResponse(
            content=text_content if text_content else None,
            tool_calls=tool_calls,
        )


class OllamaClient(BaseLLMClient):
    """Client for local Ollama models via OpenAI-compatible endpoint."""

    def __init__(self, base_url: str = "http://localhost:11434/v1", model: str = "llama3.2") -> None:
        from openai import OpenAI
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key="ollama")

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)
        choice = response.choices[0].message

        tool_calls: List[ToolCall] = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                args = {}
                if tc.function.arguments:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {"raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        return LLMResponse(content=choice.content, tool_calls=tool_calls)


def get_llm_client(config: AgentConfig) -> BaseLLMClient:
    """Factory creating LLM client according to AgentConfig."""
    provider = config.model_provider.lower()
    if provider == "openai":
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required for provider 'openai'.")
        return OpenAIClient(api_key=config.openai_api_key, model=config.openai_model)
    elif provider == "anthropic":
        if not config.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required for provider 'anthropic'.")
        return AnthropicClient(api_key=config.anthropic_api_key, model=config.anthropic_model)
    elif provider == "ollama":
        return OllamaClient(base_url=config.ollama_base_url, model=config.ollama_model)
    elif provider == "mock":
        return MockLLMClient()
    else:
        raise ValueError(f"Unsupported model provider: '{provider}'. Choose 'mock', 'openai', 'anthropic', or 'ollama'.")
