"""
Mock Support Ticket Intake Tool.

Simulates logging a ticket in an enterprise support desk (e.g. Zendesk / Jira).
Returns a newly created ticket record.
Outputs from this tool will be tagged with provenance:
  source: 'tool_output:support_ticket_intake'
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Dict
from tools.base import BaseTool


class SupportTicketIntakeTool(BaseTool):
    """Tool to intake and register customer support inquiries."""

    name = "support_ticket_intake"
    description = (
        "Create a new support ticket in the ticketing desk when a customer reports an issue, "
        "incident, or service request."
    )
    parameters = {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "Identifier or name of the customer filing the ticket.",
            },
            "issue_description": {
                "type": "string",
                "description": "Clear summary of the technical or service problem.",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high", "urgent"],
                "description": "Priority level of the support request (defaults to 'normal').",
            },
        },
        "required": ["customer_id", "issue_description"],
    }

    def execute(
        self,
        customer_id: str,
        issue_description: str,
        priority: str = "normal",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        ticket_num = random.randint(10000, 99999)
        ticket_id = f"TCK-{ticket_num}"
        created_at = datetime.now(timezone.utc).isoformat()

        return {
            "success": True,
            "ticket": {
                "ticket_id": ticket_id,
                "customer_id": customer_id,
                "issue_description": issue_description,
                "priority": priority.lower(),
                "status": "OPEN",
                "assigned_queue": "tier1-support",
                "created_at": created_at,
                "estimated_sla_hours": 24 if priority in ("normal", "low") else 4,
            },
        }
