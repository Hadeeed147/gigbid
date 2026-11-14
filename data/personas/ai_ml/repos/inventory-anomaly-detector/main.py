import torch
from torch import nn

class Classifier(nn.Module):
    def __init__(self, n):
        super().__init__()
        self.head = nn.Linear(768, n)

import mlflow
mlflow.log_metric('f1', f1)

from fastapi import FastAPI
app = FastAPI()

@app.get('/health')
def health():
    return {'ok': True}

def answer(q):
    docs = retriever.invoke(q)
    return llm.invoke(render(q, docs))  # cite sources
