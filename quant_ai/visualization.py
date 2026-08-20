from __future__ import annotations

import html
import re
from typing import Any

from .config import OrganizationConfig
from .schemas import CommitteeRun, InteractionEvent, NodeStatus


TOOL_LABELS = {
    "section_inventory": "SECTION INVENTORY",
    "market_snapshot": "MARKET STATE",
    "technical_regime": "MOMENTUM / TREND",
    "risk_snapshot": "RISK / TAIL",
    "strategy_backtest": "STRATEGY BACKTEST",
    "portfolio_diagnostics": "PORTFOLIO RISK",
    "portfolio_context": "PORTFOLIO STATE",
    "company_intelligence": "COMPANY INTEL",
    "macro_context": "MACRO",
    "fixed_income_context": "FIXED INCOME",
    "derivatives_context": "OPTIONS / FUTURES",
    "correlation_context": "CORRELATION",
    "monte_carlo_context": "MONTE CARLO",
    "backtest_context": "BACKTEST ENGINE",
    "ml_research_context": "ML LAB",
    "behavioral_context": "PSYCHOLOGY",
    "event_intelligence": "EVENT INTEL",
    "execution_context": "EXECUTION / TCA",
}


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _node_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)


def _state(status: NodeStatus | str | None) -> tuple[str, str]:
    value = status.value if isinstance(status, NodeStatus) else str(status or "standby")
    if value == NodeStatus.COMPLETE.value:
        return "complete", "COMPLETE"
    if value == NodeStatus.RUNNING.value:
        return "working", "WORKING"
    if value == NodeStatus.PARTIAL.value:
        return "warning", "REVIEW"
    if value == NodeStatus.ERROR.value:
        return "error", "ERROR"
    if value == NodeStatus.NOT_AVAILABLE.value:
        return "standby", "NO DATA"
    return "standby", "STANDBY"


def _path(source: tuple[float, float], target: tuple[float, float], kind: str) -> str:
    sx, sy = source
    tx, ty = target
    if abs(sy - ty) < 20:
        lift = 42 if sx < tx else -42
        return f"M {sx:.1f} {sy:.1f} C {sx:.1f} {sy + lift:.1f}, {tx:.1f} {ty + lift:.1f}, {tx:.1f} {ty:.1f}"
    middle = sy + (ty - sy) * 0.45
    if kind in {"dispatch", "report"}:
        return f"M {sx:.1f} {sy:.1f} C {sx:.1f} {middle:.1f}, {tx:.1f} {middle:.1f}, {tx:.1f} {ty:.1f}"
    return f"M {sx:.1f} {sy:.1f} C {sx:.1f} {middle:.1f}, {tx:.1f} {middle:.1f}, {tx:.1f} {ty:.1f}"


