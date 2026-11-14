# Excel module

import pandas as pd
df = pd.read_csv('export.csv').dropna(subset=['order_id'])

SELECT region, SUM(revenue) OVER (PARTITION BY region ORDER BY month) AS running
FROM sales;
