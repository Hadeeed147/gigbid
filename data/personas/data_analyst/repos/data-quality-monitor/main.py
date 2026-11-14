# Python module

# Tableau module

from prophet import Prophet
m = Prophet(weekly_seasonality=True).fit(history)

CREATE INDEX CONCURRENTLY idx_orders_created ON orders (created_at);
