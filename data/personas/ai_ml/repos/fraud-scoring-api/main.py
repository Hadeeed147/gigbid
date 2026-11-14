from transformers import AutoModel, AutoTokenizer
tok = AutoTokenizer.from_pretrained('bert-base-uncased')

import cv2
from ultralytics import YOLO
model = YOLO('yolov8n.pt')

import mlflow
mlflow.log_metric('f1', f1)

from prophet import Prophet
m = Prophet(weekly_seasonality=True).fit(history)

# LLM module
