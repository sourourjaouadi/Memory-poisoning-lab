from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Trigger:
    """Structured predicate determining when the attack should fire.
    Currently only the ``keyword`` type is used – the model's turn text is
    scanned for the keyword (case‑insensitive) before executing the payload.
    """
    type: str  # e.g. "keyword"
    value: str


@dataclass
class AttackConfig:
    """Configuration for a single memory‑poisoning attack.

    Fields:
    - name: Identifier for the attack.
    - description: Human‑readable description.
    - trigger: ``Trigger`` instance describing the activation condition.
    - payload: The plain‑text instruction that will be injected.
    - injection_vector: Either ``chat_message`` (sent as a user message) or
      ``tool_output`` (embedded in the output of a tool).
    - tool_name: Name of the tool to invoke when ``injection_vector`` is
      ``tool_output``. Optional for ``chat_message`` attacks.
    - tool_args: Arguments for the tool invocation. Optional for
      ``chat_message`` attacks.
    - delay_messages: Optional list of interim turn messages (role/content)
      used by sleeper attacks.
    """
    name: str
    description: str
    trigger: Trigger
    payload: str
    injection_vector: str  # "chat_message" or "tool_output"
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    delay_messages: Optional[List[Dict[str, str]]] = None
    indicator: Optional[str] = None  # New field for distinctive payload indicator
