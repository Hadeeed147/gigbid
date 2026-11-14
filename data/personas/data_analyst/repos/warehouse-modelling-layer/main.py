from statsmodels.stats.power import NormalIndPower
n = NormalIndPower().solve_power(0.1, alpha=0.05, power=0.8)

def extract_crm(since):
    return paginate('/contacts', since=since)

import pandas as pd
df = pd.read_csv('export.csv').dropna(subset=['order_id'])

# Python module

{{ config(materialized='incremental') }}
select * from {{ ref('stg_orders') }}
