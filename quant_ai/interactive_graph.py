from __future__ import annotations

from typing import Any

import streamlit as st

from .config import OrganizationConfig
from .schemas import CommitteeRun, NodeStatus
from .visualization import TOOL_LABELS


GRAPH_HTML = """
<section class="qflow" aria-label="Interactive Quant AI committee graph">
  <header class="qflow-bar">
    <div class="qflow-brand"><span class="qflow-orb"></span><div><b>JARVIS NEURAL WORKFLOW</b><small id="missionLabel">INTERACTIVE COMMITTEE TOPOLOGY</small></div></div>
    <div class="qflow-search-wrap"><span>⌕</span><input id="nodeSearch" type="search" placeholder="Find desk, engine or interaction…" aria-label="Search workflow nodes"></div>
    <div class="qflow-controls">
      <button data-filter="evidence" class="active">EVIDENCE</button><button data-filter="consult" class="active">CONSULT</button><button data-filter="challenge" class="active">CHALLENGE</button>
      <button id="zoomOut" aria-label="Zoom out">−</button><button id="zoomIn" aria-label="Zoom in">＋</button><button id="resetView">AUTO</button>
    </div>
  </header>
  <div class="qflow-body">
    <div id="viewport" class="qflow-viewport" tabindex="0" aria-label="Draggable and zoomable committee canvas">
      <div class="qflow-radar"><i></i><i></i><i></i><span></span></div>
      <div id="scene" class="qflow-scene">
        <svg id="edgeSvg" viewBox="0 0 1380 1120" preserveAspectRatio="none" aria-label="Agent interaction edges">
          <defs>
            <filter id="glow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            <marker id="arrowGreen" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker>
            <marker id="arrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker>
            <marker id="arrowRed" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker>
          </defs>
          <g id="edgeLayer"></g>
        </svg>
        <div id="nodeLayer"></div>
      </div>
      <div class="qflow-hint">DRAG NODES · PAN BACKGROUND · WHEEL TO ZOOM · CLICK EDGES</div>
    </div>
    <aside class="qflow-inspector">
      <div class="qflow-inspector-head"><span id="inspectType">NODE</span><b id="inspectState">READY</b></div>
      <h3 id="inspectTitle">CIO</h3><p id="inspectSubtitle">MASTER ORCHESTRATOR</p>
      <div class="qflow-gauge"><i id="inspectGauge"></i></div>
      <div id="inspectStats" class="qflow-stats"></div>
      <p id="inspectDetail" class="qflow-detail"></p>
      <div id="inspectEvents" class="qflow-events"></div>
      <div id="inspectActions" class="qflow-actions"></div>
    </aside>
  </div>
  <footer class="qflow-footer"><span class="live">● LIVE / COMPLETE</span><span class="review">● REVIEW / VETO</span><span class="idle">● STANDBY / NO DATA</span><span>━━ EVIDENCE / REPORT</span><span>┄┄ CONSULT / CHALLENGE</span><strong id="graphCount">0 NODES · 0 EDGES</strong></footer>
</section>
"""


