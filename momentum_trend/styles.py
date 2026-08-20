TERMINAL_CSS = r"""
<style>
:root {
  --mt-bg: #061019;
  --mt-panel: #0a1824;
  --mt-panel-2: #0d1e2b;
  --mt-line: rgba(104, 177, 211, .18);
  --mt-text: #e8f2f8;
  --mt-muted: #89a1af;
  --mt-cyan: #20c8e8;
  --mt-blue: #448cff;
  --mt-green: #2ed6a1;
  --mt-amber: #f4bf58;
  --mt-red: #ff6174;
}
.stApp { background: radial-gradient(circle at 85% -10%, rgba(20,111,149,.14), transparent 32%), #050d14; }
[data-testid="stMainBlockContainer"] { max-width: 1680px; padding-top: 1.2rem; }
.mt-shell { border: 1px solid var(--mt-line); border-radius: 13px; background: linear-gradient(135deg, rgba(12,32,45,.96), rgba(6,17,26,.96)); overflow: hidden; }
.mt-command { display:grid; grid-template-columns: minmax(250px,1.7fr) repeat(5,minmax(100px,.7fr)); min-height:92px; }
.mt-brand, .mt-command-cell { padding:16px 18px; display:flex; flex-direction:column; justify-content:center; }
.mt-command-cell { border-left:1px solid var(--mt-line); }
.mt-eyebrow { color:var(--mt-cyan); font:700 10px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing:.20em; text-transform:uppercase; }
.mt-title { color:var(--mt-text); font:700 23px/1.15 Inter, sans-serif; margin-top:5px; letter-spacing:-.025em; }
.mt-sub { color:var(--mt-muted); font:500 11px/1.35 Inter,sans-serif; margin-top:5px; }
.mt-label { color:#688493; font:700 9px/1.2 ui-monospace,monospace; letter-spacing:.16em; text-transform:uppercase; }
.mt-value { color:var(--mt-text); font:700 14px/1.2 Inter,sans-serif; margin-top:7px; }
.mt-value.good { color:var(--mt-green); } .mt-value.warn { color:var(--mt-amber); } .mt-value.bad { color:var(--mt-red); }
.mt-grid { display:grid; grid-template-columns:repeat(6,minmax(125px,1fr)); gap:10px; margin:12px 0; }
.mt-kpi { min-height:95px; border:1px solid var(--mt-line); border-radius:12px; padding:13px 14px; background:linear-gradient(145deg,rgba(11,28,41,.95),rgba(6,17,26,.88)); }
.mt-kpi .k { color:#7994a3; font:600 10px/1.2 Inter,sans-serif; text-transform:uppercase; letter-spacing:.08em; }
.mt-kpi .v { color:#f3f8fb; font:700 22px/1.1 Inter,sans-serif; margin-top:8px; }
.mt-kpi .d { color:#8ba2af; font:500 10px/1.25 ui-monospace,monospace; margin-top:7px; }
.mt-ticket { border:1px solid var(--mt-line); border-left:4px solid var(--ticket-color,var(--mt-cyan)); border-radius:12px; padding:15px 17px; background:rgba(8,24,35,.92); min-height:145px; }
.mt-ticket .action { color:var(--ticket-color,var(--mt-cyan)); font:800 18px/1.15 ui-monospace,monospace; letter-spacing:.03em; }
.mt-ticket .thesis { color:#dce8ee; font:500 13px/1.55 Inter,sans-serif; margin-top:10px; }
.mt-ticket .meta { color:#89a1af; font:500 10px/1.5 ui-monospace,monospace; margin-top:10px; }
.mt-status-row { display:flex; gap:8px; flex-wrap:wrap; margin:7px 0 11px; }
.mt-pill { border:1px solid var(--mt-line); border-radius:999px; padding:5px 9px; color:#adc0ca; background:#091722; font:600 10px/1 ui-monospace,monospace; }
.mt-pill.good { color:var(--mt-green); border-color:rgba(46,214,161,.25); }
.mt-pill.warn { color:var(--mt-amber); border-color:rgba(244,191,88,.28); }
.mt-pill.bad { color:var(--mt-red); border-color:rgba(255,97,116,.28); }
[data-testid="stMetric"] { border:1px solid var(--mt-line); background:#091722; border-radius:10px; padding:11px 13px; }
[data-testid="stMetricLabel"] { color:#819ba8; }
[data-testid="stMetricValue"] { color:#edf6fa; }
[data-testid="stTabs"] button { font-family:ui-monospace,monospace; font-size:12px; }
[data-testid="stDataFrame"] { border:1px solid var(--mt-line); border-radius:9px; overflow:hidden; }
div[data-testid="stExpander"] { border-color:var(--mt-line); background:rgba(7,19,28,.7); }
@media(max-width:1100px){.mt-command{grid-template-columns:1fr 1fr 1fr}.mt-brand{grid-column:1/-1}.mt-command-cell{border-top:1px solid var(--mt-line)}.mt-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.mt-command{grid-template-columns:1fr 1fr}.mt-grid{grid-template-columns:repeat(2,1fr)}.mt-kpi .v{font-size:18px}}
</style>
"""

