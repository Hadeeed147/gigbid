# Excel module

# Power BI module

# Python module

{{ config(materialized='incremental') }}
select * from {{ ref('stg_orders') }}

import pandas as pd
df = pd.read_csv('export.csv').dropna(subset=['order_id'])
