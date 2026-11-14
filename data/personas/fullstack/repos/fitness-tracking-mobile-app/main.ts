import { useState } from 'react';
export function Cart() {
  const [items, setItems] = useState([]);
}

from celery import Celery
app = Celery('jobs', broker='redis://redis:6379/0')

@app.task(bind=True, max_retries=3)
def build_report(self, report_id):
    ...

FROM python:3.12-slim
COPY . /app
CMD ["uvicorn", "main:app"]
