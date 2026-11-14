# Excel module

from scipy import stats
t, p = stats.ttest_ind(control, treatment)

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import cross_val_score
