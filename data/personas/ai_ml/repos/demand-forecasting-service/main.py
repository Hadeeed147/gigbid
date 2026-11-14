import mlflow
mlflow.log_metric('f1', f1)

def answer(q):
    docs = retriever.invoke(q)
    return llm.invoke(render(q, docs))  # cite sources

from airflow import DAG
from airflow.operators.python import PythonOperator