GRAPH_CSS = """
/* Quant AI interactive workflow component */
*{box-sizing:border-box}.qflow{--cyan:#38f3d1;--blue:#5ba8ff;--green:#25da78;--amber:#ffb020;--red:#ff5165;--ink:#e9f5ff;--muted:#73879c;width:100%;height:100%;min-height:720px;display:flex;flex-direction:column;overflow:hidden;border:1px solid #203246;border-radius:18px;background:radial-gradient(circle at 44% -10%,#163554 0,#09121e 35%,#050910 76%);box-shadow:0 30px 90px #0008,inset 0 1px #75e9ff18;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,sans-serif;position:relative}.qflow:before{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(transparent 49%,#7fe9ff06 50%);background-size:100% 4px;z-index:20;mix-blend-mode:screen}.qflow-bar{height:62px;flex:0 0 62px;display:flex;align-items:center;gap:16px;padding:9px 14px;border-bottom:1px solid #1e3043;background:#07101bd9;position:relative;z-index:30}.qflow-brand{min-width:230px;display:flex;align-items:center;gap:10px}.qflow-brand b{display:block;font:750 10px ui-monospace,monospace;letter-spacing:1.5px;color:#dffaff}.qflow-brand small{display:block;margin-top:3px;font:600 7px ui-monospace,monospace;letter-spacing:1.1px;color:#587087}.qflow-orb{width:28px;height:28px;border:1px solid #38f3d188;border-radius:50%;position:relative;box-shadow:0 0 20px #38f3d133,inset 0 0 12px #38f3d122}.qflow-orb:before,.qflow-orb:after{content:"";position:absolute;border-radius:50%;inset:5px;border:1px dashed var(--cyan);animation:qflowSpin 7s linear infinite}.qflow-orb:after{inset:10px;background:var(--cyan);border:0;box-shadow:0 0 12px var(--cyan);animation:qflowPulse 1.8s ease-in-out infinite}.qflow-search-wrap{height:36px;min-width:180px;max-width:330px;flex:1;display:flex;align-items:center;border:1px solid #21364a;border-radius:9px;background:#050b13;padding:0 10px;color:#5d7388}.qflow-search-wrap input{width:100%;border:0;outline:0;background:transparent;color:#ddecf8;padding:0 8px;font:500 10px ui-monospace,monospace}.qflow-search-wrap input::placeholder{color:#506274}.qflow-controls{display:flex;gap:4px;align-items:center}.qflow-controls button,.qflow-actions button{height:30px;padding:0 8px;border:1px solid #26384a;border-radius:7px;background:#0a1521;color:#6e8498;font:700 7px ui-monospace,monospace;letter-spacing:.8px;cursor:pointer}.qflow-controls button:hover,.qflow-controls button.active,.qflow-actions button:hover{color:var(--cyan);border-color:#38f3d166;background:#0c2528}.qflow-body{display:grid;grid-template-columns:minmax(0,1fr) 292px;min-height:0;flex:1}.qflow-viewport{position:relative;overflow:hidden;cursor:grab;outline:none;background-image:linear-gradient(#4b6d8910 1px,transparent 1px),linear-gradient(90deg,#4b6d8910 1px,transparent 1px);background-size:30px 30px}.qflow-viewport:active{cursor:grabbing}.qflow-scene{position:absolute;left:0;top:0;width:1380px;height:1120px;transform-origin:0 0;will-change:transform}.qflow-scene svg{position:absolute;inset:0;width:1380px;height:1120px;overflow:visible}.qflow-radar{position:absolute;width:500px;height:500px;left:50%;top:42%;transform:translate(-50%,-50%);opacity:.17;pointer-events:none}.qflow-radar i{position:absolute;inset:0;border:1px solid #38f3d144;border-radius:50%}.qflow-radar i:nth-child(2){inset:80px}.qflow-radar i:nth-child(3){inset:160px}.qflow-radar span{position:absolute;left:50%;top:50%;width:50%;height:1px;transform-origin:left;background:linear-gradient(90deg,#38f3d1aa,transparent);animation:qflowRadar 8s linear infinite}.qflow-hint{position:absolute;left:12px;bottom:10px;color:#486277;font:600 7px ui-monospace,monospace;letter-spacing:1px;z-index:6}.qnode{position:absolute;width:206px;min-height:86px;text-align:left;border:1px solid #2a4156;border-radius:11px;background:linear-gradient(145deg,#0d1927f5,#08101af5);color:var(--ink);padding:12px 12px 10px;cursor:grab;box-shadow:0 9px 24px #0007,inset 0 1px #ffffff0d;transition:border-color .18s,box-shadow .18s,opacity .18s;user-select:none;touch-action:none}.qnode:hover,.qnode.selected{border-color:#38f3d1bb;box-shadow:0 0 0 1px #38f3d133,0 0 32px #19d8bc18,0 12px 28px #0009;z-index:4}.qnode.selected:before{content:"";position:absolute;inset:-5px;border:1px solid #38f3d144;border-radius:14px;animation:qflowPulse 1.6s ease-in-out infinite}.qnode.disabled{opacity:.38;filter:saturate(.3)}.qnode.cio{width:236px;min-height:104px;background:radial-gradient(circle at 18% 10%,#123c46,#0a1722 58%);border-color:#38f3d188}.qnode.human{width:236px;border-color:#5ba8ff77;background:linear-gradient(145deg,#101e38,#09111e)}.qnode.tool{width:190px;min-height:72px;padding:10px}.qnode.warning{border-color:#ffb02088}.qnode.error{border-color:#ff5165aa}.qnode.complete .qnode-dot{background:var(--green);box-shadow:0 0 12px var(--green)}.qnode.warning .qnode-dot{background:var(--amber);box-shadow:0 0 12px var(--amber)}.qnode.error .qnode-dot{background:var(--red);box-shadow:0 0 12px var(--red)}.qnode-id{display:flex;align-items:center;gap:7px;color:#e9f5ff;font:750 9px ui-monospace,monospace;letter-spacing:.45px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.qnode-dot{width:6px;height:6px;border-radius:50%;background:#66798b;flex:0 0 auto}.qnode-role{margin-top:7px;color:#668097;font:650 7px ui-monospace,monospace;letter-spacing:.9px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.qnode-foot{margin-top:9px;display:flex;justify-content:space-between;gap:6px;color:#60768a;font:700 7px ui-monospace,monospace;letter-spacing:.7px}.qnode-foot strong{color:#8debd8;font-weight:700}.qedge{fill:none;stroke:#25b86f;stroke-width:1.25;opacity:.38;marker-end:url(#arrowGreen);transition:opacity .18s,stroke-width .18s}.qedge.report,.qedge.dispatch,.qedge.synthesis{stroke:#32d79b;opacity:.52}.qedge.consult,.qedge.support{stroke:#7f98ad;stroke-dasharray:5 7;opacity:.26}.qedge.challenge{stroke:var(--amber);stroke-dasharray:6 5;marker-end:url(#arrowAmber);opacity:.58}.qedge.veto{stroke:var(--red);stroke-width:2.1;marker-end:url(#arrowRed);opacity:.85;filter:url(#glow)}.qedge.sign_off{stroke:var(--cyan);opacity:.7}.qedge.selected{opacity:1;stroke-width:3;filter:url(#glow);animation:qflowDash 1.5s linear infinite}.qedge-hit{fill:none;stroke:transparent;stroke-width:13;cursor:pointer;pointer-events:stroke}.qflow-inspector{border-left:1px solid #1d3042;background:linear-gradient(180deg,#09131f,#060b12);padding:16px 14px;overflow:auto;position:relative}.qflow-inspector:before{content:"NEURAL INSPECTOR";position:absolute;right:-29px;top:93px;transform:rotate(90deg);font:700 7px ui-monospace,monospace;letter-spacing:2px;color:#253e53}.qflow-inspector-head{display:flex;justify-content:space-between;align-items:center;color:#5b758c;font:700 7px ui-monospace,monospace;letter-spacing:1.2px}.qflow-inspector-head b{color:var(--cyan);font-size:7px}.qflow-inspector h3{margin:17px 0 4px;font-size:18px;letter-spacing:-.03em}.qflow-inspector>p{margin:0}.qflow-inspector #inspectSubtitle{color:#637b90;font:650 8px ui-monospace,monospace;letter-spacing:.9px}.qflow-gauge{height:3px;background:#142333;margin:14px 0;border-radius:2px;overflow:hidden}.qflow-gauge i{display:block;height:100%;width:70%;background:linear-gradient(90deg,#1c8eff,var(--cyan));box-shadow:0 0 12px var(--cyan)}.qflow-stats{display:grid;grid-template-columns:1fr 1fr;gap:6px}.qflow-stat{border:1px solid #1c3042;border-radius:8px;background:#0a1520;padding:8px}.qflow-stat small{display:block;color:#536b7e;font:650 6px ui-monospace,monospace;letter-spacing:.8px}.qflow-stat b{display:block;margin-top:5px;font:750 10px ui-monospace,monospace;color:#cfe4f3}.qflow-detail{color:#8da0b2;font-size:10px;line-height:1.55;margin:13px 0!important;max-height:104px;overflow:auto}.qflow-events{display:flex;flex-direction:column;gap:5px;margin-top:10px}.qflow-event{padding:7px 8px;border-left:2px solid #294258;background:#0a131d;color:#7890a5;font-size:8px;line-height:1.4}.qflow-event.challenge,.qflow-event.veto{border-left-color:var(--amber);color:#d3b779}.qflow-actions{display:flex;flex-wrap:wrap;gap:5px;margin-top:14px}.qflow-actions button{height:32px}.qflow-footer{height:34px;flex:0 0 34px;display:flex;align-items:center;gap:13px;padding:0 14px;border-top:1px solid #1c2e40;color:#50677b;font:650 6.5px ui-monospace,monospace;letter-spacing:.65px}.qflow-footer .live{color:var(--green)}.qflow-footer .review{color:var(--amber)}.qflow-footer .idle{color:#6d7e8f}.qflow-footer strong{margin-left:auto;color:#6f879a}@keyframes qflowSpin{to{transform:rotate(360deg)}}@keyframes qflowPulse{50%{opacity:.35;transform:scale(.92)}}@keyframes qflowRadar{to{transform:rotate(360deg)}}@keyframes qflowDash{to{stroke-dashoffset:-34}}@media(max-width:850px){.qflow-body{grid-template-columns:minmax(0,1fr) 240px}.qflow-brand{min-width:150px}.qflow-controls button[data-filter]{display:none}.qflow-inspector{padding:12px 10px}.qflow-search-wrap{display:none}}
"""


