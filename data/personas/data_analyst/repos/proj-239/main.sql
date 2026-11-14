from scipy import stats
t, p = stats.ttest_ind(control, treatment)

SELECT region, SUM(revenue) OVER (PARTITION BY region ORDER BY month) AS running
FROM sales;

from statsmodels.stats.power import NormalIndPower
n = NormalIndPower().solve_power(0.1, alpha=0.05, power=0.8)

# Looker module
