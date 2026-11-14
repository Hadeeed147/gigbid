# Google Analytics module

import pandas as pd
df = pd.read_csv('export.csv').dropna(subset=['order_id'])

# Excel module

from scipy import stats
t, p = stats.ttest_ind(control, treatment)
