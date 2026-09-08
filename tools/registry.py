"""
Tool Registry for managing and executing agent tools.

Centralizes discovery, schema exposure to LLM clients, and execution dispatching.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from tools.base import BaseTool
from tools.invoice import InvoiceLookupTool
from tools.ticket import SupportTicketIntakeTool
from tools.payment import UpdatePaymentInfoTool


class ToolRegistry:
    """Registry maintaining available agent tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a new tool instance."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        """Return all registered tool instances."""
        return list(self._tools.values())

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        """Return tool definitions in OpenAI function schema format."""
        return [tool.to_openai_tool_schema() for tool in self._tools.values()]

    def get_anthropic_schemas(self) -> List[Dict[str, Any]]:
        """Return tool definitions in Anthropic schema format."""
        return [tool.to_anthropic_tool_schema() for tool in self._tools.values()]

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute named tool with provided keyword arguments."""
        tool = self.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not found in registry."}
        try:
            return tool.execute(**args)
        except Exception as e:
            return {"error": f"Error executing tool '{name}': {str(e)}"}


def create_default_registry() -> ToolRegistry:
    """Instantiate standard registry populated with default Phase 0/1 mock tools."""
    registry = ToolRegistry()
    registry.register(InvoiceLookupTool())
    registry.register(SupportTicketIntakeTool())
    registry.register(UpdatePaymentInfoTool())
    return registry
