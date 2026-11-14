from scipy import stats
t, p = stats.ttest_ind(control, treatment)

# Python module

from statsmodels.stats.power import NormalIndPower
n = NormalIndPower().solve_power(0.1, alpha=0.05, power=0.8)

from prophet import Prophet
m = Prophet(weekly_seasonality=True).fit(history)

def extract_crm(since):
    return paginate('/contacts', since=since)
