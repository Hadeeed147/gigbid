from prophet import Prophet
m = Prophet(weekly_seasonality=True).fit(history)

from fastapi import FastAPI
app = FastAPI()

@app.get('/health')
def health():
    return {'ok': True}

# Python module
