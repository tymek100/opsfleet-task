"""Discovery metadata for our application; this is not an A2A protocol endpoint."""

CAPABILITIES = {
    "coordinator": "Combine reviewed sales, inventory and distribution findings.",
    "retail": "Analyze qualifying revenue, products, customers and orders with read-only SQL.",
    "inventory": "Analyze modeled unsold stock, inventory cost and aging.",
    "distribution": "Analyze distribution-center inventory and optional Google Maps lookups.",
}


def agent_card(role="coordinator"):
    if role not in CAPABILITIES:
        raise ValueError("Unknown agent")
    return {
        "schemaVersion": "1.0",
        "name": "Retail Insight — " + role.title(),
        "description": CAPABILITIES[role],
        "framework": "LangGraph",
        "version": "0.3.0",
        "capabilities": {"streaming": True, "reviewedAnswers": True, "multiTurn": True},
        "skills": [
            {"id": key, "name": key.title(), "description": value}
            for key, value in CAPABILITIES.items()
            if role == "coordinator" or role == key
        ],
        "interfaces": [{"protocol": "HTTP+NDJSON", "url": f"/api/agents/{role}/chat"}],
        "authentication": "Signed local browser session; platform authentication for Foundry hosting.",
        "hosting": {
            "target": "Microsoft Foundry",
            "adapter": "ResponsesHostServer",
            "deployed": False,
        },
        "limitations": ["No A2A endpoint", "Read-only warehouse", "Maps requires a configured key"],
    }
