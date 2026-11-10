"""Dashboard analítico - Streamlit
Conecta las 3 bases de datos:
  * Cassandra  -> series temporales, agregados y KPIs
  * Neo4j      -> grafo usuario-repositorio (conexiones)
  * MongoDB    -> documentos originales (eventos crudos)
Ejecutar: streamlit run dashboard/app.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config  # noqa: E402

# ------------------------------------------------------------------ estilo
# Paleta categórica en orden fijo (validada para daltonismo) + secuencial azul.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#1c5cab", "#0d366b"]
INK, INK2, MUTED, GRID = "#111111", "#3b3f46", "#5f6572", "#d6d8dd"
FONT = "IBM Plex Sans, Inter, Segoe UI, system-ui, sans-serif"
DB_COLOR = {"Cassandra": "#2a78d6", "MongoDB": "#008300", "Neo4j": "#6250d6"}   # mismos tonos que las series 1, 6 y 7
LAYOUT = dict(
    template="simple_white",
    font=dict(family=FONT, color=INK2, size=14),
    title=dict(font=dict(size=18, color=INK, family=FONT), x=0, xanchor="left"),
    margin=dict(l=8, r=16, t=44, b=8),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(showgrid=False, linecolor="#9a9ea8", tickfont=dict(color=INK2, size=13)),
    yaxis=dict(gridcolor=GRID, showline=False, tickfont=dict(color=INK2, size=13), zeroline=False),
    hoverlabel=dict(bgcolor="#ffffff", font=dict(color=INK, size=14, family=FONT)),
    legend=dict(orientation="h", y=-0.28, yanchor="top", x=0, font=dict(color=INK2, size=13)),
)

CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] * { font-family: 'IBM Plex Sans', Inter, 'Segoe UI', system-ui, sans-serif; }
[data-testid="stAppViewContainer"] { color: #111111; }
.block-container { padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px; }
h1 { font-size: 2.1rem !important; font-weight: 700 !important; color: #111111 !important; letter-spacing: -0.01em; margin-bottom: 0.2rem !important; }
h2, h3 { color: #111111 !important; font-weight: 600 !important; }
p, li, label, .stMarkdown { font-size: 1.02rem; line-height: 1.5; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { font-size: 0.95rem !important; color: #3b3f46 !important; }
button[data-baseweb="tab"] p { font-size: 1.08rem !important; font-weight: 600 !important; color: #3b3f46; }
button[data-baseweb="tab"][aria-selected="true"] p { color: #1f4e9c; }
[data-testid="stWidgetLabel"] p { font-size: 0.95rem !important; font-weight: 600; color: #3b3f46; text-transform: uppercase; letter-spacing: 0.04em; }
.kpi { background: #f2f4f8; border-radius: 10px; padding: 14px 18px 12px 18px; min-height: 158px; border: 1px solid #e3e6ec; }
.kpi-label { font-size: 0.9rem; font-weight: 600; color: #3b3f46; text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-value { font-size: 2.5rem; font-weight: 700; color: #111111; line-height: 1.15; margin: 4px 0 2px 0; font-variant-numeric: tabular-nums; word-break: break-all; }
.kpi-note { font-size: 1rem; color: #1f2937; }
.kpi-src { font-size: 0.85rem; color: #5f6572; margin-top: 8px; }
.kpi-src code { font-size: 0.82rem; }
[data-testid="stTable"] table { font-size: 1rem; border-collapse: collapse; }
[data-testid="stTable"] th { font-weight: 700 !important; color: #111111 !important; background: #f2f4f8; border-bottom: 2px solid #9a9ea8 !important; text-align: left; }
[data-testid="stTable"] td { color: #111111; border-bottom: 1px solid #e3e6ec !important; font-variant-numeric: tabular-nums; }
[data-testid="stTable"] tbody tr:nth-child(even) td { background: #fafbfc; }
[data-testid="stMetricValue"] { font-size: 2.2rem; font-weight: 700; color: #111111; }
[data-testid="stMetricLabel"] p { font-size: 0.95rem !important; font-weight: 600; color: #3b3f46; }
</style>
"""


def table(df: pd.DataFrame, int_cols: list[str] | None = None):
    """Tabla HTML (st.table) con miles separados; se puede estilizar con CSS, a diferencia de st.dataframe."""
    cols = int_cols if int_cols is not None else [c for c in df.columns if pd.api.types.is_integer_dtype(df[c])]
    st.table(df.style.format({c: "{:,.0f}" for c in cols}))


