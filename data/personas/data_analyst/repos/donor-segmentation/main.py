from scipy import stats
t, p = stats.ttest_ind(control, treatment)

# Excel module

from statsmodels.stats.power import NormalIndPower
n = NormalIndPower().solve_power(0.1, alpha=0.05, power=0.8)

-- snowflake
CREATE WAREHOUSE analytics_wh WITH WAREHOUSE_SIZE='XSMALL';

from prophet import Prophet
m = Prophet(weekly_seasonality=True).fit(history)
