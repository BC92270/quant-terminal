from __future__ import annotations

import json

from .config import OrganizationConfig
from .quality import CommitteeQuality
from .schemas import CommitteeRun


def decision_packet_json(run: CommitteeRun, organization: OrganizationConfig, quality: CommitteeQuality) -> str:
    payload = run.to_dict()
    payload["organization"] = {
        "name": organization.name,
        "version": organization.version,
        "enabled_desks": [agent.id for agent in organization.agents if agent.enabled],
        "risk_signoff_required": organization.require_risk_signoff,
    }
    payload["quality"] = quality.to_dict()
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def decision_packet_markdown(run: CommitteeRun, organization: OrganizationConfig, quality: CommitteeQuality) -> str:
    brief = run.brief
    lines = [
        f"# {organization.name} · Decision packet",
        "",
        f"- Run: `{run.run_id}`",
        f"- Created: {run.created_at}",
        f"- Asset: {run.ticker}",
        f"- Request class: {run.plan.request_kind}",
        f"- Provider / model: {run.provider} / {run.model}",
        f"- Decision integrity: {quality.score}/100 · {quality.grade}",
        "",
        "## Investment question",
        "",
        run.query,
        "",
        f"## CIO decision · {brief.decision} · {brief.confidence:.0%}",
        "",
        f"**{brief.headline}**",
        "",
        brief.executive_summary,
        "",
    ]

    def section(title: str, items: list[str]) -> None:
        lines.extend([f"## {title}", ""])
        lines.extend([f"- {item}" for item in items] or ["- None reported."])
        lines.append("")

    section("Investment case", brief.thesis)
    section("Catalysts", brief.catalysts)
    section("Risks", brief.risks)
    section("Hard invalidation", brief.invalidation)
    section("Implementation proposal", brief.implementation)
    lines.extend([f"**Sizing:** {brief.sizing}", "", f"**Horizon:** {brief.time_horizon}", ""])
    section("Dissent", brief.dissent)
    section("Missing evidence", brief.missing_evidence)
    section("Decision-quality blockers", quality.blockers)

    lines.extend(["## Independent desks", ""])
    for report in run.reports:
        lines.extend(
            [
                f"### {report.agent_name} · {report.stance} · {report.confidence:.0%}",
                "",
                report.thesis,
                "",
                "**Evidence:** " + (", ".join(report.evidence_used) or "None connected"),
                "",
                "**Risks:** " + ("; ".join(report.risks) or "None reported"),
                "",
                "**Invalidation:** " + ("; ".join(report.invalidation) or "None reported"),
                "",
            ]
        )
    lines.extend(
        [
            "## Governance notice",
            "",
            "Research proposal only. No trade, rebalance, hedge or allocation is authorized without explicit human approval.",
            "",
        ]
    )
    return "\n".join(lines)
