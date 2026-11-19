"""Dashboard Streamlit sobre MongoDB, Cassandra y Neo4j; horas en UTC.

Uso: streamlit run dashboard/app.py
"""
from __future__ import annotations

import html
import math
import re
import sys
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config  # noqa: E402
from kpis import INTERMITTENT_TYPES  # noqa: E402

SERIES = ["#d9691e", "#6b3e24", "#e0a526", "#3f8a84", "#b23a2a", "#6b7329", "#c49a6c", "#8a4f6d"]
INK, INK2, MUTED, GRID, AXIS = "#2b1a10", "#55392a", "#7a6250", "#e9dec9", "#c9b99f"
BG, CARD, BAND, NEUTRAL = "#f8f1e4", "#fffaf0", "#efe4cf", "#a8957c"
OTHER = "#c9b99f"
FILL_ALPHA = 0.8
MAIN_TYPES = 4
ACCENT, ACCENT_SOFT = "#d9691e", "#f0c08f"
POS, NEG = "#d9691e", "#6b3e24"
FONT = "IBM Plex Sans, Inter, Segoe UI, system-ui, sans-serif"
DB_COLOR = {"Cassandra": "#c2570f", "MongoDB": "#6b7329", "Neo4j": "#6b3e24"}

DARK_MODE = st.session_state.get("modo_oscuro", False)
if DARK_MODE:
    INK, INK2, MUTED, GRID, AXIS = "#f3e6d5", "#ddc8b2", "#baa58e", "#44392f", "#79634e"
    BG, CARD, BAND, NEUTRAL = "#201b17", "#2b241e", "#352c24", "#ad9479"

EVENT_ES = {
    "PullRequestEvent": "Pull request", "IssuesEvent": "Issue", "IssueCommentEvent": "Comentario en issue/PR",
    "PullRequestReviewEvent": "Revisión de PR", "PullRequestReviewCommentEvent": "Comentario de revisión",
    "WatchEvent": "Estrella", "PushEvent": "Push", "CreateEvent": "Creación de rama/tag",
    "DeleteEvent": "Borrado de rama/tag", "ReleaseEvent": "Release", "ForkEvent": "Fork",
    "MemberEvent": "Alta de colaborador", "CommitCommentEvent": "Comentario en commit",
    "PublicEvent": "Repositorio hecho público", "GollumEvent": "Edición de wiki", "DiscussionEvent": "Discusión",
    "SponsorshipEvent": "Patrocinio",
}
# El color sigue al tipo, no a su posición en el ranking.
TYPE_ORDER = ["PullRequestEvent", "IssuesEvent", "IssueCommentEvent", "PullRequestReviewEvent", "WatchEvent",
              "PushEvent", "CreateEvent", "DeleteEvent"]
TYPE_COLOR = dict(zip(TYPE_ORDER, SERIES))

REL_ES = {"OPENED_PR": "Abrió PR", "OPENED_ISSUE": "Abrió issue", "PUSHED": "Push", "FORKED": "Fork", "STARRED": "Estrella"}
REL_COLOR = dict(zip(REL_ES, SERIES))

PR_ACTION_ES = {
    "opened": "Abierto", "merged": "Fusionado", "closed": "Cerrado sin fusionar", "reopened": "Reabierto",
    "labeled": "Etiquetado", "unlabeled": "Etiqueta retirada", "assigned": "Asignado", "unassigned": "Asignación retirada",
    "synchronize": "Sincronizado", "edited": "Editado", "review_requested": "Revisión solicitada",
    "review_request_removed": "Solicitud de revisión retirada", "ready_for_review": "Listo para revisión",
    "converted_to_draft": "Pasado a borrador", "unknown": "Sin acción",
}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

KPI_DEF = [
    dict(no=1, key="events_per_day", name="Eventos procesados", db="Cassandra", table="events_by_hour",
         long="Número de eventos procesados por día", question="¿Cuánta actividad pública de GitHub ingirió el pipeline en el día?",
         definition="Número de eventos públicos de GitHub procesados por el pipeline en el día (UTC).",
         formula="Σ events_by_hour.event_count  (event_date = D)",
         tex=r"E_D \;=\; \sum_{h \,\in\, H_D} \; \sum_{t} \; n_{D,h,t}",
         symbols="<i>n<sub>D,h,t</sub></i>: eventos del tipo <i>t</i> en la hora <i>h</i> del día <i>D</i> (una fila de "
                 "<code>events_by_hour</code>). <i>H<sub>D</sub></i>: horas cargadas del día.",
         reading="Volumen de actividad ingerido; base de los demás indicadores. Solo es comparable entre días con las mismas "
                 "horas cargadas y la misma cobertura de Push: para comparar días conviene mirar los tipos estables "
                 "(sin Push ni creación o borrado de ramas, que GH Archive 2026 entrega de forma intermitente).",
         lang="sql", impl="SELECT event_hour, event_type, event_count\nFROM events_by_hour\nWHERE event_date = '{d}';\n"
                          "-- E_D = suma de event_count de toda la partición"),
    dict(no=2, key="daily_growth_pct", name="Crecimiento diario", db="Cassandra", table="events_by_hour",
         long="Crecimiento diario de eventos", question="¿La actividad sube o baja respecto del día anterior?",
         definition="Variación porcentual, respecto del día anterior, del volumen de tipos estables (todos menos Push y "
                    "creación o borrado de ramas), sobre las horas cargadas en ambos días.",
         formula="(S_D(H) − S_D−1(H)) / S_D−1(H) × 100,  S = tipos estables, H = horas presentes en D y D−1",
         tex=r"\begin{gathered} G_D \;=\; \frac{S_D(H) - S_{D-1}(H)}{S_{D-1}(H)} \times 100 \\[2pt] H = H_D \cap H_{D-1} \end{gathered}",
         symbols="<i>S<sub>D</sub>(H)</i>: eventos de tipos estables del día <i>D</i> sumando solo las horas de <i>H</i>, el "
                 "conjunto de horas cargadas en ambos días. Se excluyen Push, creación y borrado de ramas porque GH Archive 2026 "
                 "los entrega de forma intermitente. Sin datos del día anterior el indicador no se calcula (N/D).",
         reading="G &gt; 0: la actividad crece; G &lt; 0: disminuye. Al excluir los tipos intermitentes, un hueco de cobertura "
                 "del feed de GH Archive no se lee como una caída o subida de actividad.",
         lang="sql", impl="SELECT event_hour, event_type, event_count FROM events_by_hour WHERE event_date = '{d}';\n"
                          "SELECT event_hour, event_type, event_count FROM events_by_hour WHERE event_date = '{d1}';\n"
                          "-- se suman las horas presentes en ambas particiones,\n"
                          "-- sin PushEvent, CreateEvent ni DeleteEvent"),
    dict(no=3, key="avg_events_per_user", name="Eventos por usuario", db="Cassandra", table="daily_totals",
         long="Promedio de actividad por usuario", question="¿Con qué intensidad participa cada usuario activo?",
         definition="Promedio de eventos por usuario activo (actor distinto) en el día.",
         formula="E_D / daily_totals.unique_users(D)",
         tex=r"A_D \;=\; \frac{E_D}{U_D}",
         symbols="<i>E<sub>D</sub></i>: eventos del día (KPI 1). <i>U<sub>D</sub></i>: usuarios distintos (actores) del día, "
                 "<code>daily_totals.unique_users</code>.",
         reading="Intensidad de uso. Valores altos señalan cuentas muy activas o automatizadas (bots); como la distribución es "
                 "muy asimétrica, el promedio describe intensidad, no al usuario típico.",
         lang="sql", impl="SELECT total_events, unique_users\nFROM daily_totals\nWHERE year = {y} AND event_date = '{d}';"),
    dict(no=4, key="pr_merge_rate_pct", name="Tasa de fusión de PR", db="MongoDB", table="payload.action",
         long="Tasa de fusión de pull requests", question="¿Qué proporción de los pull requests cerrados se acepta?",
         definition="Porcentaje de los pull requests cerrados en el día que fueron fusionados (aceptados).",
         formula="merged_D / (merged_D + closed_D) × 100,  según payload.action",
         tex=r"T_D \;=\; \frac{F_D}{F_D + N_D} \times 100",
         symbols="<i>F<sub>D</sub></i>: PullRequestEvent del día con <code>payload.action = merged</code> (fusionados). "
                 "<i>N<sub>D</sub></i>: con <code>payload.action = closed</code> (cerrados sin fusionar).",
         reading="Salud del flujo de contribución: cuánto de lo que se revisa termina aceptándose. Solo se calcula desde el "
                 "documento original, porque Cassandra no guarda <code>payload.action</code>.",
         lang="javascript", impl='db.events.aggregate([\n  { $match: {\n      type: "PullRequestEvent",\n      created_at: {\n'
                                 '        $gte: ISODate("{d}T00:00:00Z"),\n        $lt:  ISODate("{dn}T00:00:00Z") } } },\n'
                                 '  { $group: { _id: "$payload.action", n: { $sum: 1 } } }\n])'),
    dict(no=5, key="top_repo_connections", name="Repositorio más conectado", db="Neo4j", table="(:User)-[]->(:Repo)",
         long="Repositorio con mayor número de conexiones", question="¿Qué proyecto concentra más comunidad?",
         definition="Repositorio con más usuarios distintos conectados (grado del nodo) en el grafo acumulado hasta el final del día.",
         formula="MATCH (u:User)-[x]->(r:Repo) WHERE x.first_seen < fin(D) RETURN r, count(DISTINCT u) ORDER BY 2 DESC LIMIT 1",
         tex=r"\begin{gathered} r^{*}_D \;=\; \arg\max_{r} \; \deg_D(r) \\[2pt] \deg_D(r) = \left|\{\, u : (u) \rightarrow (r),\; t_{u,r} \le D \,\}\right| \end{gathered}",
         symbols="<i>deg<sub>D</sub>(r)</i>: usuarios distintos con al menos una relación (Push, PR, issue, estrella o fork) hacia "
                 "el repositorio <i>r</i> cuya primera interacción (<i>t<sub>u,r</sub></i>, propiedad <code>first_seen</code>) "
                 "ocurrió hasta el día <i>D</i>.",
         reading="Proyecto que concentra comunidad. Un grado anómalo, o un vecindario dominado por estrellas o cuentas "
                 "automatizadas, puede delatar actividad artificial.",
         lang="cypher", impl="MATCH (u:User)-[x]->(r:Repo)\nWHERE x.first_seen < datetime('{dn}T00:00:00Z')\n"
                             "RETURN r.name AS repositorio, count(DISTINCT u) AS grado\nORDER BY grado DESC LIMIT 1"),
]

LAYOUT = dict(
    font=dict(family=FONT, color=INK2, size=13),
    margin=dict(l=4, r=8, t=8, b=4),
    paper_bgcolor=BG, plot_bgcolor=BG, separators=".,",
    hoverlabel=dict(bgcolor=CARD, bordercolor="#cdbb9f", font=dict(color=INK, size=13, family=FONT), align="left"),
    xaxis=dict(showgrid=False, showline=True, linecolor=AXIS, ticks="", tickfont=dict(color=INK2, size=12),
               title=dict(font=dict(color=MUTED, size=12), standoff=10), fixedrange=False, automargin=True),
    yaxis=dict(showgrid=True, gridcolor=GRID, zeroline=False, showline=False, tickfont=dict(color=INK2, size=12),
               title=dict(font=dict(color=MUTED, size=12), standoff=10), fixedrange=False, automargin=True),
    legend=dict(orientation="h", x=0, xanchor="left", y=1.02, yanchor="bottom", font=dict(color=INK2, size=12),
                bgcolor="rgba(0,0,0,0)", itemclick=False, itemdoubleclick=False),
    showlegend=False,
)
PLOTLY_CONFIG = {
    "displayModeBar": "hover",
    "displaylogo": False,
    "scrollZoom": True,
    "doubleClick": "reset",
    "modeBarButtons": [["zoom2d", "pan2d", "zoomIn2d", "zoomOut2d", "resetScale2d"]],
}

CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root { --ink:#2b1a10; --ink2:#55392a; --muted:#7a6250; --hair:#e9dec9; --hair2:#dccdb3; --rule:#bfa98a; --bg:#f8f1e4; --card:#fffaf0; --panel:#efe4cf; --brand:#a8480f; --data:#d9691e; }
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] * { font-family:'IBM Plex Sans', Inter, 'Segoe UI', system-ui, sans-serif; }
[data-testid="stIconMaterial"] { font-family:'Material Symbols Rounded' !important; }
code, pre, pre *, [data-testid="stCode"] * { font-family:'IBM Plex Mono', ui-monospace, Menlo, monospace !important; }
.katex { font-family:KaTeX_Main, 'Times New Roman', serif; }
.katex * { font-family:inherit; }
.katex-display { padding:.4em 0 .3em; overflow:visible !important; }
[data-testid="stMarkdownContainer"]:has(> .katex-display) { overflow:visible !important; }
[data-testid="stAppDeployButton"] { display:none; }
[data-testid="stAppViewContainer"] { color:var(--ink); background:var(--bg); }
.block-container { padding-top:4.5rem; padding-bottom:3rem; max-width:1480px; }
[data-testid="stWidgetLabel"] p { font-size:.78rem !important; font-weight:600; color:var(--ink2); text-transform:uppercase; letter-spacing:.05em; }
[data-testid="stTab"] p { font-size:1rem !important; font-weight:600 !important; color:var(--ink2); }
[data-testid="stTab"][aria-selected="true"] p { color:var(--brand); }
[data-testid="stExpander"] summary p { font-weight:600; color:var(--ink2); }
code { font-size:.86em; color:var(--ink2); background:var(--panel); padding:1px 5px; border-radius:4px; }
.hdr { border-bottom:1px solid var(--hair2); padding-bottom:16px; }
.overline { font-size:.76rem; font-weight:600; letter-spacing:.09em; text-transform:uppercase; color:var(--brand); }
.title { font-size:2rem; font-weight:700; color:var(--ink); letter-spacing:-.015em; line-height:1.15; margin:6px 0; }
.lede { font-size:1rem; color:var(--ink2); margin:0; max-width:92ch; line-height:1.5; }
.meta { display:flex; flex-wrap:wrap; gap:6px 26px; margin-top:12px; font-size:.88rem; color:var(--ink); }
.meta b { color:var(--muted); font-weight:600; margin-right:6px; text-transform:uppercase; font-size:.7rem; letter-spacing:.07em; }
.sec { margin-top:26px; padding-top:16px; border-top:1px solid var(--hair); }
.sec .h { font-size:1.2rem; font-weight:600; color:var(--ink); }
.sec .p { font-size:.9rem; color:var(--muted); margin-top:2px; max-width:120ch; line-height:1.45; }
.tab-lead { font-size:.92rem; color:var(--ink2); margin:4px 0 0; max-width:125ch; line-height:1.5; }
.fig-t { font-size:1rem; font-weight:600; color:var(--ink); margin-top:2px; }
.fig-t .n { color:var(--muted); margin-right:8px; font-size:.76rem; letter-spacing:.06em; text-transform:uppercase; }
.fig-s { font-size:.84rem; color:var(--muted); margin-top:1px; }
.fig-note { font-size:.84rem; color:var(--ink2); line-height:1.5; border-left:2px solid var(--hair2); padding:1px 0 1px 10px; }
.fig-note b { color:var(--ink); font-weight:600; }
.fig-note .src { color:var(--muted); }
.tiles { display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:14px; }
@media (max-width:1180px) { .tiles { grid-template-columns:repeat(3, minmax(0, 1fr)); } }
@media (max-width:720px) { .tiles { grid-template-columns:1fr; } }
.tile { background:var(--card); border:1px solid var(--hair2); border-top:4px solid var(--db); border-radius:8px; padding:13px 16px 11px; display:flex; flex-direction:column; gap:6px; min-width:0; cursor:help; }
.tile-no { font-size:.68rem; font-weight:600; color:var(--muted); letter-spacing:.08em; margin-bottom:-4px; }
.tile-label { font-size:.92rem; font-weight:600; color:var(--ink2); }
.tile-value { font-size:2.25rem; font-weight:600; color:var(--ink); line-height:1.12; letter-spacing:-.01em; }
.tile-value .u { font-size:1.2rem; font-weight:500; color:var(--ink2); margin-left:3px; }
.tile-value.name { font-size:1.45rem; line-height:1.22; overflow-wrap:anywhere; }
.tile-value.name.long { font-size:1.15rem; }
.tile-ctx { font-size:.86rem; color:var(--ink2); line-height:1.42; }
.tile-src { margin-top:auto; padding-top:8px; border-top:1px solid var(--hair); font-size:.76rem; color:var(--muted); display:flex; flex-direction:column; align-items:flex-start; gap:3px; }
.tile-src code { font-size:.72rem; padding:0 4px; white-space:nowrap; max-width:100%; overflow:hidden; text-overflow:ellipsis; }
.sw { display:inline-block; width:9px; height:9px; border-radius:2px; }
.up { color:#4f5a12; } .down { color:#a52a1c; } .na { color:var(--muted); }
.arr { font-size:.5em; vertical-align:.32em; margin-right:4px; }
.nw { white-space:nowrap; }
.tiles-foot { display:flex; flex-wrap:wrap; gap:4px 18px; font-size:.8rem; color:var(--muted); }
.tiles-foot span { display:inline-flex; align-items:center; gap:6px; }
.badge { display:inline-block; font-size:.7rem; font-weight:600; letter-spacing:.03em; padding:1px 8px; border-radius:999px; border:1px solid var(--hair2); color:var(--ink2); background:var(--panel); white-space:nowrap; vertical-align:1px; }
.badge.warn { color:#7a4a00; background:#fdecc8; border-color:#e8c27a; }
.badge.ok { color:#4a5216; background:#eef0d4; border-color:#cfd4a0; }
.callout { display:flex; gap:10px 14px; align-items:center; flex-wrap:wrap; border:1px solid #e8c27a; background:#fdecc8; border-radius:8px; padding:10px 14px; font-size:.9rem; color:#4d3300; line-height:1.45; }
.strip { display:inline-flex; gap:1px; vertical-align:middle; }
.strip i { display:inline-block; width:7px; height:14px; border-radius:1px; background:#e4d8c2; }
.strip i.on { background:var(--data); }
.strip i.g { margin-left:3px; }
.stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:12px; }
.stat { border:1px solid var(--hair2); border-radius:8px; padding:10px 14px; background:var(--card); }
.stat .l { font-size:.72rem; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
.stat .v { font-size:1.55rem; font-weight:600; color:var(--ink); line-height:1.25; margin-top:2px; }
.stat .s { font-size:.8rem; color:var(--ink2); margin-top:2px; line-height:1.4; }
table.t { width:100%; border-collapse:collapse; font-size:.9rem; }
table.t th { text-align:left; font-size:.7rem; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; padding:8px 10px; border-bottom:1px solid var(--rule); white-space:nowrap; }
table.t th.sorted { color:var(--brand); }
table.t td { padding:7px 10px; border-bottom:1px solid var(--hair); color:var(--ink); vertical-align:middle; }
table.t tbody tr:last-child td { border-bottom:1px solid var(--rule); }
table.t .num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
table.t td.rk { color:var(--muted); width:2.2em; font-variant-numeric:tabular-nums; }
table.t td.nm { font-weight:500; min-width:9em; }
a.github-link { color:var(--ink); text-decoration:underline; text-underline-offset:3px; }
a.github-link:hover { color:var(--brand); }
a.github-link:focus-visible { outline:2px solid var(--brand); outline-offset:3px; }
table.t td.nw { white-space:nowrap; }
table.def td { vertical-align:top; font-size:.88rem; line-height:1.45; }
table.def td code { white-space:normal; }
.cb { display:flex; align-items:center; justify-content:flex-end; gap:10px; }
.cb .tr { width:60px; height:6px; background:#eadfca; border-radius:3px; overflow:hidden; flex:none; }
.cb .tr span { display:block; height:100%; background:var(--data); border-radius:3px; }
[data-testid="stCode"] code { font-size:.78rem !important; line-height:1.55 !important; }
.tnote { font-size:.8rem; color:var(--muted); margin-top:6px; line-height:1.45; }
.kf-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.kf-no { font-size:.72rem; font-weight:700; letter-spacing:.07em; color:#fff; background:var(--db); padding:2px 10px; border-radius:999px; }
.kf-db { font-size:.8rem; color:var(--muted); display:inline-flex; align-items:center; gap:6px; }
.kf-title { font-size:1.2rem; font-weight:600; color:var(--ink); margin-top:6px; }
.kf-q { font-size:.9rem; color:var(--muted); font-style:italic; margin-top:1px; }
.kf-lbl { font-size:.72rem; font-weight:600; letter-spacing:.07em; text-transform:uppercase; color:var(--brand); margin-top:6px; }
.kf-txt { font-size:.92rem; color:var(--ink); line-height:1.5; margin-top:2px; }
.kf-sym { font-size:.82rem; color:var(--ink2); line-height:1.5; }
.kf-read { font-size:.9rem; color:var(--ink); line-height:1.5; background:var(--panel); border-radius:6px; padding:8px 12px; margin-top:4px; }
.flow { display:flex; flex-wrap:wrap; align-items:stretch; gap:8px; }
.flow .st { flex:1 1 140px; border:1px solid var(--hair2); border-top:4px solid var(--c); border-radius:8px; padding:10px 12px; background:var(--card); }
.flow .st .k { font-size:.68rem; font-weight:600; color:var(--muted); letter-spacing:.07em; text-transform:uppercase; }
.flow .st .t { font-size:.95rem; font-weight:600; color:var(--ink); margin-top:2px; }
.flow .st .d { font-size:.8rem; color:var(--ink2); margin-top:4px; line-height:1.42; }
.flow .ar { align-self:center; color:var(--muted); }
ul.notes { margin:4px 0 0 1.1em; padding:0; font-size:.9rem; color:var(--ink2); line-height:1.6; max-width:125ch; }
.foot { margin-top:34px; padding-top:14px; border-top:1px solid var(--hair2); font-size:.8rem; color:var(--muted); display:flex; flex-wrap:wrap; gap:6px 24px; justify-content:space-between; }
</style>
"""

if DARK_MODE:
    CSS += """
<style>
:root { --ink:#f3e6d5; --ink2:#ddc8b2; --muted:#baa58e; --hair:#44392f; --hair2:#574737; --rule:#79634e; --bg:#201b17; --card:#2b241e; --panel:#352c24; --brand:#ee9b60; color-scheme:dark; }
[data-testid="stApp"], [data-testid="stHeader"], [data-testid="stToolbar"] { background:var(--bg); color:var(--ink); }
[data-testid="stMarkdownContainer"], [data-testid="stText"], [data-testid="stCaptionContainer"], [data-testid="stIconMaterial"] { color:var(--ink); }
[data-baseweb="select"] > div, [data-baseweb="popover"] > div, [data-baseweb="menu"], [role="listbox"], [role="option"], [data-baseweb="input"], [data-baseweb="input"] input { background:var(--card); color:var(--ink); }
[data-testid="stSelectbox"] [role="group"], [data-testid="stSelectbox"] input, [data-testid="stSelectbox"] button { background:var(--card); color:var(--ink); }
[role="option"]:hover, [aria-selected="true"][role="option"] { background:var(--panel); }
[data-testid="stExpander"], [data-testid="stExpander"] details, [data-testid="stExpander"] summary { background:var(--bg); color:var(--ink); border-color:var(--hair2); }
[data-testid="stCode"], [data-testid="stCode"] pre, [data-testid="stCode"] code, [data-testid="stCode"] span { background:var(--panel); color:var(--ink2); }
[data-testid="stSlider"] [data-testid="stTickBar"], [data-testid="stSlider"] [data-testid="stThumbValue"] { color:var(--ink2); }
[data-testid="stTooltipIcon"] svg, [data-baseweb="select"] svg { fill:var(--ink2); }
.up { color:#c6cf7a; } .down { color:#f09380; }
.badge.warn, .callout { color:#f2d29b; background:#44331d; border-color:#856231; }
.badge.ok { color:#d2d99c; background:#323820; border-color:#69733d; }
.strip i, .cb .tr { background:var(--hair2); }
</style>
"""


def esc(value: object) -> str:
    """Escapa texto antes de incorporarlo al HTML del dashboard."""
    return html.escape(str(value))


def github_link(value: object, kind: str) -> str:
    """Enlaza nombres válidos; conserva como texto bots y nombres no reconocidos."""
    name = str(value)
    label = esc(name).replace("/", "/<wbr>")
    parts = name.split("/")
    valid_owner = re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", parts[0])
    if kind == "repo":
        valid = (len(parts) == 2 and valid_owner and parts[1] not in (".", "..")
                 and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", parts[1]))
    else:
        valid = len(parts) == 1 and valid_owner
    if not valid:
        return label
    url = "https://github.com/" + "/".join(quote(part, safe="") for part in parts)
    return (f'<a class="github-link" href="{esc(url)}" target="_blank" rel="noopener noreferrer" '
            f'title="{esc(f"Abrir {name} en GitHub (nueva pestaña)")}">{label}</a>')


def filter_ranking(df: pd.DataFrame, column: str, query: str) -> pd.DataFrame:
    """Filtra el ranking cargado por texto literal, conservando orden y posiciones."""
    query = query.strip()
    if not query:
        return df
    return df[df[column].str.contains(query, case=False, regex=False, na=False)]


def download_csv(df: pd.DataFrame, filename: str, key: str, **context: object) -> None:
    """Exporta una copia con contexto de fecha y UTF-8 compatible con Excel."""
    st.download_button(
        "Descargar CSV", data=df.assign(**context).to_csv(index=False).encode("utf-8-sig"),
        file_name=filename, mime="text/csv", key=key, disabled=df.empty,
        on_click="ignore",
    )


def fdate(d: date, weekday: bool = False, year: bool = True) -> str:
    s = f"{d.day} {MESES[d.month - 1]}" + (f" {d.year}" if year else "")
    return f"{DIAS[d.weekday()]} {s}" if weekday else s


def fnum(v: float) -> str:
    """Abrevia cantidades con los mismos umbrales usados en las gráficas."""
    if v < 1e5:
        return f"{v:,.0f}"
    if v < 1e6:
        return f"{v / 1e3:.1f} mil"
    return f"{v / 1e6:.2f} M"


def tnum(v: float) -> str:
    return f"{v:,.0f}".replace(",", "{,}")


def tex_escape(text: str) -> str:
    return re.sub(r"([_&%#$])", r"\\\1", text)


def fdt(ts: datetime) -> str:
    return f"{fdate(ts.date())}, {ts:%H:%M} UTC"


def runs_of(values: Iterable[int]) -> list[tuple[int, int]]:
    """Agrupa horas consecutivas para presentar la cobertura de forma compacta."""
    out: list[tuple[int, int]] = []
    for v in sorted(values):
        if out and v == out[-1][1] + 1:
            out[-1] = (out[-1][0], v)
        else:
            out.append((v, v))
    return out


def hours_label(hours: Iterable[int]) -> str:
    return ", ".join(f"{a:02d}–{b:02d} h" if a != b else f"{a:02d} h" for a, b in runs_of(hours)) or "ninguna"


def hour_strip(hours: Iterable[int]) -> str:
    on = set(hours)
    cells = "".join(f'<i class="{"on" if h in on else ""}{" g" if h and h % 6 == 0 else ""}" '
                    f'title="{h:02d}:00–{h:02d}:59 UTC"></i>' for h in range(24))
    return f'<span class="strip">{cells}</span>'


def layout(**overrides) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in LAYOUT.items()}
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def date_axis(d0: date, d1: date, max_ticks: int) -> dict:
    span = (d1 - d0).days + 1
    if span <= max_ticks:
        ticks = [d0 + timedelta(days=i) for i in range(span)]
    else:
        step = 7 * math.ceil(span / 7 / max_ticks)
        first = d0 + timedelta(days=(7 - d0.weekday()) % 7)
        ticks = [first + timedelta(days=i) for i in range(0, (d1 - first).days + 1, step)]
    return dict(type="date", tickmode="array", tickvals=[pd.Timestamp(d) for d in ticks],
                ticktext=[f"{DIAS[d.weekday()]}<br>{d.day} {MESES[d.month - 1]}" for d in ticks],
                range=[pd.Timestamp(d0) - pd.Timedelta(hours=14), pd.Timestamp(d1) + pd.Timedelta(hours=14)])


def show(fig: go.Figure, height: int, key: str) -> None:
    fig.update_layout(height=height)
    st.plotly_chart(fig, theme=None, config=PLOTLY_CONFIG, key=key)


def section(title: str, lead: str = "") -> None:
    st.html(f'<div class="sec"><div class="h">{title}</div>' + (f'<div class="p">{lead}</div>' if lead else "") + "</div>")


def fig_head(num: str, title: str, sub: str = "") -> None:
    st.html(f'<div class="fig-t"><span class="n">{num}</span>{title}</div>' + (f'<div class="fig-s">{sub}</div>' if sub else ""))


def fig_note(reading: str = "", source: str = "") -> None:
    parts = ([f"<b>Lectura.</b> {reading}"] if reading else []) + ([f'<span class="src"><b>Fuente.</b> {source}</span>'] if source else [])
    st.html('<div class="fig-note">' + "<br>".join(parts) + "</div>")


def stat(label: str, value: str, sub: str = "") -> str:
    return f'<div class="stat"><div class="l">{label}</div><div class="v">{value}</div>' + (f'<div class="s">{sub}</div>' if sub else "") + "</div>"


def table_html(df: pd.DataFrame, cols: list[tuple[str, str, str]], bar: str | None = None, sorted_col: str | None = None,
               cls: str = "t") -> str:
    """Renderiza tablas con formatos explícitos y enlaces de GitHub opcionales."""
    numeric = ("int", "pct", "dec")
    head = "".join(f'<th class="{"num" if k in numeric else ""}{" sorted" if c == sorted_col else ""}">{h}</th>'
                   for c, h, k in cols)
    vmax = float(df[bar].max()) if bar and len(df) else 0.0
    body = []
    for i, row in enumerate(df.to_dict("records"), 1):
        tds = []
        for c, _, kind in cols:
            v = row.get(c)
            missing = v is None or (isinstance(v, float) and math.isnan(v))
            if kind == "rank":
                tds.append(f'<td class="rk">{esc(row.get(c, i))}</td>')
            elif kind in numeric:
                txt = "—" if missing else (f"{v:,.0f}" if kind == "int" else f"{v:.1f} %" if kind == "pct" else f"{v:,.2f}")
                if c == bar and vmax > 0 and not missing:
                    txt = (f'<div class="cb"><div class="tr"><span style="width:{max(2.0, float(v) / vmax * 100):.1f}%"></span></div>'
                           f"<span>{txt}</span></div>")
                tds.append(f'<td class="num">{txt}</td>')
            elif kind == "html":
                tds.append(f"<td>{'' if missing else v}</td>")
            elif kind in ("name", "repo", "user"):
                if missing:
                    label = "—"
                elif kind == "name":
                    label = esc(v).replace("/", "/<wbr>")
                else:
                    label = github_link(v, kind)
                tds.append(f'<td class="nm">{label}</td>')
            else:
                tds.append(f'<td class="{"nw" if kind == "nw" else ""}">{"—" if missing else esc(v)}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def kpi_tile(kd: dict, value: str, ctx: str, value_cls: str = "") -> str:
    tip = esc(f"{kd['definition']}\nFórmula: {kd['formula']}\nInterpretación: {kd['reading']}").replace("\n", "&#10;")
    color = DB_COLOR[kd["db"]]
    return (f'<div class="tile" style="--db:{color}" title="{tip}">'
            f'<div class="tile-no">KPI {kd["no"]}</div><div class="tile-label">{kd["name"]}</div>'
            f'<div class="tile-value {value_cls}">{value}</div><div class="tile-ctx">{ctx}</div>'
            f'<div class="tile-src"><span><span class="sw" style="background:{color}"></span> {kd["db"]}</span>'
            f'<code>{kd["table"]}</code></div></div>')


def kpi_section(kd: dict, sel: date, calc: str | None, calc_note: str, applied: str, chart_title: str,
                chart: Callable[[], None]) -> None:
    color = DB_COLOR[kd["db"]]
    impl = kd["impl"].replace("{d1}", str(sel - timedelta(days=1))).replace("{dn}", str(sel + timedelta(days=1)))
    with st.container(border=True):
        st.html(f'<div class="kf-head" style="--db:{color}"><span class="kf-no">KPI {kd["no"]}</span>'
                f'<span class="kf-db"><span class="sw" style="background:{color}"></span>{kd["db"]} · <code>{kd["table"]}</code></span></div>'
                f'<div class="kf-title">{kd["long"]}</div><div class="kf-q">{kd["question"]}</div>')
        a, b = st.columns([5, 6], gap="large")
        with a:
            st.html(f'<div class="kf-lbl">Definición</div><div class="kf-txt">{kd["definition"]}</div>'
                    '<div class="kf-lbl">Fórmula de cálculo</div>')
            st.latex(kd["tex"])
            st.html(f'<div class="kf-sym">{kd["symbols"]}</div><div class="kf-lbl">Interpretación</div>'
                    f'<div class="kf-txt">{kd["reading"]}</div>')
            with st.expander(f"Implementación en {kd['db']}"):
                st.code(impl.replace("{d}", str(sel)).replace("{y}", str(sel.year)), language=kd["lang"])
        with b:
            st.html(f'<div class="kf-lbl">Cálculo para el {fdate(sel, weekday=True)}</div>')
            if calc:
                st.latex(calc)
            st.html((f'<div class="kf-sym">{calc_note}</div>' if calc_note else "")
                    + f'<div class="kf-read"><b>Lectura.</b> {applied}</div><div class="kf-lbl">{chart_title}</div>')
            chart()


def hbar(labels, values, colors, text, hover, customdata=None, height=None) -> go.Figure:
    n = max(len(labels), 1)
    height = height or 34 * n + 24
    slot = (height - 24) / n
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker=dict(color=colors, cornerradius=4, opacity=FILL_ALPHA),
                           text=text, textposition="outside", cliponaxis=False, textfont=dict(color=INK2, size=12),
                           customdata=customdata, hovertemplate=hover))
    room = 1 + max(0.3, 0.028 * max((len(str(t)) for t in text), default=0))
    fig.update_layout(**layout(bargap=min(0.75, max(0.2, 1 - 22 / slot)), height=height,
                               xaxis={"visible": False, "range": [0, float(max(values, default=0) or 1) * room]},
                               yaxis={"showgrid": False, "autorange": "reversed", "ticks": "", "ticklabelstandoff": 6}))
    return fig


@st.cache_resource(show_spinner=False)
def cass():
    return config.cassandra_session()


@st.cache_resource(show_spinner=False)
def neo():
    return config.neo4j_driver()


@st.cache_resource(show_spinner=False)
def mongo():
    return config.mongo_db()


def cypher(query: str, **params) -> list[dict]:
    return [dict(r) for r in neo().execute_query(query, database_=config.NEO4J_DATABASE, **params).records]


def native(v):
    return v.to_native() if hasattr(v, "to_native") else v


@st.cache_data(ttl=300, show_spinner=False)
def hourly_all() -> pd.DataFrame:
    df = pd.DataFrame(list(cass().execute("SELECT event_date, event_hour, event_type, event_count FROM events_by_hour")))
    if df.empty:
        return pd.DataFrame(columns=["event_date", "event_hour", "event_type", "event_count"])
    df["event_date"] = df["event_date"].map(lambda d: d.date())
    df["event_count"] = df["event_count"].fillna(0).astype("int64")
    return df


@st.cache_data(ttl=300, show_spinner=False)
def daily() -> pd.DataFrame:
    df = pd.DataFrame(list(cass().execute("SELECT event_date, total_events, unique_users, unique_repos FROM daily_totals")))
    if df.empty:
        return df
    df["event_date"] = df["event_date"].map(lambda d: d.date())
    h = hourly_all()
    hours = h.groupby("event_date")["event_hour"].agg(lambda s: tuple(sorted(set(s))))
    df["hours"] = df["event_date"].map(lambda d: hours.get(d, ()))
    df["n_hours"] = df["hours"].map(len)
    # Tipos estables y cobertura de Push (Push/Create/Delete llegan de forma intermitente).
    stable = h[~h["event_type"].isin(INTERMITTENT_TYPES)].groupby("event_date")["event_count"].sum()
    push = h[(h["event_type"] == "PushEvent") & (h["event_count"] > 0)].groupby("event_date")["event_hour"].agg(
        lambda s: tuple(sorted(set(s))))
    df["stable"] = df["event_date"].map(lambda d: int(stable.get(d, 0)))
    df["push_hours"] = df["event_date"].map(lambda d: push.get(d, ()))
    return df.fillna(0).sort_values("event_date").reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False)
def kpis_all() -> pd.DataFrame:
    df = pd.DataFrame(list(cass().execute("SELECT event_date, kpi_name, kpi_value, kpi_label, computed_at FROM kpis_by_date")))
    if df.empty:
        return pd.DataFrame(columns=["event_date", "kpi_name", "kpi_value", "kpi_label", "computed_at"])
    df["event_date"] = df["event_date"].map(lambda d: d.date())
    df["kpi_value"] = pd.to_numeric(df["kpi_value"], errors="coerce")
    return df


@st.cache_data(ttl=300, show_spinner=False)
def stable_hourly() -> pd.DataFrame:
    h = hourly_all()
    return h.assign(event_count=h["event_count"].where(~h["event_type"].isin(INTERMITTENT_TYPES), 0))


@st.cache_data(ttl=300, show_spinner=False)
def growth_all() -> dict:
    by_day = {d: g.groupby("event_hour")["event_count"].sum() for d, g in stable_hourly().groupby("event_date")}
    out = {}
    for d, cur in by_day.items():
        prev = by_day.get(d - timedelta(days=1))
        common = sorted(set(cur.index) & set(prev.index)) if prev is not None else []
        base = float(prev.loc[common].sum()) if common else 0.0
        out[d] = ((float(cur.loc[common].sum()) - base) / base * 100 if base else None, tuple(common))
    return out


@st.cache_data(ttl=300, show_spinner=False)
def runs() -> pd.DataFrame:
    df = pd.DataFrame(list(cass().execute(
        "SELECT run_date, run_hour, raw_count, clean_count, loaded_mongo, loaded_neo4j FROM pipeline_runs")))
    if not df.empty:
        df["run_date"] = df["run_date"].map(lambda d: d.date())
    return df


REPO_COLS = ["total_events", "pull_requests", "issues", "stars", "forks", "pushes"]
REPO_ES = {"total_events": "Eventos", "pull_requests": "Pull requests", "issues": "Issues", "stars": "Estrellas",
           "forks": "Forks", "pushes": "Pushes"}


@st.cache_data(ttl=600, show_spinner=False)
def repo_rank(dates: tuple[date, ...], k: int = 50) -> pd.DataFrame:
    frames = [pd.DataFrame(list(cass().execute(
        "SELECT repo_name, pushes, stars, forks, issues, pull_requests, total_events FROM repo_activity_by_day "
        "WHERE event_date=%s", (d,)))) for d in dates]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=["repo_name", *REPO_COLS])
    df = pd.concat(frames, ignore_index=True)
    df[REPO_COLS] = df[REPO_COLS].fillna(0).astype("int64")
    if len(frames) > 1:
        df = df.groupby("repo_name", as_index=False)[REPO_COLS].sum()
    # Solo el top-k de cada métrica, sin cachear particiones completas.
    keep = set().union(*(df.nlargest(k, c)["repo_name"] for c in REPO_COLS))
    return df[df["repo_name"].isin(keep)].reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False)
def user_activity(d: date) -> dict:
    df = pd.DataFrame(list(cass().execute(
        "SELECT actor_login, event_count FROM user_activity_by_day WHERE event_date=%s", (d,))))
    if df.empty:
        return {}
    df["event_count"] = df["event_count"].fillna(0).astype("int64")
    total = int(df["event_count"].sum())
    bots = df["actor_login"].str.endswith("[bot]")
    k = max(1, round(len(df) * 0.01))
    top = df.nlargest(10, "event_count").assign(share=lambda t: t["event_count"] / total * 100)
    return {"users": len(df), "total": total, "bot_users": int(bots.sum()), "bot_events": int(df.loc[bots, "event_count"].sum()),
            "top1_k": k, "top1_events": int(df["event_count"].nlargest(k).sum()), "median": float(df["event_count"].median()),
            "top": top.to_dict("records")}


@st.cache_data(ttl=300, show_spinner=False)
def degree_of(repos: tuple[str, ...]) -> dict:
    recs = cypher("MATCH (u:User)-[]->(r:Repo) WHERE r.name IN $repos RETURN r.name AS repo, count(DISTINCT u) AS deg",
                  repos=list(repos))
    return {r["repo"]: r["deg"] for r in recs}


@st.cache_data(ttl=300, show_spinner=False)
def graph_stats() -> dict:
    q = " UNION ALL ".join(f"MATCH (n:{label}) RETURN '{key}' AS k, count(n) AS n"
                           for key, label in (("users", "User"), ("repos", "Repo"), ("orgs", "Org")))
    nodes = {r["k"]: r["n"] for r in cypher(q)}
    q = " UNION ALL ".join(f"MATCH ()-[r:{t}]->() RETURN '{t}' AS t, count(r) AS n" for t in [*REL_ES, "BELONGS_TO"])
    return {**nodes, "rels": {r["t"]: r["n"] for r in cypher(q)}}


@st.cache_data(ttl=300, show_spinner=False)
def graph_top(n: int) -> pd.DataFrame:
    return pd.DataFrame(cypher(
        "MATCH (u:User)-[r]->(repo:Repo) "
        "RETURN repo.name AS repo, count(DISTINCT u) AS usuarios, sum(r.count) AS interacciones "
        "ORDER BY usuarios DESC, interacciones DESC LIMIT $n", n=n))


@st.cache_data(ttl=300, show_spinner=False)
def ego(repo: str, n: int = 36) -> dict:
    info = cypher("MATCH (u:User)-[r]->(repo:Repo {name:$repo}) "
                  "WITH repo, count(DISTINCT u) AS deg, sum(r.count) AS inter, "
                  "     count(DISTINCT CASE WHEN u.login ENDS WITH '[bot]' THEN u END) AS bots "
                  "OPTIONAL MATCH (repo)-[:BELONGS_TO]->(o:Org) RETURN deg, inter, bots, o.login AS org", repo=repo)
    users = cypher("MATCH (u:User)-[r]->(:Repo {name:$repo}) "
                   "WITH u, collect({tipo: type(r), veces: r.count, desde: r.first_seen, hasta: r.last_seen}) AS rels, "
                   "     sum(r.count) AS total "
                   "RETURN u.login AS usuario, total, rels ORDER BY total DESC, usuario LIMIT $n", repo=repo, n=n)
    for u in users:
        u["rels"] = [{**r, "desde": native(r["desde"]), "hasta": native(r["hasta"])} for r in u["rels"]]
    return {**(info[0] if info else {"deg": 0, "inter": 0, "bots": 0, "org": None}), "users": users}


@st.cache_data(ttl=300, show_spinner=False)
def mongo_overview() -> dict:
    ev = mongo().events
    first = ev.find_one({}, {"created_at": 1}, sort=[("created_at", 1)])
    last = ev.find_one({}, {"created_at": 1}, sort=[("created_at", -1)])
    return {"total": ev.estimated_document_count(), "first": first and first["created_at"], "last": last and last["created_at"]}


def _iso(doc: object) -> object:
    """Convierte fechas de documentos anidados a su representación ISO-8601."""
    if isinstance(doc, dict):
        return {k: _iso(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [_iso(v) for v in doc]
    return doc.isoformat() if isinstance(doc, datetime) else doc


@st.cache_data(ttl=300, show_spinner=False)
def mongo_day(d: date) -> dict:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    rng = {"$gte": start, "$lt": start + timedelta(days=1)}
    ev = mongo().events
    actions = {(r["_id"] or "unknown"): r["n"] for r in ev.aggregate([
        {"$match": {"type": "PullRequestEvent", "created_at": rng}},
        {"$group": {"_id": "$payload.action", "n": {"$sum": 1}}}])}
    latest = list(ev.find({"created_at": rng}, {"type": 1, "actor.login": 1, "repo.name": 1, "created_at": 1, "payload.action": 1})
                  .sort("created_at", -1).limit(10))
    sample = ev.find_one({"created_at": rng}, sort=[("created_at", -1)])
    return {"count": ev.count_documents({"created_at": rng}), "actions": actions, "sample": _iso(sample),
            "latest": [{"hora": r["created_at"].strftime("%H:%M:%S"), "tipo": EVENT_ES.get(r["type"], r["type"]),
                        "tecnico": r["type"], "usuario": r["actor"]["login"], "repo": r["repo"]["name"],
                        "accion": (r.get("payload") or {}).get("action") or "—"} for r in latest]}


def fig_heatmap(hourly: pd.DataFrame, start: date, end: date) -> go.Figure:
    """Muestra el volumen horario sin convertir horas ausentes en ceros."""
    calendar = pd.date_range(start, end, freq="D").date
    window = hourly[hourly["event_date"].between(start, end)]
    counts = window.groupby(["event_date", "event_hour"])["event_count"].sum(min_count=1)
    matrix = counts.unstack("event_hour").reindex(index=calendar, columns=range(24))
    dates = [d.isoformat() for d in calendar]
    missing = [[1 if pd.isna(value) else None for value in row] for row in matrix.to_numpy()]
    values = [[None if pd.isna(value) else int(value) for value in row] for row in matrix.to_numpy()]
    maximum = max((value for row in values for value in row if value is not None), default=0)
    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        x=list(range(24)), y=dates, z=missing, zmin=0, zmax=1,
        colorscale=[[0, NEUTRAL], [1, NEUTRAL]], showscale=False, xgap=2, ygap=2,
        hoverongaps=False, hovertemplate="%{y} · %{x:02d}:00 UTC<br>Sin datos<extra></extra>",
    ))
    fig.add_trace(go.Heatmap(
        x=list(range(24)), y=dates, z=values, zmin=0, zmax=max(1, maximum),
        colorscale=[[0, CARD], [0.5, ACCENT_SOFT], [1, ACCENT]], xgap=2, ygap=2,
        colorbar=dict(title=dict(text="Eventos"), thickness=12, tickformat="~s"),
        hoverongaps=False, hovertemplate="%{y} · %{x:02d}:00 UTC<br>%{z:,} eventos<extra></extra>",
    ))
    step = max(1, math.ceil(len(dates) / 20))
    fig.update_layout(**layout(
        xaxis={"title": {"text": "Hora (UTC)"}, "tickmode": "array", "tickvals": list(range(24)),
               "ticktext": [f"{h:02d}" for h in range(24)], "showgrid": False},
        yaxis={"type": "category", "autorange": "reversed", "tickmode": "array",
               "tickvals": dates[::step], "ticktext": [fdate(d, year=False) for d in calendar[::step]],
               "showgrid": False},
    ))
    return fig


def fig_hourly(day: pd.DataFrame, hours: tuple[int, ...]) -> tuple[go.Figure, dict]:
    totals = day.groupby("event_type")["event_count"].sum().sort_values(ascending=False)
    main = sorted([t for t in totals.index if t in TYPE_COLOR][:MAIN_TYPES], key=TYPE_ORDER.index)
    serie = day["event_type"].where(day["event_type"].isin(main), "Otros")
    pv = day.assign(serie=serie).pivot_table(index="event_hour", columns="serie", values="event_count", aggfunc="sum").reindex(range(24))
    cats = [f"{h:02d}:00" for h in range(24)]
    fig = go.Figure()
    for t in main + (["Otros"] if "Otros" in pv.columns else []):
        name = EVENT_ES.get(t, t) if t != "Otros" else "Otros tipos"
        fig.add_bar(x=cats, y=[None if pd.isna(v) else v for v in pv[t]], name=name,
                    marker=dict(color=TYPE_COLOR.get(t, OTHER), opacity=FILL_ALPHA, line=dict(color=BG, width=1)),
                    hovertemplate=f"{name}: %{{y:,.0f}}<extra></extra>")
    tot = pv.sum(axis=1, min_count=1)
    fig.add_scatter(x=cats, y=[None if pd.isna(v) else v for v in tot], mode="markers", marker=dict(opacity=0, size=1),
                    name="Total", hovertemplate="<b>Total: %{y:,.0f}</b><extra></extra>", showlegend=False)
    info = {"main": main, "totals": totals}
    present = tot.dropna()
    if not present.empty:
        peak, low = int(present.idxmax()), int(present.idxmin())
        info.update(peak=peak, peak_v=int(present[peak]), low=low, low_v=int(present[low]))
        fig.add_annotation(x=cats[peak], y=present[peak], text=f"Pico {int(present[peak]):,}", showarrow=False, yshift=12,
                           font=dict(size=11, color=INK))
        if len(present) >= 6:
            atyp = present[present < 0.25 * present.median()]
            info["atypical"] = list(atyp.index)
            if len(atyp):
                fig.add_scatter(x=[cats[h] for h in atyp.index], y=[float(present.max()) * 0.06 + v for v in atyp], mode="markers",
                                marker=dict(symbol="triangle-down", size=9, color=INK2), name="Volumen atípico (< 25 % de la mediana)",
                                hovertemplate="Volumen atípico: %{customdata:,.0f} eventos<extra></extra>", customdata=list(atyp))
    for a, b in runs_of(set(range(24)) - set(hours)):
        fig.add_vrect(x0=a - 0.5, x1=b + 0.5, fillcolor=BAND, line_width=0, layer="below")
        if b - a >= 1:
            fig.add_annotation(x=(a + b) / 2, y=0.5, yref="paper", text="Sin datos<br>cargados", showarrow=False,
                               font=dict(size=11, color=MUTED))
    fig.update_layout(**layout(barmode="stack", bargap=0.3, barcornerradius=3, showlegend=True, hovermode="x unified",
                               legend={"traceorder": "normal"},
                               xaxis={"type": "category", "categoryorder": "array", "categoryarray": cats,
                                      "tickvals": cats[::3], "ticktext": [f"{h:02d} h" for h in range(0, 24, 3)],
                                      "title": {"text": "Hora del día (UTC)"}},
                               yaxis={"tickformat": "~s", "title": {"text": "Eventos por hora"}}))
    return fig, info


def fig_composition(totals: pd.Series, main: list[str]) -> go.Figure:
    total = float(totals.sum())
    rows = [(t, int(totals[t])) for t in totals.index if t in main]
    others = totals[[t for t in totals.index if t not in main]]
    if len(others):
        rows.append(("Otros", int(others.sum())))
    labels = [EVENT_ES.get(t, t) if t != "Otros" else "Otros tipos" for t, _ in rows]
    vals = [v for _, v in rows]
    detail = [t if t != "Otros" else " · ".join(f"{EVENT_ES.get(o, o)} {n:,}" for o, n in others.head(4).items()) for t, _ in rows]
    return hbar(labels, vals, [TYPE_COLOR.get(t, OTHER) for t, _ in rows],
                [f"{v / total * 100:.1f} %  ·  {fnum(v)}" for v in vals],
                "<b>%{y}</b><br>%{x:,} eventos<br><span style='color:" + MUTED + "'>%{customdata}</span><extra></extra>",
                customdata=detail, height=420)


def fig_daily(dd: pd.DataFrame, sel: date) -> go.Figure:
    d0, d1 = dd["event_date"].min(), dd["event_date"].max()
    fig = go.Figure()
    for a, b in runs_of([i for i in range((d1 - d0).days + 1) if (d0 + timedelta(days=i)).weekday() >= 5]):
        fig.add_vrect(x0=pd.Timestamp(d0 + timedelta(days=a)) - pd.Timedelta(hours=12),
                      x1=pd.Timestamp(d0 + timedelta(days=b)) + pd.Timedelta(hours=12), fillcolor=BAND, line_width=0, layer="below")
    full = dd["n_hours"] >= 24
    hover = ("<b>%{customdata[0]}</b><br>%{y:,} eventos<br>%{customdata[1]} de 24 h cargadas · %{customdata[2]:,.0f} eventos/h"
             "<br>%{customdata[3]:,} usuarios activos · %{customdata[4]:,} repositorios<extra></extra>")
    for mask, name, color in ((full, "Día completo (24 h)", ACCENT), (~full, "Día parcial (< 24 h; se indica cuántas)", ACCENT_SOFT)):
        part = dd[mask]
        if part.empty:
            continue
        fig.add_bar(x=pd.to_datetime(part["event_date"]), y=part["total_events"], name=name, marker=dict(color=color, cornerradius=3),
                    customdata=[[fdate(d, weekday=True), n, t / n if n else 0, u, r] for d, n, t, u, r in
                                zip(part["event_date"], part["n_hours"], part["total_events"], part["unique_users"], part["unique_repos"])],
                    hovertemplate=hover, text=[f"{n} h" if n < 24 else "" for n in part["n_hours"]], textposition="outside",
                    textfont=dict(size=11, color=MUTED), cliponaxis=False)
    fig.add_scatter(x=pd.to_datetime(dd["event_date"]), y=dd["stable"], mode="lines+markers", name="Tipos estables (sin Push ni ramas)",
                    line=dict(color=INK, width=2), marker=dict(size=6, color=INK, line=dict(color=BG, width=1.5)),
                    customdata=[fdate(d, weekday=True) for d in dd["event_date"]],
                    hovertemplate="<b>%{customdata}</b><br>%{y:,} eventos de tipos estables<extra></extra>")
    srow = dd[dd["event_date"] == sel]
    if not srow.empty:
        pos = (sel - d0).days / max(1, (d1 - d0).days)
        fig.add_annotation(x=pd.Timestamp(sel), y=float(srow["total_events"].iloc[0]), text="Seleccionado", showarrow=True,
                           arrowhead=0, arrowwidth=1, arrowcolor=INK2, ax=0, ay=-40, standoff=18 if srow["n_hours"].iloc[0] < 24 else 2,
                           xanchor="right" if pos > 0.9 else "left" if pos < 0.1 else "center", font=dict(size=11, color=INK),
                           bgcolor=BG if DARK_MODE else "rgba(248,241,228,0.9)")
    fig.update_layout(**layout(barmode="overlay", bargap=0.25, showlegend=True, hovermode="closest",
                               xaxis=date_axis(d0, d1, 16), yaxis={"tickformat": "~s", "title": {"text": "Eventos por día"}}))
    return fig


def fig_trend(dd: pd.DataFrame, values: dict, sel: date, ytitle: str, hover_fmt: str, suffix: str = "") -> go.Figure:
    d0, d1 = dd["event_date"].min(), dd["event_date"].max()
    days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    partial = dict(zip(dd["event_date"], dd["n_hours"] < 24))
    fig = go.Figure()
    fig.add_scatter(x=[pd.Timestamp(d) for d in days], y=[values.get(d) for d in days], mode="lines", connectgaps=False,
                    line=dict(color=ACCENT, width=2), hoverinfo="skip")
    for is_partial, fill in ((False, ACCENT), (True, BG)):
        pts = [d for d in days if values.get(d) is not None and partial.get(d, False) == is_partial]
        if pts:
            fig.add_scatter(x=[pd.Timestamp(d) for d in pts], y=[values[d] for d in pts], mode="markers",
                            marker=dict(size=8, color=fill, line=dict(color=ACCENT if is_partial else BG, width=2)),
                            customdata=[fdate(d, weekday=True) + (" (parcial)" if is_partial else "") for d in pts],
                            hovertemplate=f"<b>%{{customdata}}</b><br>%{{y:{hover_fmt}}}{suffix}<extra></extra>")
    fig.add_vline(x=pd.Timestamp(sel), line_width=1, line_color=NEUTRAL)
    fig.update_layout(**layout(xaxis=date_axis(d0, d1, 6), yaxis={"title": {"text": ytitle}, "ticksuffix": suffix}))
    return fig


def fig_growth(dd: pd.DataFrame, growth: dict, sel: date) -> go.Figure:
    d0, d1 = dd["event_date"].min(), dd["event_date"].max()
    pts = [(d, *growth[d]) for d in dd["event_date"] if growth.get(d, (None,))[0] is not None]
    fig = go.Figure(go.Bar(x=[pd.Timestamp(d) for d, _, _ in pts], y=[g for _, g, _ in pts],
                           marker=dict(color=[POS if g >= 0 else NEG for _, g, _ in pts], cornerradius=3),
                           customdata=[[fdate(d, weekday=True), len(h)] for d, _, h in pts],
                           hovertemplate="<b>%{customdata[0]}</b><br>%{y:+.1f} % vs. día anterior<br>%{customdata[1]} h comparadas<extra></extra>"))
    fig.add_vline(x=pd.Timestamp(sel), line_width=1, line_color=NEUTRAL)
    fig.update_layout(**layout(bargap=0.3, xaxis=date_axis(d0, d1, 6),
                               yaxis={"title": {"text": "Variación (%)"}, "ticksuffix": " %", "zeroline": True,
                                      "zerolinecolor": NEUTRAL, "zerolinewidth": 1}))
    return fig


def fig_ego(repo: str, eg: dict) -> go.Figure:
    users = eg["users"]
    order = list(REL_ES)
    for u in users:
        u["main"] = max(u["rels"], key=lambda r: r["veces"] or 0)["tipo"]
    users.sort(key=lambda u: (order.index(u["main"]) if u["main"] in order else len(order), -(u["total"] or 0)))
    n, top = len(users), max((u["total"] or 1) for u in users)
    for i, u in enumerate(users):
        ang = math.pi / 2 - 2 * math.pi * i / n
        r = 1.0 if n <= 24 or i % 2 == 0 else 0.84
        u["x"], u["y"] = r * math.cos(ang), r * math.sin(ang)
    fig = go.Figure()
    ex, ey = [], []
    for u in users:
        ex += [0, u["x"], None]
        ey += [0, u["y"], None]
    fig.add_scatter(x=ex, y=ey, mode="lines", line=dict(color="#dccdb3", width=1), hoverinfo="skip", showlegend=False)
    for t in order:
        grp = [u for u in users if u["main"] == t]
        if not grp:
            continue
        # leyenda aparte: plotly usaria el simbolo del primer punto
        fig.add_scatter(x=[None], y=[None], mode="markers", name=REL_ES[t], marker=dict(size=10, color=REL_COLOR[t], opacity=FILL_ALPHA))
        fig.add_scatter(
            x=[u["x"] for u in grp], y=[u["y"] for u in grp], mode="markers", name=REL_ES[t], showlegend=False,
            marker=dict(size=[9 + 13 * math.sqrt((u["total"] or 0) / top) for u in grp], color=REL_COLOR[t], opacity=FILL_ALPHA,
                        symbol=["diamond" if u["usuario"].endswith("[bot]") else "circle" for u in grp],
                        line=dict(color=BG, width=1.5)),
            customdata=[[u["usuario"], " · ".join(f"{REL_ES.get(r['tipo'], r['tipo'])} ×{r['veces']:,}" for r in u["rels"])]
                        for u in grp],
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>")
    lab = sorted(users, key=lambda u: -(u["total"] or 0))[:10]
    fig.add_scatter(x=[u["x"] * 1.1 for u in lab], y=[u["y"] * 1.1 for u in lab], mode="text", text=[u["usuario"] for u in lab],
                    textposition=["middle right" if u["x"] >= 0 else "middle left" for u in lab],
                    textfont=dict(size=11, color=INK2), hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=[None], y=[None], mode="markers", name="Cuenta automatizada ([bot])",
                    marker=dict(symbol="diamond", size=10, color=NEUTRAL))
    fig.add_scatter(x=[0], y=[0], mode="markers+text", text=[f"<b>{repo}</b>"], textposition="bottom center", textfont=dict(size=12, color=INK),
                    marker=dict(size=28, color=DB_COLOR["Neo4j"], line=dict(color=BG, width=2)), showlegend=False,
                    hovertemplate=f"<b>{repo}</b><br>{eg['deg']:,} usuarios distintos<extra></extra>")
    fig.update_layout(**layout(showlegend=True, hovermode="closest", margin=dict(l=4, r=4, t=8, b=4),
                               xaxis={"visible": False, "range": [-1.75, 1.75]},
                               yaxis={"visible": False, "range": [-1.3, 1.3], "scaleanchor": "x", "scaleratio": 1}))
    return fig


st.set_page_config(page_title="GitHub Events · Dashboard analítico", page_icon=":material/monitoring:", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

try:
    dd = daily()
except Exception as exc:
    st.error(f"No se pudo conectar a Cassandra: {exc}")
    st.stop()
if dd.empty:
    st.info("Aún no hay datos. Ejecuta el DAG `github_events_pipeline` en Airflow o `python src/run_pipeline_local.py`.")
    st.stop()

hourly, kp, growth = hourly_all(), kpis_all(), growth_all()
cov = dict(zip(dd["event_date"], dd["hours"]))
dates = list(dd["event_date"])[::-1]
first_d, last_d = dd["event_date"].iloc[0], dd["event_date"].iloc[-1]
today_utc = datetime.now(timezone.utc).date()
n_full = int((dd["n_hours"] >= 24).sum())

st.html(
    '<div class="hdr"><div class="overline">UTEC · Big Data · Proyecto Grupal II</div>'
    '<div class="title" role="heading" aria-level="1">Actividad pública en GitHub: dashboard analítico</div>'
    '<p class="lede">Eventos de GH Archive procesados cada hora por un DAG de Apache Airflow y almacenados en una arquitectura '
    "multimodelo: MongoDB conserva el documento original, Cassandra los agregados temporales y Neo4j el grafo de colaboración.</p>"
    f'<div class="meta"><span><b>Periodo cargado</b>{fdate(first_d)} – {fdate(last_d)}</span>'
    f"<span><b>Días</b>{len(dd)} ({n_full} completos, {len(dd) - n_full} parciales)</span>"
    f"<span><b>Último dato</b>{fdate(last_d)}, {max(cov[last_d]):02d}:59 UTC</span>"
    "<span><b>Actualización</b>cada hora (Airflow)</span><span><b>Zona horaria</b>UTC (Lima = UTC−5)</span></div></div>")

f1, f2, appearance = st.columns([2.3, 2, 5])
if st.session_state.get("fecha") not in cov:
    try:
        st.session_state["fecha"] = date.fromisoformat(st.query_params.get("fecha", ""))
    except ValueError:
        pass
    if st.session_state.get("fecha") not in cov:
        st.session_state["fecha"] = dates[0]
sel = f1.selectbox("Fecha de análisis (UTC)", dates, key="fecha",
                   format_func=lambda d: fdate(d, weekday=True) + ("" if len(cov[d]) == 24 else f" — parcial ({len(cov[d])} h)"))
st.query_params["fecha"] = str(sel)
top_n = f2.slider("Elementos en rankings", 5, 20, 10)
appearance.toggle("Modo oscuro", key="modo_oscuro")
hrs = cov[sel]
if len(hrs) < 24:
    kind = "Día en curso" if sel == today_utc else "Día parcial"
    why = ("Airflow agrega una hora nueva cada 60 minutos." if sel == today_utc
           else "La carga histórica de este día está incompleta.")
    st.html(f'<div class="callout"><span class="badge warn">{kind}</span><span>Hay <b>{len(hrs)} de 24 horas</b> con datos '
            f"({hours_label(hrs)} UTC).</span>{hour_strip(hrs)}<span>{why} Los totales del día no son comparables con días "
            "completos; el crecimiento diario compara solo las horas presentes en ambos días.</span></div>")

krow = kp[kp["event_date"] == sel].set_index("kpi_name")


def kval(name: str) -> float | None:
    v = krow["kpi_value"].get(name) if name in krow.index else None
    return None if v is None or pd.isna(v) else float(v)


def klabel(name: str) -> str:
    return str(krow["kpi_label"].get(name, "")) if name in krow.index else ""


section(f"Indicadores clave · {fdate(sel, weekday=True)}",
        "Calculados automáticamente por la etapa 6 del DAG y guardados en Cassandra (<code>kpis_by_date</code>). "
        "El color superior de cada tarjeta indica la base de datos de origen. La pestaña «Indicadores (KPI)» detalla la "
        "definición, la fórmula de cálculo y la interpretación de cada uno.")
K = {kd["key"]: kd for kd in KPI_DEF}
day_row = dd.set_index("event_date").loc[sel]
tiles = []

ev = kval("events_per_day")
badge = '<span class="badge ok">Día completo</span>' if len(hrs) == 24 else f'<span class="badge warn">Parcial · {len(hrs)}/24 h</span>'
tiles.append(kpi_tile(K["events_per_day"], "—" if ev is None else f"{ev:,.0f}",
                      badge + (f"<br>≈ {ev / len(hrs):,.0f} eventos por hora cargada." if ev and hrs else "")
                      + f"<br>Tipos estables: {int(day_row['stable']):,} · Push en {len(day_row['push_hours'])} de {len(hrs)} h."))

g_live, common = growth.get(sel, (None, ()))
g_stored, prev = kval("daily_growth_pct"), sel - timedelta(days=1)
if g_live is None:
    tiles.append(kpi_tile(K["daily_growth_pct"], '<span class="na">N/D</span>',
                          f"Sin datos del {fdate(prev, weekday=True)} para comparar."))
else:
    arrow, cls = ("▲", "up") if g_live >= 0 else ("▼", "down")
    ctx = f'Tipos estables vs. {fdate(prev, weekday=True, year=False)}, mismas {len(common)} h <span class="nw">({hours_label(common)})</span>.'
    if g_stored is None or abs(g_stored - g_live) > 0.05:
        ctx += (' <span class="badge" title="El valor guardado en kpis_by_date se calculó antes de completarse la carga del '
                'día anterior; se muestra el recalculado con los datos actuales (scripts/recompute_kpis.py lo actualiza).">recalculado</span>')
    signed = f"{g_live:+.1f}".replace("-", "−")
    tiles.append(kpi_tile(K["daily_growth_pct"], f'<span class="{cls}"><span class="arr">{arrow}</span>{signed}<span class="u">%</span></span>', ctx))

v3 = kval("avg_events_per_user")
users_n = int(day_row["unique_users"])
tiles.append(kpi_tile(K["avg_events_per_user"], "—" if v3 is None else f"{v3:.2f}",
                      f"{(ev or 0):,.0f} eventos ÷ {users_n:,} usuarios activos (actores distintos)."))

v4 = kval("pr_merge_rate_pct")
m = re.search(r"(\d+) merged / (\d+) cerrados", klabel("pr_merge_rate_pct"))
ctx4 = (f"{int(m.group(1)):,} fusionados de {int(m.group(1)) + int(m.group(2)):,} PR cerrados en el día "
        f"({int(m.group(2)):,} sin fusionar)." if m else "Fusionados / (fusionados + cerrados sin fusionar).")
tiles.append(kpi_tile(K["pr_merge_rate_pct"], "—" if v4 is None else f"{v4:.1f}<span class='u'>%</span>", ctx4))

r5, d5 = klabel("top_repo_connections"), kval("top_repo_connections")
if r5 and d5 is not None:
    c5 = krow["computed_at"].get("top_repo_connections")
    ctx5 = f"{d5:,.0f} usuarios distintos conectados en el grafo acumulado hasta el {fdate(sel, year=False)}."
    try:
        live = degree_of((r5,)).get(r5)
        if live and live != int(d5):
            ctx5 += f" Hoy en el grafo: {live:,}."
    except Exception:
        pass
    tiles.append(kpi_tile(K["top_repo_connections"], esc(r5).replace("/", "/<wbr>"), ctx5, "name long" if len(r5) > 22 else "name"))
else:
    tiles.append(kpi_tile(K["top_repo_connections"], '<span class="na">—</span>', "KPI aún no calculado para esta fecha."))
st.html('<div class="tiles">' + "".join(tiles) + "</div>")
foot = "".join(f'<span><span class="sw" style="background:{c}"></span>{db}</span>' for db, c in DB_COLOR.items())
if not krow.empty:
    foot += f"<span>Último cálculo de los KPI de esta fecha: {fdt(krow['computed_at'].max())}</span>"
st.html(f'<div class="tiles-foot">{foot}</div>')

kpi_export = pd.DataFrame([
    {
        "indicador": kd["key"], "nombre": kd["name"], "fuente": kd["db"],
        "valor": g_live if kd["key"] == "daily_growth_pct" else kval(kd["key"]),
        "detalle": (f"Tipos estables en {len(common)} horas comunes con {prev}."
                    if kd["key"] == "daily_growth_pct" else klabel(kd["key"])),
        "origen_valor": "Recalculado en el dashboard" if kd["key"] == "daily_growth_pct" else "KPI guardado",
    }
    for kd in KPI_DEF
])
download_csv(kpi_export, f"indicadores_{sel}_utc.csv", "csv_kpis",
             fecha_analisis_utc=sel, horas_cargadas=len(hrs))

tab_k, tab_c, tab_g, tab_m, tab_doc = st.tabs(["Indicadores (KPI)", "Actividad temporal · Cassandra", "Red de colaboración · Neo4j",
                                               "Documentos fuente · MongoDB", "Metodología y calidad de datos"])
kpiv = {name: dict(zip(g["event_date"], g["kpi_value"].where(g["kpi_value"].notna(), None))) for name, g in kp.groupby("kpi_name")}
full_days = dd[dd["n_hours"] >= 24]
n_h = len(hrs)

with tab_k:
    st.html('<p class="tab-lead">Cinco indicadores, al menos uno por base de datos, calculados cada hora por la etapa 6 del DAG '
            "(<code>generate_kpis</code>) y guardados en Cassandra (<code>kpis_by_date</code>). Cada ficha presenta la definición, "
            "la fórmula de cálculo y la interpretación del indicador, y aplica la fórmula a la fecha de análisis.</p>")

    if ev is None:
        calc, applied = None, "El indicador aún no se calculó para esta fecha."
    else:
        calc = (rf"\begin{{gathered}} E_D = {tnum(ev)}\ \text{{eventos}} \\[2pt] {n_h}\ \text{{h cargadas}} \;\Rightarrow\; "
                rf"\approx {tnum(ev / n_h)}\ \text{{eventos por hora}} \end{{gathered}}")
        if n_h == 24 and len(full_days) > 1:
            mean = full_days["total_events"].mean()
            dev = (ev / mean - 1) * 100
            applied = (f"Se procesaron {ev:,.0f} eventos, {f'{dev:+.0f}'.replace('-', '−')} % respecto de la media "
                       f"de los {len(full_days)} días completos ({mean:,.0f}).")
            if abs(dev) >= 50:
                applied += " Una diferencia de esta magnitud refleja sobre todo cambios de volumen del feed de GH Archive entre periodos."
        elif n_h < 24 and len(full_days):
            applied = (f"Día parcial: {ev / n_h:,.0f} eventos por hora cargada frente a {(full_days['total_events'] / 24).mean():,.0f} "
                       f"por hora en los días completos. El total crecerá cuando se carguen las {24 - n_h} horas faltantes.")
        else:
            applied = f"Se procesaron {ev:,.0f} eventos en {n_h} horas."
        st_n, push_n = int(day_row["stable"]), len(day_row["push_hours"])
        applied += (f" De ellos, {st_n:,} ({st_n / ev * 100:.0f} %) son de tipos estables; el resto son Push y creación o borrado "
                    f"de ramas, que el feed trajo en {push_n} de {n_h} horas." if ev else "")
    kpi_section(K["events_per_day"], sel, calc, "", applied, "Evolución en el periodo",
                lambda: show(fig_trend(dd, dict(zip(dd["event_date"], dd["total_events"])), sel, "Eventos por día", ",.0f"), 230, "k1"))

    if g_live is None:
        calc, note, applied = None, "", f"No se calcula: no hay datos del {fdate(prev, weekday=True)}."
    else:
        hsum = stable_hourly()
        hsum = hsum[hsum["event_date"].isin([sel, prev])].groupby(["event_date", "event_hour"])["event_count"].sum()
        a = int(sum(hsum.get((sel, h), 0) for h in common))
        b = int(sum(hsum.get((prev, h), 0) for h in common))
        calc = rf"G_D = \frac{{{tnum(a)} - {tnum(b)}}}{{{tnum(b)}}} \times 100 = {g_live:+.1f}\,\%"
        note = f"<i>H</i>: {len(common)} horas presentes en ambos días ({hours_label(common)}). Solo tipos estables."
        applied = (f"La actividad de tipos estables {'creció' if g_live >= 0 else 'cayó'} un {abs(g_live):.1f} % frente al "
                   f"{fdate(prev, weekday=True)} en las mismas {len(common)} horas.")
        if abs(g_live) >= 50:
            applied += " Una variación de esta magnitud suele reflejar una captura incompleta del feed (ver horas atípicas en el Gráfico 1)."
        if g_stored is None or abs(g_stored - g_live) > 0.05:
            applied += " El valor guardado en <code>kpis_by_date</code> está desactualizado; se muestra el recalculado."
    kpi_section(K["daily_growth_pct"], sel, calc, note, applied, "Evolución en el periodo",
                lambda: show(fig_growth(dd, growth, sel), 230, "k2"))

    ua = user_activity(sel)
    if v3 is None:
        calc, applied = None, "El indicador aún no se calculó para esta fecha."
    else:
        calc = rf"A_D = \frac{{{tnum(ev or 0)}}}{{{tnum(users_n)}}} = {v3:.2f}\ \text{{eventos por usuario}}"
        applied = f"Cada usuario activo generó en promedio {v3:.2f} eventos."
        if ua:
            applied += (f" La mediana es {ua['median']:.0f}: el 1 % de cuentas más activas concentra el "
                        f"{ua['top1_events'] / ua['total'] * 100:.1f} % de los eventos y las cuentas automatizadas ([bot]), el "
                        f"{ua['bot_events'] / ua['total'] * 100:.1f} %.")
        if n_h < 24:
            applied += " En un día parcial el promedio es menor porque cada usuario tuvo menos horas para generar eventos."
    v3s = {d: v for d, v in kpiv.get("avg_events_per_user", {}).items() if v is not None}
    kpi_section(K["avg_events_per_user"], sel, calc, "", applied, "Evolución en el periodo",
                lambda: show(fig_trend(dd, v3s, sel, "Eventos / usuario", ".2f"), 230, "k3"))

    v4s = {d: v for d, v in kpiv.get("pr_merge_rate_pct", {}).items() if v is not None}
    if v4 is None:
        calc, applied = None, "El indicador aún no se calculó para esta fecha."
    else:
        calc = None
        applied = f"De cada 100 pull requests cerrados, {v4:.0f} se fusionaron."
        if m:
            F, N = int(m.group(1)), int(m.group(2))
            calc = rf"T_D = \frac{{{tnum(F)}}}{{{tnum(F)} + {tnum(N)}}} \times 100 = {v4:.1f}\,\%"
        if len(v4s) > 1:
            lo, hi = min(v4s.values()), max(v4s.values())
            applied += (f" En el periodo la tasa va de {lo:.1f} % a {hi:.1f} % (media {sum(v4s.values()) / len(v4s):.1f} %): "
                        f"{'un comportamiento estable' if hi - lo < 5 else 'una variación apreciable'} entre días.")
    kpi_section(K["pr_merge_rate_pct"], sel, calc, "", applied, "Evolución en el periodo",
                lambda: show(fig_trend(dd, v4s, sel, "Fusionados (%)", ".1f", " %"), 230, "k4"))

    if not (r5 and d5 is not None):
        calc, note, applied = None, "", "El indicador aún no se calculó para esta fecha."
    else:
        calc = rf"r^{{*}}_D = \texttt{{{tex_escape(r5)}}}, \qquad \deg_D(r^{{*}}_D) = {tnum(d5)}"
        note = f"Grafo acumulado hasta el final del {fdate(sel)} (calculado el {fdt(c5)})."
        applied = f"<b>{esc(r5)}</b> reunía {d5:,.0f} usuarios distintos al cierre del {fdate(sel, weekday=True, year=False)}."
        try:
            eg5 = ego(r5)
            applied += (f" Hoy el grafo le asigna {eg5['deg']:,} usuarios, de los cuales {eg5['bots']:,} son cuentas automatizadas. "
                        "Su vecindario se explora en la pestaña «Red de colaboración» (Gráfico 6).")
        except Exception:
            pass

    def chart5():
        try:
            g5 = graph_top(5)
        except Exception as exc:
            st.info(f"No se pudo consultar Neo4j: {exc}")
            return
        show(hbar(g5["repo"].tolist(), g5["usuarios"].tolist(), [DB_COLOR["Neo4j"] if r == r5 else OTHER for r in g5["repo"]],
                  [f"{v:,}" for v in g5["usuarios"]], "<b>%{y}</b><br>%{x:,} usuarios distintos<extra></extra>"),
             34 * len(g5) + 24, "k5")
    kpi_section(K["top_repo_connections"], sel, calc, note, applied, "Ranking actual del grafo (consulta en vivo)", chart5)

with tab_c:
    st.html('<p class="tab-lead">Agregados que Cassandra sirve leyendo <b>una sola partición por consulta</b> (diseño orientado a '
            "consultas, sin JOIN): <code>events_by_hour</code> y <code>repo_activity_by_day</code> particionadas por día, "
            "<code>daily_totals</code> por año y <code>user_activity_by_day</code> por día.</p>")
    day = hourly[hourly["event_date"] == sel]
    left, right = st.columns([3, 2], gap="large")
    with left:
        fig_head("Gráfico 1", "Eventos por hora y tipo de evento", f"{fdate(sel, weekday=True)} · horas en UTC · los {MAIN_TYPES} tipos principales del día")
        fig, info = fig_hourly(day, hrs)
        show(fig, 420, "g1")
        reading = (f"Hora pico: {info['peak']:02d} h ({info['peak_v']:,} eventos); hora valle: {info['low']:02d} h "
                   f"({info['low_v']:,}). {len(hrs)} de 24 horas con datos." if "peak" in info else "Sin datos para el día.")
        if info.get("atypical"):
            reading += (f" Las horas marcadas con ▼ ({', '.join(f'{h:02d} h' for h in info['atypical'])}) tienen menos del 25 % "
                        "del volumen mediano del día: suele indicar una captura incompleta del feed de GH Archive, no una caída real.")
        ph = day_row["push_hours"]
        if 0 < len(ph) < len(hrs):
            reading += (f" El feed trae Push solo en {len(ph)} de {len(hrs)} horas ({hours_label(ph)}): el salto de volumen entre "
                        "horas es de cobertura, no de actividad.")
        fig_note(reading, "Cassandra · <code>events_by_hour</code> (partición <code>event_date</code>).")
    with right:
        fig_head("Gráfico 2", "Composición del día por tipo de evento", "porcentaje del total y número de eventos")
        totals = info["totals"]
        show(fig_composition(totals, info["main"]), 420, "g2")
        if len(totals):
            tshare = totals.iloc[0] / totals.sum() * 100
            reading = (f"{EVENT_ES.get(totals.index[0], totals.index[0])} concentra el {tshare:.1f} % de los "
                       f"{int(totals.sum()):,} eventos; hay {len(totals)} tipos distintos en el día.")
            if "PushEvent" not in totals.index:
                reading += " El feed de este día no trae eventos Push (intermitentes en GH Archive 2026)."
            fig_note(reading, "Cassandra · <code>events_by_hour</code>. Colores fijos por tipo, iguales en ambos gráficos.")

    download_csv(day.sort_values(["event_hour", "event_type"]), f"eventos_horarios_{sel}_utc.csv",
                 "csv_horarios", zona_horaria="UTC")

    section("Evolución diaria", "Todas las fechas cargadas. Las barras claras son días parciales y llevan encima las horas "
            "cargadas; los fines de semana van sombreados. La línea es la serie comparable entre días (tipos estables).")
    fig_head("Gráfico 3", "Eventos procesados por día", f"{fdate(first_d)} – {fdate(last_d)}")
    show(fig_daily(dd, sel), 360, "g3")
    if len(full_days):
        lo, hi = full_days.loc[full_days["total_events"].idxmin()], full_days.loc[full_days["total_events"].idxmax()]
        reading = (f"Días completos: promedio de {full_days['total_events'].mean():,.0f} eventos por día; mínimo el "
                   f"{fdate(lo['event_date'])} ({lo['total_events']:,}) y máximo el {fdate(hi['event_date'])} ({hi['total_events']:,}). "
                   f"La línea muestra solo los tipos estables: {full_days['stable'].mean():,.0f} por día en promedio, entre "
                   f"{full_days['stable'].min():,} y {full_days['stable'].max():,}. La diferencia con las barras son Push y creación o "
                   "borrado de ramas, que GH Archive entrega de forma intermitente en 2026: el volumen total depende de esa cobertura.")
    else:
        reading = "Aún no hay días completos: todas las barras corresponden a días parciales."
    fig_note(reading, "Cassandra · <code>daily_totals</code> (totales) y <code>events_by_hour</code> (horas cargadas).")

    with st.expander("Mapa de calor por día y hora"):
        heat_periods = {"Últimos 7 días": 7, "Últimos 14 días": 14, "Últimos 30 días": 30,
                        "Todo el periodo hasta la fecha seleccionada": None}
        heat_period = st.selectbox("Periodo del mapa", list(heat_periods), index=1, key="periodo_mapa")
        heat_days = heat_periods[heat_period]
        heat_start = max(first_d, sel - timedelta(days=heat_days - 1)) if heat_days else first_d
        st.caption(f"{fdate(heat_start)} – {fdate(sel)} · todos los tipos de evento · horas en UTC.")
        show(fig_heatmap(hourly, heat_start, sel), min(720, max(280, 24 * ((sel - heat_start).days + 1) + 100)), "mapa_horario")
        st.html(f'<div class="tnote"><span class="sw" style="background:{NEUTRAL}"></span> Sin datos · '
                f'<span class="sw" style="background:{CARD};border:1px solid {AXIS}"></span> Cero eventos · '
                f'<span class="sw" style="background:{ACCENT}"></span> Mayor actividad. '
                'Las horas ausentes se mantienen sin datos. La intensidad también depende de la cobertura '
                'de Push, creación y borrado de ramas; revisa los avisos de cobertura al comparar días.</div>')

    section("Repositorios y usuarios más activos", "Rankings de actividad. El periodo y el criterio de orden solo afectan a la Tabla 1.")
    o1, o2, _ = st.columns([2.4, 2, 4])
    period = o1.radio("Periodo de la Tabla 1", ["Día seleccionado", "Últimos 7 días"], horizontal=True)
    order_lbl = o2.selectbox("Ordenar repositorios por", list(REPO_ES.values()))
    order_col = {v: k for k, v in REPO_ES.items()}[order_lbl]
    win = (sel,) if period == "Día seleccionado" else tuple(d for d in dd["event_date"] if sel - timedelta(days=6) <= d <= sel)
    t1, t2 = st.columns([3, 2], gap="large")
    with t1:
        scope = fdate(sel, weekday=True) if len(win) == 1 else f"{fdate(win[0])} – {fdate(win[-1])} ({len(win)} días cargados)"
        fig_head("Tabla 1", f"Top {top_n} repositorios por {order_lbl.lower()}", scope)
        with st.spinner(f"Agregando {len(win)} particiones diarias de repo_activity_by_day…"):
            rr = repo_rank(win)
        if rr.empty:
            st.info("Sin actividad de repositorios para el periodo.")
        else:
            tr = rr.sort_values([order_col, "total_events", "repo_name"], ascending=[False, False, True]).head(top_n).copy()
            tr.insert(0, "#", range(1, len(tr) + 1))
            try:
                tr["usuarios"] = tr["repo_name"].map(degree_of(tuple(tr["repo_name"]))).fillna(0)
            except Exception:
                tr["usuarios"] = None
            shown = [c for c in REPO_COLS if c in (order_col, "total_events") or tr[c].sum() > 0]
            cols = [("#", "#", "rank"), ("repo_name", "Repositorio", "repo")] + [(c, REPO_ES[c], "int") for c in shown]
            cols.append(("usuarios", "Usuarios (grafo)*", "int"))
            repo_search = st.text_input("Buscar repositorio en este ranking", key="buscar_repositorio",
                                        placeholder="Parte del nombre del repositorio",
                                        help=f"Filtra los {len(tr)} repositorios de este ranking. Conserva sus posiciones originales.")
            visible_repos = filter_ranking(tr, "repo_name", repo_search)
            st.caption(f"{len(visible_repos)} de {len(tr)} repositorios del ranking. La búsqueda se limita a esta tabla.")
            if visible_repos.empty:
                st.info("No hay coincidencias en este ranking. Prueba otro nombre o borra la búsqueda.")
            st.html(table_html(visible_repos, cols, bar=order_col, sorted_col=order_col)
                    + '<div class="tnote">Fuente: Cassandra · <code>repo_activity_by_day</code> (suma de las particiones diarias del '
                      "periodo). * Grado del repositorio en el grafo acumulado de Neo4j (todas las fechas), no solo el periodo. "
                      "GH Archive registra eventos, no estados: «Estrellas» son las recibidas en el periodo, no el total histórico."
                      + (" Las columnas sin actividad en el periodo se omiten." if len(shown) < len(REPO_COLS) else "") + "</div>")
            download_csv(visible_repos[[c for c, _, _ in cols]].rename(columns={"#": "posicion"}),
                         f"ranking_repositorios_{win[0]}_{win[-1]}_utc.csv", "csv_repositorios",
                         fecha_analisis_utc=sel, inicio_periodo_utc=win[0], fin_periodo_utc=win[-1],
                         alcance_usuarios_grafo="Acumulado: todas las fechas")
    with t2:
        fig_head("Tabla 2", "Top 10 usuarios del día", fdate(sel, weekday=True))
        ua = user_activity(sel)
        if ua:
            tu = pd.DataFrame(ua["top"])
            tu.insert(0, "#", range(1, len(tu) + 1))
            user_search = st.text_input("Buscar usuario en este ranking", key="buscar_usuario",
                                        placeholder="Parte del nombre del usuario",
                                        help=f"Filtra los {len(tu)} usuarios de este ranking. Conserva sus posiciones originales.")
            visible_users = filter_ranking(tu, "actor_login", user_search)
            st.caption(f"{len(visible_users)} de {len(tu)} usuarios del ranking. La búsqueda se limita a esta tabla.")
            if visible_users.empty:
                st.info("No hay coincidencias en este ranking. Prueba otro nombre o borra la búsqueda.")
            st.html(table_html(visible_users, [("#", "#", "rank"), ("actor_login", "Usuario", "user"), ("event_count", "Eventos", "int"),
                                    ("share", "% del día", "pct")], bar="event_count")
                    + f'<div class="tnote"><b>Lectura.</b> Las cuentas automatizadas (sufijo [bot]) son {ua["bot_users"]:,} de '
                      f'{ua["users"]:,} usuarios y generan el {ua["bot_events"] / ua["total"] * 100:.1f} % de los eventos. El 1 % más '
                      f'activo ({ua["top1_k"]:,} cuentas) concentra el {ua["top1_events"] / ua["total"] * 100:.1f} %; la mediana es '
                      f'{ua["median"]:.0f} evento{"" if ua["median"] == 1 else "s"} por usuario: unas pocas cuentas muy activas '
                      'elevan el promedio del KPI 3.<br>'
                      'Fuente: Cassandra · <code>user_activity_by_day</code>.</div>')
            download_csv(visible_users.rename(columns={"#": "posicion"}), f"ranking_usuarios_{sel}_utc.csv",
                         "csv_usuarios", fecha_analisis_utc=sel)

    with st.expander("Consultas CQL de esta pestaña"):
        st.code(f"""-- Gráficos 1 y 2: una partición (el día) de la tabla horaria
SELECT event_hour, event_type, event_count FROM events_by_hour WHERE event_date = '{sel}';
-- Gráfico 3: totales diarios (partición por año, ordenada por fecha DESC)
SELECT event_date, total_events, unique_users, unique_repos FROM daily_totals WHERE year = {sel.year};
-- Indicadores (tarjetas y fichas KPI): calculados por Airflow
SELECT kpi_name, kpi_value, kpi_label, computed_at FROM kpis_by_date WHERE event_date = '{sel}';
-- Tabla 1: actividad por repositorio (una partición por día del periodo)
SELECT repo_name, pull_requests, issues, stars, forks, pushes, total_events FROM repo_activity_by_day WHERE event_date = '{sel}';
-- Tabla 2: eventos por usuario del día
SELECT actor_login, event_count FROM user_activity_by_day WHERE event_date = '{sel}';""", language="sql")

with tab_g:
    try:
        gs = graph_stats()
        gt = graph_top(top_n)
    except Exception as exc:
        st.error(f"No se pudo consultar Neo4j: {exc}")
    else:
        rels = gs["rels"]
        inter = sum(rels.get(t, 0) for t in REL_ES)
        st.html('<p class="tab-lead">Modelo de grafo: <code>(:User)-[:PUSHED | OPENED_PR | OPENED_ISSUE | STARRED | FORKED '
                '{count, first_seen, last_seen}]-&gt;(:Repo)-[:BELONGS_TO]-&gt;(:Org)</code>. Es <b>acumulado</b>: reúne todas las '
                "fechas cargadas, por lo que no depende de la fecha de análisis. Consultas en vivo.</p>")
        st.html('<div class="stats">'
                + stat("Usuarios", f"{gs['users']:,}", "nodos <code>:User</code>")
                + stat("Repositorios", f"{gs['repos']:,}", "nodos <code>:Repo</code>")
                + stat("Organizaciones", f"{gs['orgs']:,}", "nodos <code>:Org</code>")
                + stat("Interacciones", f"{inter:,}", "relaciones usuario → repositorio")
                + stat("Pertenencias", f"{rels.get('BELONGS_TO', 0):,}", "relaciones repositorio → organización") + "</div>")
        a, b = st.columns([2, 3], gap="large")
        with a:
            fig_head("Gráfico 4", "Interacciones por tipo de relación", "porcentaje y número de relaciones")
            rt = sorted(((t, rels.get(t, 0)) for t in REL_ES), key=lambda x: -x[1])
            show(hbar([REL_ES[t] for t, _ in rt], [v for _, v in rt], [REL_COLOR[t] for t, _ in rt],
                      [f"{v / inter * 100:.1f} %  ·  {fnum(v)}" if inter else "0" for _, v in rt],
                      "<b>%{y}</b> (%{customdata})<br>%{x:,} relaciones<extra></extra>", customdata=[t for t, _ in rt],
                      height=300), 300, "g7")
            if inter:
                fig_note(f"{REL_ES[rt[0][0]]} representa el {rt[0][1] / inter * 100:.1f} % de las {inter:,} interacciones. Solo cinco "
                         "tipos de evento generan relaciones en el grafo.", "Neo4j · conteo por tipo de relación.")
        with b:
            if gt.empty:
                st.info("El grafo aún no tiene relaciones.")
            else:
                repo = st.selectbox("Repositorio a explorar (Gráficos 5 y 6)", gt["repo"].tolist())
                fig_head("Gráfico 5", f"Top {top_n} repositorios por usuarios conectados", "grado del nodo: usuarios distintos con al menos una relación")
                show(hbar(gt["repo"].tolist(), gt["usuarios"].tolist(),
                          [DB_COLOR["Neo4j"] if r == repo else OTHER for r in gt["repo"]], [f"{v:,}" for v in gt["usuarios"]],
                          "<b>%{y}</b><br>%{x:,} usuarios distintos · %{customdata:,} interacciones<extra></extra>",
                          customdata=gt["interacciones"].tolist()), 34 * len(gt) + 24, "g8")
                note = (f"{gt['repo'].iloc[0]} encabeza el ranking con {gt['usuarios'].iloc[0]:,} usuarios distintos (KPI 5 calculado "
                        "en vivo). La barra resaltada es el repositorio explorado abajo.")
                if r5 and d5 is not None and (r5 != gt["repo"].iloc[0] or int(d5) != int(gt["usuarios"].iloc[0])):
                    note += (f" El KPI 5 del {fdate(sel, year=False)} ({esc(r5)}, {d5:,.0f} usuarios) corresponde al grafo "
                             "acumulado hasta esa fecha.")
                fig_note(note, "Neo4j · grado por repositorio.")
                st.html(f'<div class="tnote">Repositorio seleccionado: {github_link(repo, "repo")}</div>')
                download_csv(gt, f"ranking_grafo_fecha_analisis_{sel}_utc.csv", "csv_grafo",
                             fecha_analisis_utc=sel, alcance="Grafo acumulado: todas las fechas, independiente de la fecha de análisis")
        if not gt.empty:
            eg = ego(repo)
            if eg["users"]:
                e1, e2 = st.columns([3, 2], gap="large")
                with e1:
                    fig_head("Gráfico 6", f"Vecindario de {esc(repo)}",
                             f"{len(eg['users'])} de {eg['deg']:,} usuarios conectados (los de más interacciones); sector = relación dominante")
                    show(fig_ego(repo, eg), 520, "g9")
                    org = f" Pertenece a la organización <b>{esc(eg['org'])}</b>." if eg.get("org") else ""
                    fig_note(f"{eg['deg']:,} usuarios distintos y {eg['inter']:,} interacciones acumuladas; {eg['bots']:,} cuentas "
                             f"automatizadas (rombos).{org} El tamaño del nodo es proporcional a sus interacciones.",
                             "Neo4j · patrón <code>(:User)-[r]-&gt;(:Repo {name})</code>.")
                with e2:
                    fig_head("Tabla 3", "Usuarios con más interacciones", "relaciones y periodo de actividad en el repositorio")
                    nb = pd.DataFrame([{
                        "usuario": u["usuario"],
                        "rels": " · ".join(f"{REL_ES.get(r['tipo'], r['tipo'])} ×{r['veces']:,}" for r in u["rels"]),
                        "desde": fdate(min(r["desde"] for r in u["rels"] if r["desde"]).date(), year=False) if any(r["desde"] for r in u["rels"]) else "—",
                        "hasta": fdate(max(r["hasta"] for r in u["rels"] if r["hasta"]).date(), year=False) if any(r["hasta"] for r in u["rels"]) else "—",
                    } for u in sorted(eg["users"], key=lambda u: -(u["total"] or 0))[:12]])
                    st.html(table_html(nb, [("usuario", "Usuario", "user"), ("rels", "Relaciones (interacciones)", "text"),
                                            ("desde", "Primera", "nw"), ("hasta", "Última", "nw")])
                            + '<div class="tnote">Primera y última actividad: propiedades <code>first_seen</code> y '
                              "<code>last_seen</code> de las relaciones.</div>")
                    download_csv(nb, f"usuarios_grafo_fecha_analisis_{sel}_utc.csv", "csv_vecindario",
                                 fecha_analisis_utc=sel, repositorio=repo, alcance="Grafo acumulado: todas las fechas")
        with st.expander("Consultas Cypher de esta pestaña"):
            st.code("""// Gráfico 4: relaciones por tipo (Neo4j responde desde su count store)
MATCH ()-[r:PUSHED]->() RETURN count(r)          // una consulta por tipo de relación
// Gráfico 5 y KPI 5: grado (usuarios distintos) por repositorio
MATCH (u:User)-[r]->(repo:Repo)
RETURN repo.name, count(DISTINCT u) AS usuarios, sum(r.count) AS interacciones
ORDER BY usuarios DESC LIMIT %d
// Gráfico 6 y Tabla 3: vecindario del repositorio
MATCH (u:User)-[r]->(:Repo {name: '%s'})
RETURN u.login, type(r), r.count, r.first_seen, r.last_seen ORDER BY r.count DESC""" % (top_n, repo if not gt.empty else ""),
                    language="cypher")

with tab_m:
    try:
        mo, md = mongo_overview(), mongo_day(sel)
    except Exception as exc:
        st.error(f"No se pudo consultar MongoDB: {exc}")
    else:
        st.html('<p class="tab-lead">Colección <code>events</code>: un documento JSON por evento con <code>actor</code>, '
                "<code>repo</code>, <code>created_at</code> y el <code>payload</code> propio de cada tipo. Es la única capa que conserva "
                "el payload, por eso el KPI 4 se calcula aquí.</p>")
        cass_n = int(day_row["total_events"])
        diff = md["count"] - cass_n
        rec = (f"{md['count'] / cass_n * 100:.1f} %" if cass_n else "—")
        st.html('<div class="stats">'
                + stat("Documentos en la colección", f"{mo['total']:,}", "estimación por metadatos de la colección")
                + stat(f"Documentos del {fdate(sel, year=False)}", f"{md['count']:,}", "consulta por rango de <code>created_at</code>")
                + stat("Conciliación con Cassandra", rec,
                       "coincide con <code>daily_totals</code>" if diff == 0 else f"{diff:+,} documentos frente a <code>daily_totals</code>")
                + stat("Periodo almacenado", f"{fdate(mo['first'].date(), year=False)} – {fdate(mo['last'].date())}" if mo["first"] else "—",
                       "primer y último <code>created_at</code>") + "</div>")
        a, b = st.columns([3, 2], gap="large")
        acts = md["actions"]
        with a:
            fig_head("Gráfico 7", "Ciclo de vida de los pull requests", f"eventos PullRequestEvent del {fdate(sel, weekday=True)} por <code>payload.action</code>")
            if acts:
                ordered = sorted(acts.items(), key=lambda x: -x[1])
                show(hbar([PR_ACTION_ES.get(k, k) for k, _ in ordered], [v for _, v in ordered],
                          [ACCENT if k in ("merged", "closed") else OTHER for k, _ in ordered], [f"{v:,}" for _, v in ordered],
                          "<b>%{y}</b> (payload.action = %{customdata})<br>%{x:,} eventos<extra></extra>",
                          customdata=[k for k, _ in ordered]), 34 * len(ordered) + 24, "g10")
                merged, closed = acts.get("merged", 0), acts.get("closed", 0)
                if merged + closed:
                    fig_note(f"Las barras resaltadas forman el KPI 4: {merged:,} / ({merged:,} + {closed:,}) = "
                             f"<b>{merged / (merged + closed) * 100:.1f} %</b>. Las demás acciones (abrir, etiquetar, asignar) no cierran "
                             "un PR y no intervienen.", "MongoDB · <code>events</code> (agregación sobre <code>payload.action</code>).")
            else:
                st.info("No hay eventos PullRequestEvent en el día.")
        with b:
            fig_head("Consulta", "Agregación que calcula el KPI 4", "se ejecuta en la etapa 6 del DAG (índice ix_type_date)")
            st.code(f"""db.events.aggregate([
  {{ $match: {{
      type: "PullRequestEvent",
      created_at: {{
        $gte: ISODate("{sel}T00:00:00Z"),
        $lt:  ISODate("{sel + timedelta(days=1)}T00:00:00Z") }} }} }},
  {{ $group: {{ _id: "$payload.action", n: {{ $sum: 1 }} }} }}
])
// KPI 4 = n(merged) / (n(merged) + n(closed)) × 100""", language="javascript")
        fig_head("Tabla 4", "Muestra de documentos del día", "los 10 eventos más recientes de la fecha (orden por created_at)")
        if md["latest"]:
            st.html(table_html(pd.DataFrame(md["latest"]), [("hora", "Hora (UTC)", "text"), ("tipo", "Tipo", "text"),
                                                            ("tecnico", "Tipo técnico", "text"), ("usuario", "Usuario", "user"),
                                                            ("repo", "Repositorio", "repo"), ("accion", "payload.action", "text")]))
        if md["sample"]:
            with st.expander("Ver el documento JSON completo del evento más reciente"):
                st.json(md["sample"], expanded=True)

with tab_doc:
    section("Cobertura y calidad de la carga", "Una fila por día. Las horas provienen de <code>events_by_hour</code>; los conteos, "
            "de la tabla de trazabilidad <code>pipeline_runs</code> que escribe cada corrida del DAG.")
    rn = runs()
    agg = (rn.groupby("run_date").agg(raw=("raw_count", "sum"), clean=("clean_count", "sum"), mongo=("loaded_mongo", "sum"),
                                       neo=("loaded_neo4j", "sum")) if not rn.empty else pd.DataFrame())
    rows = []
    for d in dates:
        a = agg.loc[d] if d in agg.index else None
        n = len(cov[d])
        state = ('<span class="badge ok">Completo</span>' if n == 24 else
                 '<span class="badge warn">En curso</span>' if d == today_utc else '<span class="badge warn">Parcial</span>')
        rows.append({"fecha": fdate(d, weekday=True), "horas": f'<span class="nw">{hour_strip(cov[d])}&nbsp; {n}/24</span>', "estado": state,
                     "clean": None if a is None else a["clean"],
                     "desc": None if a is None else a["raw"] - a["clean"],
                     "mongo": None if a is None else a["mongo"], "neo": None if a is None else a["neo"],
                     "push": f"{len(dd.set_index('event_date').at[d, 'push_hours'])}/{n}",
                     "users": int(dd.set_index("event_date").at[d, "unique_users"])})
    st.html(table_html(pd.DataFrame(rows), [("fecha", "Fecha", "nw"), ("horas", "Horas con datos", "html"), ("estado", "Estado", "html"),
                                            ("push", "Horas con Push", "nw"), ("clean", "Eventos válidos", "int"), ("desc", "Descartados", "int"),
                                            ("mongo", "Insertados en MongoDB", "int"), ("neo", "Aristas Neo4j", "int"),
                                            ("users", "Usuarios activos", "int")])
            + '<div class="tnote">Descartados = eventos crudos que no superan la validación (campos obligatorios, fecha ISO-8601, '
              "id duplicado). Horas con Push = horas cargadas en las que el feed trae eventos Push. Insertados en MongoDB = documentos nuevos de cada corrida: al reintentar una hora los documentos ya "
              "existentes no se duplican, por eso puede ser menor que los eventos válidos (la conciliación exacta está en la "
              "pestaña MongoDB). Aristas Neo4j = relaciones usuario→repositorio fusionadas en el grafo durante esas horas.</div>")

    section("Arquitectura y flujo de datos", "DAG <code>github_events_pipeline</code> de Apache Airflow, programado cada hora. "
            "Cada etapa lee la salida de la anterior: la arquitectura es por capas.")
    steps = [("Fuente", "GH Archive", "Un archivo JSON comprimido por hora con los eventos públicos de GitHub.", NEUTRAL),
             ("Etapas 1-2", "Extracción y limpieza", "Descarga; campos obligatorios, fecha ISO-8601, deduplicación por id y payload recortado.", NEUTRAL),
             ("Etapa 3", "MongoDB", "Colección <code>events</code>: el documento original de cada evento.", DB_COLOR["MongoDB"]),
             ("Etapa 4", "Cassandra", "Lee MongoDB y escribe agregados por hora y día e interacciones usuario→repositorio.", DB_COLOR["Cassandra"]),
             ("Etapa 5", "Neo4j", "Lee <code>user_repo_interactions_by_hour</code> y fusiona Usuario→Repositorio→Organización.", DB_COLOR["Neo4j"]),
             ("Etapa 6", "Indicadores", "Cinco KPI (al menos uno por base de datos) guardados en <code>kpis_by_date</code>.", NEUTRAL),
             ("Consumo", "Dashboard", "Streamlit consulta las tres bases de datos.", NEUTRAL)]
    st.html('<div class="flow">' + '<span class="ar">→</span>'.join(
        f'<div class="st" style="--c:{c}"><div class="k">{k}</div><div class="t">{t}</div><div class="d">{d}</div></div>'
        for k, t, d, c in steps) + "</div>")
    just = pd.DataFrame([
        {"db": f'<span class="sw" style="background:{DB_COLOR["MongoDB"]}"></span> MongoDB', "que": "Documento JSON original de cada evento (actor, repo, payload, fecha).",
         "porque": "Esquema flexible: cada tipo de evento trae un payload distinto. Permite agregaciones sobre campos anidados como payload.action."},
        {"db": f'<span class="sw" style="background:{DB_COLOR["Cassandra"]}"></span> Cassandra', "que": "Series temporales y agregados por hora y día; KPIs por fecha.",
         "porque": "Escrituras masivas append-only y lecturas de una partición (el día) en tiempo constante; tablas diseñadas por consulta, sin JOIN."},
        {"db": f'<span class="sw" style="background:{DB_COLOR["Neo4j"]}"></span> Neo4j', "que": "Grafo Usuario→Repositorio→Organización con conteo de interacciones.",
         "porque": "Grado, vecindario y caminos se resuelven recorriendo relaciones, sin los JOIN encadenados que exigiría un modelo tabular."}])
    st.html(table_html(just, [("db", "Base de datos", "html"), ("que", "Qué almacena", "text"), ("porque", "Por qué esa base de datos", "text")], cls="t def"))

    section("Notas para la interpretación")
    st.html(f"""<ul class="notes">
<li>Todas las fechas y horas están en UTC (Lima = UTC−5): un «día» va de 00:00 a 23:59 UTC.</li>
<li>Un día es <b>parcial</b> si tiene menos de 24 horas cargadas (día en curso o carga histórica incompleta). Sus totales no son
comparables con los de días completos; el KPI 2 compara solo las horas presentes en ambos días.</li>
<li><b>Tipos estables</b> son todos menos Push y creación o borrado de ramas. GH Archive 2026 entrega esos tres tipos de forma
intermitente (aparecen y desaparecen juntos), así que el volumen total de un día depende de cuántas horas los traen. El KPI 2 se
calcula solo sobre tipos estables y el Gráfico 3 los muestra como línea: es la serie comparable entre días.</li>
<li>El volumen del feed de GH Archive en 2026 cambia de forma abrupta entre horas (p. ej., de ~80 mil a ~7 mil eventos por hora) y
algunos tipos (Push, creación y borrado de ramas) aparecen de forma intermitente: esas variaciones vienen de la fuente y no
necesariamente de la actividad real en GitHub.</li>
<li>El KPI 5 de cada fecha usa el grafo acumulado hasta el final de ese día (relaciones con <code>first_seen</code> anterior);
las consultas de la pestaña Neo4j muestran el grafo completo.</li>
<li>El grafo de Neo4j es acumulado y, para acotar su tamaño, cada hora incorpora solo los {config.NEO4J_TOP_REPOS:,} repositorios y
{config.NEO4J_TOP_USERS:,} usuarios más activos; únicamente cinco tipos de evento generan relaciones.</li>
<li>GH Archive registra eventos, no estados: «estrellas» o «forks» son los recibidos en el periodo, no el total histórico del repositorio.</li>
<li>Las cuentas con sufijo [bot] (p. ej., <code>github-actions[bot]</code>) son automatizaciones y se incluyen en todos los indicadores.</li>
</ul>""")

st.html('<div class="foot"><span>Fuente de datos: GH Archive (gharchive.org), eventos públicos de GitHub. Elaboración propia.</span>'
        "<span>Proyecto Grupal II · Big Data · UTEC · 2026</span></div>")