def card(col, label, value, note, source, table_ref=""):
    color = DB_COLOR[source]
    col.markdown(
        f'<div class="kpi" style="border-left:6px solid {color}">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-note">{note}</div>'
        f'<div class="kpi-src"><span style="color:{color};font-weight:700">■</span> {source}'
        + (f' · <code>{table_ref}</code>' if table_ref else "") + '</div></div>',
        unsafe_allow_html=True)


def hbar(x, y, color, title, text=None, hover=None, height=None) -> go.Figure:
    """Barra horizontal con etiquetas fuera; extiende el eje X para que el texto no se recorte."""
    fig = go.Figure(go.Bar(x=x, y=y, orientation="h", marker=dict(color=color, cornerradius=4),
                           text=text if text is not None else x, textposition="outside",
                           cliponaxis=False, hovertemplate=hover or "%{y}: %{x:,}<extra></extra>"))
    extra = dict(height=height) if height else {}
    fig.update_layout(**layout(title=title, showlegend=False, xaxis={"range": [0, float(max(x)) * 1.22]}, **extra))
    return fig


def layout(**overrides) -> dict:
    """LAYOUT base + overrides; los dicts de ejes se fusionan en vez de reemplazarse."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in LAYOUT.items()}
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out

st.set_page_config(page_title="GitHub Events · Multimodelo", page_icon="📊", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
st.title("GitHub Events · Arquitectura multimodelo")
st.caption("MongoDB (documentos) → Cassandra (series temporales) → Neo4j (grafo) · orquestado con Apache Airflow")


# ------------------------------------------------------------------ datos (cache 5 min)
@st.cache_data(ttl=300, show_spinner=False)
def available_dates() -> list[date]:
    s = config.cassandra_session()
    rows = s.execute("SELECT event_date FROM daily_totals")
    return sorted({r.event_date.date() for r in rows}, reverse=True)


@st.cache_data(ttl=300, show_spinner=False)
def kpis_for(d: date) -> pd.DataFrame:
    s = config.cassandra_session()
    rows = s.execute("SELECT kpi_name, kpi_value, kpi_label, computed_at FROM kpis_by_date WHERE event_date=%s", (d,))
    return pd.DataFrame([r._asdict() for r in rows])


@st.cache_data(ttl=300, show_spinner=False)
def events_by_hour(d: date) -> pd.DataFrame:
    s = config.cassandra_session()
    rows = s.execute("SELECT event_hour, event_type, event_count FROM events_by_hour WHERE event_date=%s", (d,))
    return pd.DataFrame([r._asdict() for r in rows])


@st.cache_data(ttl=300, show_spinner=False)
def daily_totals(days: int = 14) -> pd.DataFrame:
    s = config.cassandra_session()
    year = date.today().year
    rows = s.execute("SELECT event_date, total_events, unique_users, unique_repos FROM daily_totals WHERE year=%s LIMIT %s", (year, days))
    df = pd.DataFrame([r._asdict() for r in rows])
    if not df.empty:
        df["event_date"] = pd.to_datetime(df["event_date"].astype(str))
        df = df.sort_values("event_date")
    return df


REPO_COLS = ["pushes", "stars", "forks", "issues", "pull_requests", "total_events"]
REPO_ES = {"repo_name": "repositorio", "pushes": "pushes", "stars": "estrellas", "forks": "forks", "issues": "issues",
           "pull_requests": "pull requests", "total_events": "eventos", "usuarios": "usuarios distintos"}


@st.cache_data(ttl=300, show_spinner=False)
def repo_activity(dates: tuple[date, ...]) -> pd.DataFrame:
    """Actividad por repo sumada sobre las fechas dadas (una partición de repo_activity_by_day por día)."""
    s = config.cassandra_session()
    frames = []
    for d in dates:
        rows = s.execute("SELECT repo_name, pushes, stars, forks, issues, pull_requests, total_events FROM repo_activity_by_day WHERE event_date=%s", (d,))
        frames.append(pd.DataFrame([r._asdict() for r in rows]))
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
    if df.empty:
        return df
    return df.fillna(0).groupby("repo_name", as_index=False)[REPO_COLS].sum()


@st.cache_data(ttl=300, show_spinner=False)
def distinct_users_for(repos: tuple[str, ...]) -> dict:
    """Usuarios distintos conectados a cada repo (grado del nodo en Neo4j)."""
    with config.neo4j_driver() as drv:
        recs = drv.execute_query(
            "MATCH (u:User)-[]->(r:Repo) WHERE r.name IN $repos RETURN r.name AS repo, count(DISTINCT u) AS usuarios",
            repos=list(repos), database_=config.NEO4J_DATABASE).records
    return {rec["repo"]: rec["usuarios"] for rec in recs}


def top_repos(dates: tuple[date, ...], n: int, order_by: str) -> pd.DataFrame:
    df = repo_activity(dates)
    if df.empty:
        return df
    df = df.nlargest(n, order_by)
    df["usuarios"] = df["repo_name"].map(distinct_users_for(tuple(df["repo_name"]))).fillna(0).astype(int)
    df = df[["repo_name", "usuarios"] + [c for c in REPO_COLS if df[c].sum() > 0]]   # oculta columnas en cero (p. ej. pushes)
    return df.rename(columns=REPO_ES).set_index("repositorio")


@st.cache_data(ttl=300, show_spinner=False)
def graph_top_connected(n: int = 10) -> pd.DataFrame:
    with config.neo4j_driver() as drv:
        recs = drv.execute_query(
            "MATCH (u:User)-[r]->(repo:Repo) "
            "RETURN repo.name AS repo, count(DISTINCT u) AS usuarios, count(r) AS relaciones, "
            "collect(DISTINCT type(r)) AS tipos ORDER BY usuarios DESC LIMIT $n",
            n=n, database_=config.NEO4J_DATABASE).records
    return pd.DataFrame([dict(r) for r in recs])


@st.cache_data(ttl=300, show_spinner=False)
def graph_stats() -> dict:
    with config.neo4j_driver() as drv:
        r = drv.execute_query(
            "MATCH (u:User) WITH count(u) AS users MATCH (r:Repo) WITH users, count(r) AS repos "
            "MATCH ()-[rel]->() RETURN users, repos, count(rel) AS rels", database_=config.NEO4J_DATABASE).records
    return dict(r[0]) if r else {"users": 0, "repos": 0, "rels": 0}


@st.cache_data(ttl=300, show_spinner=False)
def graph_neighbors(repo: str, n: int = 25) -> pd.DataFrame:
    with config.neo4j_driver() as drv:
        recs = drv.execute_query(
            "MATCH (u:User)-[r]->(repo:Repo {name:$repo}) RETURN u.login AS usuario, type(r) AS relacion, r.count AS veces "
            "ORDER BY veces DESC LIMIT $n", repo=repo, n=n, database_=config.NEO4J_DATABASE).records
    return pd.DataFrame([dict(r) for r in recs])


@st.cache_data(ttl=300, show_spinner=False)
def mongo_overview() -> tuple[int, pd.DataFrame, pd.DataFrame]:
    db = config.mongo_db()
    total = db.events.estimated_document_count()
    by_type = list(db.events.aggregate([{"$group": {"_id": "$type", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]))
    recent = list(db.events.find({}, {"type": 1, "actor.login": 1, "repo.name": 1, "created_at": 1}).sort("created_at", -1).limit(15))
    df_recent = pd.DataFrame([{"id": r["_id"], "tipo": r["type"], "usuario": r["actor"]["login"], "repo": r["repo"]["name"], "fecha": r["created_at"]} for r in recent])
    return total, pd.DataFrame(by_type).rename(columns={"_id": "tipo"}), df_recent


# ------------------------------------------------------------------ filtros (una fila)
try:
    dates = available_dates()
except Exception as exc:
    st.error(f"No se pudo conectar a Cassandra: {exc}")
    st.stop()
if not dates:
    st.info("Aún no hay datos. Ejecuta el DAG `github_events_pipeline` en Airflow o `python src/run_pipeline_local.py`.")
    st.stop()

f1, f2, _ = st.columns([2, 2, 6])
sel_date = f1.selectbox("Día", dates, format_func=lambda d: d.strftime("%d %b %Y"))
top_n = f2.slider("Top N repositorios", 5, 20, 10)

# ------------------------------------------------------------------ KPIs (stat tiles)
k = kpis_for(sel_date)
kv = {r.kpi_name: r for r in k.itertuples()} if not k.empty else {}

def _v(kpi):
    r = kv.get(kpi)
    return r.kpi_value if r is not None else None


def _lbl(kpi):
    r = kv.get(kpi)
    return r.kpi_label if r is not None else ""


c = st.columns(5)
v = _v("events_per_day")
card(c[0], "Eventos del día", f"{v:,.0f}" if v is not None else "—", "registros procesados por el pipeline", "Cassandra", "events_by_hour")
v = _v("daily_growth_pct")
if v is None:
    gv = "—"
else:
    gv = f'<span style="color:{"#008300" if v >= 0 else "#c0392b"}">{v:+.1f} %</span>'
card(c[1], "Crecimiento diario", gv, _lbl("daily_growth_pct") or "vs. día anterior, mismas horas", "Cassandra", "events_by_hour")
v = _v("avg_events_per_user")
card(c[2], "Eventos por usuario", f"{v:.2f}" if v is not None else "—", _lbl("avg_events_per_user") or "promedio del día", "Cassandra", "daily_totals")
v = _v("pr_merge_rate_pct")
card(c[3], "PRs aceptados", f"{v:.1f} %" if v is not None else "—", _lbl("pr_merge_rate_pct") or "merged / (merged + cerrados)", "MongoDB", "events.payload.action")
r = kv.get("top_repo_connections")
_name = r.kpi_label if r is not None else "—"
card(c[4], "Repo más conectado", _name, f"<b>{r.kpi_value:,.0f} usuarios distintos</b> (grado del nodo)" if r is not None else "", "Neo4j", "(User)-[]->(Repo)")
if kv:
    st.caption(f"KPIs calculados por Airflow a las {list(kv.values())[0].computed_at:%H:%M} UTC · fuente: Cassandra `kpis_by_date`")

# ------------------------------------------------------------------ pestañas por base de datos
tab_c, tab_g, tab_m, tab_doc = st.tabs(["⏱ Cassandra · series temporales", "🕸 Neo4j · grafo", "📄 MongoDB · documentos", "ℹ️ KPIs y arquitectura"])

with tab_c:
    left, right = st.columns([3, 2])
    ebh = events_by_hour(sel_date)
    if not ebh.empty:
        main_types = ["PullRequestEvent", "IssuesEvent", "IssueCommentEvent", "PullRequestReviewEvent", "WatchEvent", "ReleaseEvent", "ForkEvent", "PushEvent"]
        ebh["serie"] = ebh["event_type"].where(ebh["event_type"].isin(main_types), "Other")
        pivot = ebh.groupby(["event_hour", "serie"], as_index=False)["event_count"].sum()
        order = [t for t in main_types if t in set(pivot["serie"])] + (["Other"] if "Other" in set(pivot["serie"]) else [])
        fig = px.area(pivot, x="event_hour", y="event_count", color="serie", category_orders={"serie": order},
                      color_discrete_sequence=SERIES, title="Eventos por hora y tipo")
        fig.update_traces(line=dict(width=1.5), hovertemplate="%{y:,} eventos<extra>%{fullData.name}</extra>")
        fig.update_layout(**layout(hovermode="x unified", xaxis={"title": "Hora (UTC)"}, yaxis={"title": None}, legend_title_text=""))
        left.plotly_chart(fig, width="stretch")

        share = ebh.groupby("serie", as_index=False)["event_count"].sum().sort_values("event_count")
        fig2 = hbar(share["event_count"], share["serie"], SERIES[0], "Distribución por tipo de evento",
                    text=share["event_count"].map("{:,}".format))
        right.plotly_chart(fig2, width="stretch")

    dt = daily_totals()
    if len(dt) > 1:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=dt["event_date"], y=dt["total_events"], mode="lines+markers", name="Eventos",
                                  line=dict(color=SERIES[0], width=2), marker=dict(size=8)))
        fig3.update_layout(**layout(title="Tendencia diaria de eventos procesados", hovermode="x unified", showlegend=False))
        st.plotly_chart(fig3, width="stretch")

    o1, o2, _ = st.columns([2, 2, 6])
    period = o1.radio("Periodo", ["Día seleccionado", f"Todo el periodo cargado ({len(dates)} días)"], horizontal=True)
    order_opts = {"eventos": "total_events", "estrellas": "stars", "forks": "forks", "pull requests": "pull_requests", "issues": "issues"}
    order_lbl = o2.selectbox("Ordenar por", list(order_opts))
    sel_dates = (sel_date,) if period.startswith("Día") else tuple(dates)
    tr = top_repos(sel_dates, top_n, order_opts[order_lbl])
    if not tr.empty:
        scope = f"del {sel_date:%d %b %Y}" if len(sel_dates) == 1 else f"acumulados del {min(dates):%d %b} al {max(dates):%d %b %Y}"
        st.markdown(f"**Top {top_n} repositorios por {order_lbl}, {scope}** · eventos: Cassandra `repo_activity_by_day` · usuarios distintos: Neo4j")
        table(tr)
        st.caption("GH Archive registra eventos (alguien dio una estrella hoy), no estados (el repo tiene N estrellas): las cifras son actividad en el periodo, no totales históricos del repositorio.")

with tab_g:
    gs = graph_stats()
    g1, g2, g3 = st.columns(3)
    g1.metric("Usuarios (nodos)", f"{gs['users']:,}")
    g2.metric("Repositorios (nodos)", f"{gs['repos']:,}")
    g3.metric("Relaciones", f"{gs['rels']:,}")
    tc = graph_top_connected(top_n)
    if not tc.empty:
        fig = hbar(tc["usuarios"], tc["repo"], SERIES[6], "Repositorios con más usuarios conectados (grado del nodo)",
                   hover="%{y}<br>%{x} usuarios distintos<extra></extra>", height=max(320, 32 * len(tc) + 80))
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, width="stretch")
        repo = st.selectbox("Explorar vecinos de", tc["repo"].tolist())
        nb = graph_neighbors(repo)
        table(nb.set_index("usuario"))
        st.code(f"MATCH (u:User)-[r]->(repo:Repo {{name:'{repo}'}})\nRETURN u.login, type(r), r.count ORDER BY r.count DESC", language="cypher")

with tab_m:
    total, by_type, recent = mongo_overview()
    m1, m2 = st.columns([1, 3])
    m1.metric("Documentos en `events`", f"{total:,}")
    if not by_type.empty:
        by_type = by_type.head(8).sort_values("n")
        fig = hbar(by_type["n"], by_type["tipo"], SERIES[2], "Documentos por tipo (aggregate $group)",
                   text=by_type["n"].map("{:,}".format))
        m2.plotly_chart(fig, width="stretch")
    st.markdown("**Últimos eventos ingeridos** (colección `events`)")
    table(recent.set_index("id"), int_cols=[])
    with st.expander("Ver un documento completo"):
        doc = config.mongo_db().events.find_one(sort=[("created_at", -1)])
        st.json(doc, expanded=False)

with tab_doc:
    st.markdown("""
