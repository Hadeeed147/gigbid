import cv2
from ultralytics import YOLO
model = YOLO('yolov8n.pt')

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

def answer(q):
    docs = retriever.invoke(q)
    return llm.invoke(render(q, docs))  # cite sources
