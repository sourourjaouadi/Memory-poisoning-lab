"""
Base tool interface for the Memory Poisoning Lab.

Tools provide schema definitions for the model and an execution handler.
Outputs are formatted as dictionaries or strings suitable for persistent memory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Abstract base class for all agent tools."""

    name: str
    description: str
    parameters: Dict[str, Any]

    @abstractmethod
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """Execute the tool with given arguments and return a structured dictionary."""
        pass

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        """Convert tool definition to OpenAI/Ollama function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_tool_schema(self) -> Dict[str, Any]:
        """Convert tool definition to Anthropic tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }
