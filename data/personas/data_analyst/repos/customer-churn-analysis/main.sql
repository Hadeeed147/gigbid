# Looker module

SELECT region, SUM(revenue) OVER (PARTITION BY region ORDER BY month) AS running
FROM sales;

# Power BI module
