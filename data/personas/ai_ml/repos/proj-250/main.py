def answer(q):
    docs = retriever.invoke(q)
    return llm.invoke(render(q, docs))  # cite sources

import cv2
from ultralytics import YOLO
model = YOLO('yolov8n.pt')

from qdrant_client import QdrantClient
client = QdrantClient(url='http://qdrant:6333')
