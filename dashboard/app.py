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
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
LAYOUT = dict(
    template="simple_white",
    font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK2, size=13),
    margin=dict(l=8, r=8, t=36, b=8),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(showgrid=False, linecolor="#c3c2b7", tickfont=dict(color=MUTED)),
    yaxis=dict(gridcolor=GRID, showline=False, tickfont=dict(color=MUTED), zeroline=False),
    hoverlabel=dict(bgcolor="#ffffff", font=dict(color=INK)),
    legend=dict(orientation="h", y=1.12, x=0, font=dict(color=INK2)),
)


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
st.title("GitHub Events · Arquitectura multimodelo")
st.caption("MongoDB Atlas (documentos) · Cassandra (series temporales) · Neo4j AuraDB (grafo) · orquestado con Apache Airflow")


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


@st.cache_data(ttl=300, show_spinner=False)
def top_repos(d: date, n: int = 10) -> pd.DataFrame:
    s = config.cassandra_session()
    rows = s.execute("SELECT repo_name, pushes, stars, forks, issues, pull_requests, total_events FROM repo_activity_by_day WHERE event_date=%s", (d,))
    df = pd.DataFrame([r._asdict() for r in rows])
    return df.nlargest(n, "total_events") if not df.empty else df


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

def tile(col, label, kpi, fmt="{:,.0f}", suffix=""):
    r = kv.get(kpi)
    col.metric(label, (fmt.format(r.kpi_value) + suffix) if r is not None else "—", help=r.kpi_label if r is not None else None)

c = st.columns(6)
tile(c[0], "Eventos del día", "events_per_day")
tile(c[1], "Crecimiento diario", "daily_growth_pct", "{:+.1f}", " %")
tile(c[2], "Prom. eventos / usuario", "avg_events_per_user", "{:.2f}")
tile(c[3], "Participación de pushes", "push_share_pct", "{:.1f}", " %")
tile(c[4], "Hora pico (UTC)", "peak_hour", "{:02.0f}", ":00")
r = kv.get("top_repo_connections")
c[5].metric("Repo más conectado", (r.kpi_label if r is not None else "—"), help=f"{r.kpi_value:.0f} usuarios distintos" if r is not None else None)
if kv:
    st.caption(f"KPIs calculados por Airflow a las {list(kv.values())[0].computed_at:%H:%M} UTC · fuente: Cassandra `kpis_by_date`")

# ------------------------------------------------------------------ pestañas por base de datos
tab_c, tab_g, tab_m, tab_doc = st.tabs(["⏱ Cassandra · series temporales", "🕸 Neo4j · grafo", "📄 MongoDB · documentos", "ℹ️ KPIs y arquitectura"])

with tab_c:
    left, right = st.columns([3, 2])
    ebh = events_by_hour(sel_date)
    if not ebh.empty:
        main_types = ["PushEvent", "CreateEvent", "PullRequestEvent", "WatchEvent", "IssueCommentEvent", "IssuesEvent", "ForkEvent"]
        ebh["serie"] = ebh["event_type"].where(ebh["event_type"].isin(main_types), "Other")
        pivot = ebh.groupby(["event_hour", "serie"], as_index=False)["event_count"].sum()
        order = [t for t in main_types if t in set(pivot["serie"])] + (["Other"] if "Other" in set(pivot["serie"]) else [])
        fig = px.area(pivot, x="event_hour", y="event_count", color="serie", category_orders={"serie": order},
                      color_discrete_sequence=SERIES, title="Eventos por hora y tipo")
        fig.update_traces(line=dict(width=1.5), hovertemplate="%{y:,} eventos<extra>%{fullData.name}</extra>")
        fig.update_layout(**layout(hovermode="x unified", xaxis={"title": "Hora (UTC)"}, yaxis={"title": None}))
        left.plotly_chart(fig, use_container_width=True)

        share = ebh.groupby("serie", as_index=False)["event_count"].sum().sort_values("event_count")
        fig2 = go.Figure(go.Bar(x=share["event_count"], y=share["serie"], orientation="h",
                                marker=dict(color=SERIES[0], cornerradius=4), text=share["event_count"].map("{:,}".format),
                                textposition="outside", hovertemplate="%{y}: %{x:,}<extra></extra>"))
        fig2.update_layout(**layout(title="Distribución por tipo de evento", showlegend=False))
        right.plotly_chart(fig2, use_container_width=True)

    dt = daily_totals()
    if len(dt) > 1:
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=dt["event_date"], y=dt["total_events"], mode="lines+markers", name="Eventos",
                                  line=dict(color=SERIES[0], width=2), marker=dict(size=8)))
        fig3.update_layout(**layout(title="Tendencia diaria de eventos procesados", hovermode="x unified", showlegend=False))
        st.plotly_chart(fig3, use_container_width=True)

    tr = top_repos(sel_date, top_n)
    if not tr.empty:
        st.markdown(f"**Top {top_n} repositorios del día** (tabla `repo_activity_by_day`)")
        st.dataframe(tr.set_index("repo_name"), use_container_width=True)