GRAPH_JS = r"""
export default function({parentElement,data,setStateValue,setTriggerValue,key}){
  const root=parentElement.querySelector('.qflow'),viewport=parentElement.querySelector('#viewport'),scene=parentElement.querySelector('#scene');
  const nodeLayer=parentElement.querySelector('#nodeLayer'),edgeLayer=parentElement.querySelector('#edgeLayer');
  const nodes=Array.isArray(data?.nodes)?data.nodes:[],edges=Array.isArray(data?.edges)?data.edges:[];
  const byId=new Map(nodes.map(n=>[n.id,n]));
  let selected=data?.selected||{kind:'node',id:'cio'},zoom=Number(data?.zoom||.72),pan={x:16,y:18};
  let filters={evidence:true,consult:true,challenge:true},draggingCanvas=false,canvasStart=null,moved=false;
  const storageKey='qai-layout-'+String(data?.layout_key||'default');
  let positions={};try{positions=JSON.parse(localStorage.getItem(storageKey)||'{}')}catch(e){positions={}}
  const make=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=String(text);return e};
  const defaults=()=>{const p={cio:{x:572,y:34},human_ic:{x:572,y:980}};let ai=0,ti=0;nodes.forEach(n=>{if(n.type==='agent'){p[n.id]={x:78+(ai%4)*292,y:175+Math.floor(ai/4)*132};ai++}else if(n.type==='tool'){p[n.id]={x:42+(ti%5)*250,y:490+Math.floor(ti/5)*104};ti++}});return p};
  const base=defaults();nodes.forEach(n=>{if(!positions[n.id])positions[n.id]=base[n.id]||{x:40,y:40}});
  const persist=()=>{try{localStorage.setItem(storageKey,JSON.stringify(positions))}catch(e){}};
  const applyTransform=()=>{scene.style.transform=`translate(${pan.x}px,${pan.y}px) scale(${zoom})`};
  const edgeGroup=k=>['consult','support'].includes(k)?'consult':['challenge','veto'].includes(k)?'challenge':'evidence';
  const edgeVisible=e=>filters[edgeGroup(e.kind)]!==false;
  const pathFor=(a,b)=>{const sx=a.x+(a.w||206)/2,sy=a.y+(a.h||86)/2,tx=b.x+(b.w||206)/2,ty=b.y+(b.h||86)/2;const my=sy+(ty-sy)*.48;return `M ${sx} ${sy} C ${sx} ${my}, ${tx} ${my}, ${tx} ${ty}`};
  const dims=n=>n.type==='cio'||n.type==='human'?{w:236,h:n.type==='cio'?104:86}:n.type==='tool'?{w:190,h:72}:{w:206,h:86};
  function renderEdges(){edgeLayer.replaceChildren();edges.forEach((e,i)=>{if(!byId.has(e.source)||!byId.has(e.target)||!edgeVisible(e))return;const a={...positions[e.source],...dims(byId.get(e.source))},b={...positions[e.target],...dims(byId.get(e.target))};const d=pathFor(a,b);const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',d);p.setAttribute('class','qedge '+String(e.kind||'flow')+(selected?.kind==='edge'&&String(selected.id)===String(i)?' selected':''));const hit=document.createElementNS('http://www.w3.org/2000/svg','path');hit.setAttribute('d',d);hit.setAttribute('class','qedge-hit');hit.onclick=()=>selectEdge(i);edgeLayer.append(p,hit)})}
  function nodeButton(n){const b=make('button','qnode '+n.type+' '+n.status+(n.enabled===false?' disabled':'')+(selected?.kind==='node'&&selected.id===n.id?' selected':''));b.type='button';b.dataset.id=n.id;b.setAttribute('aria-label',`${n.label}, ${n.subtitle}`);const pos=positions[n.id];b.style.left=pos.x+'px';b.style.top=pos.y+'px';const id=make('div','qnode-id');id.append(make('i','qnode-dot'),make('span','',n.label));const role=make('div','qnode-role',n.subtitle);const foot=make('div','qnode-foot');foot.append(make('span','',n.type.toUpperCase()),make('strong','',n.status_label||n.status));b.append(id,role,foot);let start=null,origin=null,wasDrag=false;b.onpointerdown=ev=>{if(ev.button!==0)return;start={x:ev.clientX,y:ev.clientY};origin={...positions[n.id]};wasDrag=false;b.setPointerCapture(ev.pointerId)};b.onpointermove=ev=>{if(!start)return;const dx=(ev.clientX-start.x)/zoom,dy=(ev.clientY-start.y)/zoom;if(Math.abs(dx)+Math.abs(dy)>4)wasDrag=true;positions[n.id]={x:Math.max(0,origin.x+dx),y:Math.max(0,origin.y+dy)};b.style.left=positions[n.id].x+'px';b.style.top=positions[n.id].y+'px';renderEdges()};b.onpointerup=()=>{if(wasDrag)persist();start=null};b.onclick=()=>{if(!wasDrag)selectNode(n.id)};return b}
  function renderNodes(){nodeLayer.replaceChildren();nodes.forEach(n=>nodeLayer.appendChild(nodeButton(n)))}
  const stat=(label,value)=>{const d=make('div','qflow-stat');d.append(make('small','',label),make('b','',value));return d};
  function renderInspector(){const isEdge=selected?.kind==='edge',item=isEdge?edges[Number(selected.id)]:byId.get(selected?.id)||byId.get('cio');if(!item)return;parentElement.querySelector('#inspectType').textContent=isEdge?'INTERACTION':String(item.type||'NODE').toUpperCase();parentElement.querySelector('#inspectState').textContent=String(item.status_label||item.status||item.kind||'READY').toUpperCase();parentElement.querySelector('#inspectTitle').textContent=isEdge?`${item.source} → ${item.target}`:item.label;parentElement.querySelector('#inspectSubtitle').textContent=isEdge?String(item.kind||'FLOW').toUpperCase():item.subtitle;const score=isEdge?Number(item.evidence_count||0)*12:Number(item.confidence||item.quality||.72)*100;parentElement.querySelector('#inspectGauge').style.width=Math.max(8,Math.min(100,score))+'%';const stats=parentElement.querySelector('#inspectStats');stats.replaceChildren();if(isEdge){stats.append(stat('KIND',String(item.kind||'flow').toUpperCase()),stat('EVIDENCE',item.evidence_count||0),stat('STATUS',String(item.status||'ready').toUpperCase()),stat('IMPACT',item.effect?'RECORDED':'TRACE'))}else{stats.append(stat('STATUS',String(item.status_label||item.status).toUpperCase()),stat('LINKS',edges.filter(e=>e.source===item.id||e.target===item.id).length),stat('EVIDENCE',item.evidence_count||0),stat('PRIORITY',item.priority??'—'))}parentElement.querySelector('#inspectDetail').textContent=isEdge?(item.message||item.effect||'Verified interaction trace.'):(item.detail||'No additional node detail.');const events=parentElement.querySelector('#inspectEvents');events.replaceChildren();edges.filter(e=>!isEdge&&(e.source===item.id||e.target===item.id)).slice(-5).forEach(e=>{events.append(make('div','qflow-event '+e.kind,`${String(e.kind).toUpperCase()} · ${e.source} → ${e.target} · ${e.message||''}`))});const actions=parentElement.querySelector('#inspectActions');actions.replaceChildren();if(!isEdge&&item.type==='agent'){actions.append(actionButton('EDIT DESK','edit_agent',item.id),actionButton(item.enabled===false?'ENABLE':'DISABLE','toggle_agent',item.id))}else if(!isEdge&&item.type==='tool'){actions.append(actionButton('OPEN EVIDENCE','inspect_tool',item.id))}else if(!isEdge&&item.id==='cio'){actions.append(actionButton('EDIT CIO / GOVERNANCE','edit_cio',item.id))}if(isEdge)actions.append(actionButton('FOCUS SOURCE','focus_node',item.source))}
  function actionButton(label,kind,id){const b=make('button','',label);b.type='button';b.onclick=()=>setTriggerValue('action',{kind,id,nonce:Date.now()+'-'+Math.random().toString(16).slice(2)});return b}
  function selectNode(id){selected={kind:'node',id};setStateValue('selected',selected);renderNodes();renderEdges();renderInspector()}
  function selectEdge(i){selected={kind:'edge',id:String(i)};setStateValue('selected',selected);renderNodes();renderEdges();renderInspector()}
  function resetView(resetPositions=false){if(resetPositions){positions=defaults();persist();renderNodes();renderEdges()}const available=Math.max(420,viewport.clientWidth);zoom=Math.max(.56,Math.min(.86,(available-20)/1380));pan={x:12,y:16};applyTransform()}
  parentElement.querySelectorAll('[data-filter]').forEach(b=>{b.onclick=()=>{const k=b.dataset.filter;filters[k]=!filters[k];b.classList.toggle('active',filters[k]);renderEdges()}});
  parentElement.querySelector('#zoomIn').onclick=()=>{zoom=Math.min(1.45,zoom+.1);applyTransform()};parentElement.querySelector('#zoomOut').onclick=()=>{zoom=Math.max(.38,zoom-.1);applyTransform()};parentElement.querySelector('#resetView').onclick=()=>resetView(true);
  const search=parentElement.querySelector('#nodeSearch');search.oninput=()=>{const q=search.value.trim().toLowerCase();nodeLayer.querySelectorAll('.qnode').forEach(b=>{const n=byId.get(b.dataset.id);b.style.opacity=!q||`${n.label} ${n.subtitle} ${n.id}`.toLowerCase().includes(q)?'1':'.12'})};search.onkeydown=e=>{if(e.key==='Enter'){const q=search.value.trim().toLowerCase();const n=nodes.find(x=>`${x.label} ${x.subtitle} ${x.id}`.toLowerCase().includes(q));if(n)selectNode(n.id)}};
  viewport.onwheel=e=>{e.preventDefault();const before=zoom;zoom=Math.max(.38,Math.min(1.5,zoom+(e.deltaY<0?.08:-.08)));const rect=viewport.getBoundingClientRect(),mx=e.clientX-rect.left,my=e.clientY-rect.top;pan.x=mx-(mx-pan.x)*(zoom/before);pan.y=my-(my-pan.y)*(zoom/before);applyTransform()};viewport.onpointerdown=e=>{if(e.target!==viewport)return;draggingCanvas=true;canvasStart={x:e.clientX,y:e.clientY,pan:{...pan}};viewport.setPointerCapture(e.pointerId)};viewport.onpointermove=e=>{if(!draggingCanvas)return;pan={x:canvasStart.pan.x+e.clientX-canvasStart.x,y:canvasStart.pan.y+e.clientY-canvasStart.y};applyTransform()};viewport.onpointerup=()=>{draggingCanvas=false};
  parentElement.querySelector('#graphCount').textContent=`${nodes.length} NODES · ${edges.length} EDGES`;parentElement.querySelector('#missionLabel').textContent=data?.run_id?`RUN ${data.run_id} · ${String(data.request_kind||'general').toUpperCase()}`:'CONFIGURATION MODE · CLIENT EDITABLE';
  renderNodes();renderEdges();renderInspector();resetView(false);
  return()=>{viewport.onwheel=null;viewport.onpointerdown=null;viewport.onpointermove=null;viewport.onpointerup=null};
}
"""


