# LLM module

# Python module

from fastapi import FastAPI
app = FastAPI()

@app.get('/health')
def health():
    return {'ok': True}

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import cross_val_score