def workflow_graph_html(
    organization: OrganizationConfig,
    run: CommitteeRun | None = None,
    active_label: str = "",
) -> str:
    agents = [agent for agent in organization.agents if agent.enabled][:8]
    if run:
        planned_ids = {step.specialist for step in run.plan.steps}
        agents = [agent for agent in agents if agent.id in planned_ids]
    tool_names = list(
        dict.fromkeys(
            run.plan.required_tools if run else [tool for agent in agents for tool in agent.tools]
        )
    )
    tool_names = [name for name in tool_names if name != "section_inventory"][:18]

    width = 1400
    agent_y = 178
    agent_w, agent_h = 150, 78
    agent_gap = (width - 44 - agent_w) / max(len(agents) - 1, 1)
    positions: dict[str, tuple[float, float]] = {"cio": (700.0, 98.0)}
    agent_boxes: list[tuple[Any, float, float]] = []
    for index, agent in enumerate(agents):
        x = 22.0 + index * agent_gap
        agent_boxes.append((agent, x, float(agent_y)))
        positions[agent.id] = (x + agent_w / 2, agent_y + agent_h / 2)

    tool_w, tool_h, columns = 200, 70, 6
    tool_gap = (width - 56 - columns * tool_w) / (columns - 1)
    tool_boxes: list[tuple[str, float, float]] = []
    for index, name in enumerate(tool_names):
        row, column = divmod(index, columns)
        x = 28.0 + column * (tool_w + tool_gap)
        y = 410.0 + row * 126.0
        tool_boxes.append((name, x, y))
        positions[name] = (x + tool_w / 2, y + tool_h / 2)
    rows = max(1, (len(tool_names) + columns - 1) // columns)
    height = 410 + rows * 126 + 48

    report_map = {report.agent_id: report for report in run.reports} if run else {}
    tool_map = run.tools if run else {}
    event_source: list[InteractionEvent] = []
    if run:
        event_source = [
            event
            for event in run.interactions
            if event.source in positions
            and event.target in positions
            and event.kind in {"dispatch", "tool_call", "report", "consult", "challenge", "support", "veto", "sign_off"}
        ]
    else:
        for agent in agents:
            event_source.extend(
                InteractionEvent(agent.id, tool, "tool_call", "Configured evidence dependency", NodeStatus.PENDING)
                for tool in agent.tools
                if tool in positions
            )
            event_source.extend(
                InteractionEvent(agent.id, target, "consult", "Configured consultation", NodeStatus.PENDING)
                for target in agent.consults
                if target in positions
            )
            event_source.append(InteractionEvent("cio", agent.id, "dispatch", "Configured reporting line", NodeStatus.PENDING))

    edge_svg: list[str] = []
    for index, event in enumerate(event_source):
        source, target = positions[event.source], positions[event.target]
        css_state, _ = _state(event.status)
        css_kind = event.kind if event.kind in {"challenge", "support", "veto", "sign_off", "consult"} else "flow"
        path = _path(source, target, event.kind)
        edge_svg.append(
            f'<path id="edge-{index}" class="qerd-edge {css_state} {css_kind}" d="{path}"><title>{_esc(event.message)}</title></path>'
        )

    cio_state = "working" if active_label and not run else "complete" if run else "standby"
    cio_label = "WORKING" if cio_state == "working" else "COMPLETE" if run else "READY"
    nodes: list[str] = [
        f"""
        <g class="qerd-node {cio_state}" transform="translate(610 40)">
          <title>{_esc(active_label or 'Master orchestration, challenge reconciliation and risk gate')}</title>
          <rect width="180" height="86" rx="11"/><circle cx="18" cy="20" r="5"/>
          <text class="qerd-name" x="30" y="24">CIO</text><text class="qerd-type" x="15" y="49">MASTER ORCHESTRATOR</text>
          <text class="qerd-state" x="15" y="69">{cio_label}</text>
        </g>"""
    ]
    for agent, x, y in agent_boxes:
        report = report_map.get(agent.id)
        state, state_label = _state(report.status if report else NodeStatus.PENDING)
        if report and report.stance in {"HEDGE", "REDUCE", "AVOID"}:
            state, state_label = "warning", report.stance
        tooltip = report.thesis if report else agent.mandate
        nodes.append(
            f"""
            <g class="qerd-node {state}" transform="translate({x:.1f} {y:.1f})">
              <title>{_esc(tooltip)}</title><rect width="{agent_w}" height="{agent_h}" rx="10"/>
              <circle cx="16" cy="19" r="4.5"/><text class="qerd-name small" x="27" y="23">{_esc(agent.name.upper()[:22])}</text>
              <text class="qerd-type" x="13" y="46">SPECIALIST · P{agent.priority}</text>
              <text class="qerd-state" x="13" y="65">{state_label}{f' · {report.confidence:.0%}' if report else ''}</text>
            </g>"""
        )
    for name, x, y in tool_boxes:
        result = tool_map.get(name)
        state, state_label = _state(result.status if result else NodeStatus.PENDING)
        warnings = "; ".join(result.warnings[:2]) if result else "Configured deterministic evidence adapter"
        nodes.append(
            f"""
            <g class="qerd-node tool {state}" transform="translate({x:.1f} {y:.1f})">
              <title>{_esc(warnings)}</title><rect width="{tool_w}" height="{tool_h}" rx="9"/>
              <circle cx="16" cy="18" r="4"/><text class="qerd-name small" x="27" y="22">{_esc(TOOL_LABELS.get(name, name.upper())[:28])}</text>
              <text class="qerd-type" x="13" y="43">DETERMINISTIC ENGINE</text><text class="qerd-state" x="13" y="60">{state_label}</text>
            </g>"""
        )

    model = run.model if run else "SESSION MODEL"
    interaction_count = len(run.interactions) if run else len(event_source)
    interaction_label = "VERIFIED INTERACTIONS" if run else "CONFIGURED RELATIONSHIPS"
    return f"""
    <div class="qerd-wrap" style="--qerd-h:{height}px">
      <div class="qerd-grid"></div>
      <div class="qerd-meta">QUANT AI · INVESTMENT COMMITTEE GRAPH · SQL/ERD VIEW</div>
      <div class="qerd-ai">● {interaction_count} {interaction_label} · {_esc(model)}</div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="Quant AI committee interaction graph">
        <defs><filter id="qerdGlow"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
        {''.join(edge_svg)}{''.join(nodes)}
      </svg>
      <div class="qerd-legend"><span class="working">● WORKING</span><span class="complete">● COMPLETE</span><span class="standby">● STANDBY / NO DATA</span><span class="warning">● REVIEW / VETO</span><span class="error">● ERROR</span><span>— EVIDENCE</span><span>┄ CONSULT / CHALLENGE</span></div>
    </div>
    <style>
      .qerd-wrap{{position:relative;width:100%;background:radial-gradient(circle at 50% 3%,#132036 0,#090e16 38%,#070a0f 76%);border:1px solid #202a38;border-radius:15px;overflow:hidden;margin:8px 0 14px;color:#e9eef7}}
      .qerd-wrap svg{{display:block;width:100%;height:auto;position:relative;z-index:2}}
      .qerd-grid{{position:absolute;inset:0;background-image:linear-gradient(#1b243117 1px,transparent 1px),linear-gradient(90deg,#1b243117 1px,transparent 1px);background-size:28px 28px}}
      .qerd-meta,.qerd-ai{{position:absolute;z-index:4;top:14px;font:600 9px ui-monospace,SFMono-Regular,monospace;letter-spacing:1.3px}}
      .qerd-meta{{left:18px;color:#7f8ba0}} .qerd-ai{{right:18px;color:#39d0bd}}
      .qerd-node rect{{fill:#0c121bf2;stroke:#68738488;stroke-width:1.2}} .qerd-node circle{{fill:#687384}}
      .qerd-node .qerd-name{{fill:#e9eef7;font:750 10px Inter,system-ui,sans-serif;letter-spacing:.35px}}
      .qerd-node .qerd-name.small{{font-size:8.5px}} .qerd-node .qerd-type{{fill:#63748c;font:600 7.5px ui-monospace,monospace;letter-spacing:1px}}
      .qerd-node .qerd-state{{fill:#687384;font:750 8px ui-monospace,monospace;letter-spacing:1px}}
      .qerd-node.complete rect{{stroke:#149954aa}} .qerd-node.complete circle,.qerd-node.complete .qerd-state{{fill:#22bd69}}
      .qerd-node.working rect{{stroke:#24e07acc;filter:url(#qerdGlow)}} .qerd-node.working circle,.qerd-node.working .qerd-state{{fill:#24e07a}}
      .qerd-node.warning rect{{stroke:#ffb020bb}} .qerd-node.warning circle,.qerd-node.warning .qerd-state{{fill:#ffb020}}
      .qerd-node.error rect{{stroke:#ff4d5dcc}} .qerd-node.error circle,.qerd-node.error .qerd-state{{fill:#ff4d5d}}
      .qerd-edge{{fill:none;stroke:#149954;stroke-width:1.5;opacity:.5}} .qerd-edge.standby{{stroke:#687384;stroke-dasharray:5 6;opacity:.16}}
      .qerd-edge.warning,.qerd-edge.challenge{{stroke:#ffb020;stroke-dasharray:5 4;opacity:.75}} .qerd-edge.error,.qerd-edge.veto{{stroke:#ff4d5d;stroke-width:2;opacity:.85}}
      .qerd-edge.support,.qerd-edge.sign_off{{stroke:#24e07a;opacity:.72}} .qerd-edge.consult{{stroke:#8291a6;stroke-dasharray:4 5;opacity:.36}}
      .qerd-edge.working{{stroke:#24e07a;stroke-dasharray:9 7;animation:qerdFlow 1s linear infinite;opacity:.9}}
      @keyframes qerdFlow{{to{{stroke-dashoffset:-32}}}}
      .qerd-legend{{display:flex;flex-wrap:wrap;gap:14px;padding:0 18px 13px;color:#6f7d91;font:650 8px ui-monospace,monospace;letter-spacing:.7px}}
      .qerd-legend .working{{color:#24e07a}} .qerd-legend .complete{{color:#149954}} .qerd-legend .warning{{color:#ffb020}} .qerd-legend .error{{color:#ff4d5d}}
    </style>
    """
