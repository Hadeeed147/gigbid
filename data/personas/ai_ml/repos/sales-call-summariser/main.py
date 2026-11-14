from langchain_core.prompts import ChatPromptTemplate
prompt = ChatPromptTemplate.from_messages([('system', '{rules}'), ('user', '{q}')])

from qdrant_client import QdrantClient
client = QdrantClient(url='http://qdrant:6333')

# Python module

# LLM module

import cv2
from ultralytics import YOLO
model = YOLO('yolov8n.pt')
