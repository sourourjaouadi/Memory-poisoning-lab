"""
Mock Invoice Lookup Tool.

Simulates querying an enterprise billing system.
Returns mock invoice data with realistic financial and customer attributes.
Outputs from this tool will be tagged with provenance:
  source: 'tool_output:invoice_lookup'
"""

from __future__ import annotations

from typing import Any, Dict
from tools.base import BaseTool


MOCK_INVOICE_DATABASE: Dict[str, Dict[str, Any]] = {
    "INV-1001": {
        "invoice_id": "INV-1001",
        "customer_id": "CUST-402",
        "customer_name": "Acme Industrial Corp",
        "amount_usd": 14500.00,
        "status": "PAID",
        "issue_date": "2026-08-01",
        "due_date": "2026-08-31",
        "description": "Enterprise Platform License (Annual)",
        "notes": "Payment processed via wire transfer on Aug 15.",
    },
    "INV-1002": {
        "invoice_id": "INV-1002",
        "customer_id": "CUST-771",
        "customer_name": "Globex Cyber Dynamics",
        "amount_usd": 3200.50,
        "status": "OVERDUE",
        "issue_date": "2026-07-15",
        "due_date": "2026-08-15",
        "description": "Cloud Storage & Vector Compute Surcharge",
        "notes": "First notice sent Aug 20. Pending finance review.",
    },
    "INV-1003": {
        "invoice_id": "INV-1003",
        "customer_id": "CUST-905",
        "customer_name": "Initech Systems",
        "amount_usd": 780.00,
        "status": "PENDING",
        "issue_date": "2026-09-01",
        "due_date": "2026-10-01",
        "description": "Premium Support Tier Add-on",
        "notes": "Standard net-30 terms.",
    },
}


class InvoiceLookupTool(BaseTool):
    """Tool to fetch customer invoice details by invoice ID."""

    name = "invoice_lookup"
    description = "Look up billing information, payment status, and customer details for a given invoice ID (e.g. INV-1001)."
    parameters = {
        "type": "object",
        "properties": {
            "invoice_id": {
                "type": "string",
                "description": "The unique identifier of the invoice (e.g. 'INV-1001', 'INV-1002')",
            }
        },
        "required": ["invoice_id"],
    }

    def execute(self, invoice_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Look up invoice in mock database, or generate a realistic fallback record."""
        clean_id = invoice_id.strip().upper()
        if clean_id in MOCK_INVOICE_DATABASE:
            return {"found": True, "invoice": MOCK_INVOICE_DATABASE[clean_id]}

        # Realistic fallback record for unlisted invoice IDs
        return {
            "found": True,
            "invoice": {
                "invoice_id": clean_id,
                "customer_id": "CUST-GENERIC",
                "customer_name": "Standard Client Services",
                "amount_usd": 1250.00,
                "status": "UNPAID",
                "issue_date": "2026-09-01",
                "due_date": "2026-09-30",
                "description": f"Standard consulting services for reference {clean_id}",
                "notes": "Generated from auxiliary billing ledger.",
            },
        }