_WORKFLOW_COMPONENT = st.components.v2.component(
    "quant_ai_interactive_workflow_v1",
    html=GRAPH_HTML,
    css=GRAPH_CSS,
    js=GRAPH_JS,
    isolate_styles=True,
)


def _status(value: NodeStatus | str | None) -> tuple[str, str]:
    raw = value.value if isinstance(value, NodeStatus) else str(value or "standby")
    if raw == NodeStatus.COMPLETE.value:
        return "complete", "COMPLETE"
    if raw == NodeStatus.PARTIAL.value:
        return "warning", "REVIEW"
    if raw == NodeStatus.ERROR.value:
        return "error", "ERROR"
    if raw == NodeStatus.NOT_AVAILABLE.value:
        return "standby", "NO DATA"
    if raw == NodeStatus.RUNNING.value:
        return "complete", "WORKING"
    return "standby", "STANDBY"


def workflow_payload(organization: OrganizationConfig, run: CommitteeRun | None = None) -> dict[str, Any]:
    reports = {report.agent_id: report for report in run.reports} if run else {}
    planned = {step.specialist for step in run.plan.steps} if run else set()
    nodes: list[dict[str, Any]] = [
        {
            "id": "cio",
            "type": "cio",
            "label": "CIO / JARVIS CORE",
            "subtitle": "MASTER ORCHESTRATOR · RISK GATE",
            "status": "complete" if run else "standby",
            "status_label": run.brief.decision if run else "READY",
            "detail": run.brief.executive_summary if run else organization.cio_prompt,
            "confidence": run.brief.confidence if run else 0.72,
            "evidence_count": sum(bool(result.evidence) for result in run.tools.values()) if run else 0,
            "priority": "CIO",
            "enabled": True,
        },
        {
            "id": "human_ic",
            "type": "human",
            "label": "HUMAN INVESTMENT COMMITTEE",
            "subtitle": "FINAL AUTHORITY · CAPITAL APPROVAL",
            "status": "warning" if run else "standby",
            "status_label": "APPROVAL REQUIRED" if run else "STANDBY",
            "detail": "No trade, rebalance, hedge or allocation is authorized without explicit human approval.",
            "confidence": 1.0,
            "evidence_count": 0,
            "priority": "GATE",
            "enabled": True,
        },
    ]
    tool_names: list[str] = []
    for agent in organization.agents:
        report = reports.get(agent.id)
        state, state_label = _status(report.status if report else NodeStatus.PENDING)
        if not agent.enabled:
            state, state_label = "standby", "DISABLED"
        elif run and agent.id not in planned:
            state, state_label = "standby", "NOT ROUTED"
        elif report and report.stance in {"HEDGE", "REDUCE", "AVOID", "ABSTAIN"}:
            state, state_label = "warning", report.stance
        nodes.append(
            {
                "id": agent.id,
                "type": "agent",
                "label": agent.name.upper(),
                "subtitle": agent.role,
                "status": state,
                "status_label": state_label,
                "detail": report.thesis if report else agent.mandate,
                "confidence": report.confidence if report else max(0.05, min(1.0, agent.priority / 100.0)),
                "evidence_count": len(report.evidence_used) if report else len(agent.tools),
                "priority": agent.priority,
                "enabled": agent.enabled,
                "model": agent.model,
                "tools": list(agent.tools),
                "consults": list(agent.consults),
            }
        )
        tool_names.extend(agent.tools)
    if run:
        tool_names = list(run.plan.required_tools) + tool_names
    tool_names = [name for name in dict.fromkeys(tool_names) if name != "section_inventory"]
    for name in tool_names:
        result = run.tools.get(name) if run else None
        state, state_label = _status(result.status if result else NodeStatus.PENDING)
        nodes.append(
            {
                "id": name,
                "type": "tool",
                "label": TOOL_LABELS.get(name, name.replace("_", " ").upper()),
                "subtitle": "DETERMINISTIC EVIDENCE ENGINE",
                "status": state,
                "status_label": state_label,
                "detail": "; ".join(result.warnings[:3]) if result and result.warnings else "Connected terminal evidence adapter.",
                "confidence": 0.92 if result and result.status == NodeStatus.COMPLETE else 0.45,
                "evidence_count": len(result.evidence) if result else 0,
                "priority": "DATA",
                "enabled": True,
            }
        )

    node_ids = {node["id"] for node in nodes}
    edges: list[dict[str, Any]] = []
    if run:
        for event in run.interactions:
            if event.source not in node_ids or event.target not in node_ids:
                continue
            edges.append(
                {
                    "source": event.source,
                    "target": event.target,
                    "kind": event.kind,
                    "status": event.status.value,
                    "message": event.message,
                    "effect": event.effect,
                    "evidence_count": len(event.evidence),
                }
            )
    else:
        for agent in organization.agents:
            edges.append({"source": "cio", "target": agent.id, "kind": "dispatch", "status": "pending", "message": "Configured CIO dispatch and reporting line.", "effect": "", "evidence_count": 0})
            for tool in agent.tools:
                if tool in node_ids:
                    edges.append({"source": agent.id, "target": tool, "kind": "tool_call", "status": "pending", "message": "Configured evidence dependency.", "effect": "", "evidence_count": 0})
            for target in agent.consults:
                if target in node_ids:
                    edges.append({"source": agent.id, "target": target, "kind": "consult", "status": "pending", "message": "Configured peer consultation.", "effect": "", "evidence_count": 0})
        edges.append({"source": "risk_manager", "target": "cio", "kind": "sign_off", "status": "pending", "message": "Configured Chief Risk gate.", "effect": "", "evidence_count": 0})
        edges.append({"source": "cio", "target": "human_ic", "kind": "synthesis", "status": "pending", "message": "Final proposal requires human approval.", "effect": "", "evidence_count": 0})
    return {
        "nodes": nodes,
        "edges": edges,
        "run_id": run.run_id if run else "",
        "request_kind": run.plan.request_kind if run else "configuration",
        "layout_key": f"org-{organization.version}-{'live' if run else 'config'}",
    }


def render_interactive_workflow(
    organization: OrganizationConfig,
    run: CommitteeRun | None = None,
    selected: dict[str, Any] | None = None,
    *,
    key: str = "qai_workflow_component",
) -> dict[str, Any]:
    initial = selected or {"kind": "node", "id": "cio"}
    result = _WORKFLOW_COMPONENT(
        data={**workflow_payload(organization, run), "selected": initial},
        default={"selected": initial},
        on_selected_change=lambda: None,
        on_action_change=lambda: None,
        key=key,
        width="stretch",
        height=760,
    )
    return {
        "selected": getattr(result, "selected", initial) or initial,
        "action": getattr(result, "action", None),
    }
