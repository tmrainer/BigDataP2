"""
DAG: github_events_pipeline
Pipeline multimodelo (MongoDB Atlas + Cassandra + Neo4j AuraDB) sobre GitHub Events.

Etapas (requisito del proyecto):
  1. extract_data          -> descarga el archivo horario de GH Archive
  2. validate_and_clean    -> valida, deduplica, recorta payload
  3. load_mongodb          -> documentos originales (semiestructurados)
  4. transform_load_cassandra -> agregados por hora/día (series temporales)
  5. build_graph_neo4j     -> relaciones Usuario -> Repo
  6. generate_kpis         -> indicadores -> Cassandra kpis_by_date

Programación: cada hora. Cada corrida procesa la hora `data_interval_start - lag`,
lo que implementa la actualización incremental del dataset.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

log = logging.getLogger(__name__)

default_args = {
    "owner": "grupo-bigdata",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
}


# ---------------------------------------------------------------- callables
def _extract(**ctx):
    from extract import extract, hour_to_process
    # data_interval_start = inicio de la hora programada; restamos el lag de publicación de GH Archive
    hour = hour_to_process(reference=ctx["data_interval_start"])
    log.info("Hora a procesar: %s", hour)
    return extract(hour)


def _clean(ti, **_):
    from clean import clean
    return clean(ti.xcom_pull(task_ids="extract_data"))


def _mongo(ti, **_):
    from load_mongo import load_mongo
    return load_mongo(ti.xcom_pull(task_ids="validate_and_clean"))


def _cassandra(ti, **_):
    from load_cassandra import load_cassandra
    return load_cassandra(ti.xcom_pull(task_ids="load_mongodb"))


def _neo4j(ti, **_):
    from load_neo4j import load_neo4j
    return load_neo4j(ti.xcom_pull(task_ids="transform_load_cassandra"))


def _kpis(ti, **_):
    from kpis import generate_kpis
    return generate_kpis(ti.xcom_pull(task_ids="build_graph_neo4j"))


# ---------------------------------------------------------------- DAG
with DAG(
    dag_id="github_events_pipeline",
    description="ETL horario GH Archive -> MongoDB Atlas / Cassandra / Neo4j AuraDB + KPIs",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["bigdata", "utec", "multimodelo"],
    doc_md=__doc__,
) as dag:

    t1 = PythonOperator(task_id="extract_data", python_callable=_extract)
    t2 = PythonOperator(task_id="validate_and_clean", python_callable=_clean)
    t3 = PythonOperator(task_id="load_mongodb", python_callable=_mongo)
    t4 = PythonOperator(task_id="transform_load_cassandra", python_callable=_cassandra)
    t5 = PythonOperator(task_id="build_graph_neo4j", python_callable=_neo4j)
    t6 = PythonOperator(task_id="generate_kpis", python_callable=_kpis)

    t1 >> t2 >> t3 >> t4 >> t5 >> t6