with tab_g:
    gs = graph_stats()
    g1, g2, g3 = st.columns(3)
    g1.metric("Usuarios (nodos)", f"{gs['users']:,}")
    g2.metric("Repositorios (nodos)", f"{gs['repos']:,}")
    g3.metric("Relaciones", f"{gs['rels']:,}")
    tc = graph_top_connected(top_n)
    if not tc.empty:
        fig = go.Figure(go.Bar(x=tc["usuarios"], y=tc["repo"], orientation="h",
                               marker=dict(color=SERIES[6], cornerradius=4), text=tc["usuarios"], textposition="outside",
                               hovertemplate="%{y}<br>%{x} usuarios distintos<extra></extra>"))
        fig.update_layout(**layout(title="Repositorios con más usuarios conectados (grado del nodo)",
                                   yaxis={"autorange": "reversed"}, showlegend=False,
                                   height=max(320, 32 * len(tc) + 80)))
        st.plotly_chart(fig, use_container_width=True)
        repo = st.selectbox("Explorar vecinos de", tc["repo"].tolist())
        nb = graph_neighbors(repo)
        st.dataframe(nb, use_container_width=True, hide_index=True)
        st.code(f"MATCH (u:User)-[r]->(repo:Repo {{name:'{repo}'}})\nRETURN u.login, type(r), r.count ORDER BY r.count DESC", language="cypher")

with tab_m:
    total, by_type, recent = mongo_overview()
    m1, m2 = st.columns([1, 3])
    m1.metric("Documentos en `events`", f"{total:,}")
    if not by_type.empty:
        by_type = by_type.head(8).sort_values("n")
        fig = go.Figure(go.Bar(x=by_type["n"], y=by_type["tipo"], orientation="h",
                               marker=dict(color=SERIES[2], cornerradius=4), text=by_type["n"].map("{:,}".format), textposition="outside",
                               hovertemplate="%{y}: %{x:,}<extra></extra>"))
        fig.update_layout(**layout(title="Documentos por tipo (aggregate $group)", showlegend=False))
        m2.plotly_chart(fig, use_container_width=True)
    st.markdown("**Últimos eventos ingeridos** (colección `events`)")
    st.dataframe(recent, use_container_width=True, hide_index=True)
    with st.expander("Ver un documento completo"):
        doc = config.mongo_db().events.find_one(sort=[("created_at", -1)])
        st.json(doc, expanded=False)

with tab_doc:
    st.markdown("""
| KPI | Definición | Fórmula | Interpretación |
|---|---|---|---|
| Eventos del día | Registros procesados por el pipeline en el día | `Σ events_by_hour.event_count` | Volumen ingerido; base del resto |
| Crecimiento diario | Variación porcentual vs. día anterior | `(E(d) − E(d−1)) / E(d−1) × 100` | >0: la actividad crece |
| Repo más conectado | Repositorio con más usuarios distintos (grado) | `MATCH (u)-[]->(r) RETURN r, count(DISTINCT u)` | Proyecto que concentra comunidad |
| Prom. eventos/usuario | Intensidad de actividad | `E(d) / usuarios_únicos(d)` | Valores altos: usuarios muy activos o bots |
| Participación de pushes | Proporción de actividad de código | `pushes(d) / E(d) × 100` | Código real vs. actividad social |
| Hora pico | Hora con más eventos | `argmax_h Σ event_count` | Ventana de mayor carga |

**Flujo:** GH Archive (JSON/hora) → Airflow: extracción → limpieza → **MongoDB** (documento original) → **Cassandra** (agregados por hora/día) → **Neo4j** (Usuario→Repo) → KPIs.
""")
