from __future__ import annotations

from .config import OrganizationConfig


def organization_graph(organization: OrganizationConfig) -> dict[str, object]:
    nodes = [{"id": "cio", "name": "CIO", "role": "Chief Investment Officer", "enabled": True}]
    edges: list[dict[str, str]] = []
    for agent in organization.agents:
        nodes.append({"id": agent.id, "name": agent.name, "role": agent.role, "enabled": agent.enabled})
        edges.append({"source": agent.id, "target": agent.reports_to or "cio", "type": "reports_to"})
        edges.extend({"source": agent.id, "target": target, "type": "consults"} for target in agent.consults)
    return {"nodes": nodes, "edges": edges}