| KPI | BD fuente | Definición | Fórmula | Interpretación |
|---|---|---|---|---|
| Eventos del día | Cassandra | Registros procesados por el pipeline en el día | `Σ events_by_hour.event_count` | Volumen ingerido; base del resto |
| Crecimiento diario | Cassandra | Variación porcentual vs. las mismas horas del día anterior | `(E(d) − E(d−1)) / E(d−1) × 100` | >0: la actividad crece |
| Prom. eventos/usuario | Cassandra | Intensidad de actividad | `E(d) / daily_totals.unique_users(d)` | Valores altos: usuarios muy activos o bots |
| Tasa de fusión de PRs | MongoDB | Porcentaje de pull requests resueltos que fueron aceptados | `merged(d) / (merged(d) + closed(d)) × 100` sobre `payload.action` | Salud del flujo de contribución; solo existe en el documento original |
| Repo más conectado | Neo4j | Repositorio con más usuarios distintos (grado del nodo) | `MATCH (u)-[]->(r) RETURN r, count(DISTINCT u)` | Proyecto que concentra comunidad (o actividad automatizada si es anómalo) |

**Flujo por capas:** GH Archive (JSON/hora) → Airflow: extracción → limpieza → **MongoDB** (capa de documentos originales) → **Cassandra** lee MongoDB y escribe agregados por hora/día + `user_repo_interactions_by_hour` → **Neo4j** lee esa tabla de Cassandra y construye (Usuario)→(Repo)→(Org) → KPIs leen las tres BDs y se guardan en `kpis_by_date`.
""")
