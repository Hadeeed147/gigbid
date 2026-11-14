from langchain_core.prompts import ChatPromptTemplate
prompt = ChatPromptTemplate.from_messages([('system', '{rules}'), ('user', '{q}')])

import torch
from torch import nn

class Classifier(nn.Module):
    def __init__(self, n):
        super().__init__()
        self.head = nn.Linear(768, n)

# NLP module
