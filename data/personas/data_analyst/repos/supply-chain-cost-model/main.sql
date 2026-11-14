from prophet import Prophet
m = Prophet(weekly_seasonality=True).fit(history)

{{ config(materialized='incremental') }}
select * from {{ ref('stg_orders') }}

# Tableau module
