import os

os.environ.setdefault("GIGSIM_ERROR_RATE", "0")
os.environ.setdefault("GIGBID_SECRETS_BACKEND", "file")
os.environ.setdefault("GIGBID_VERIFY_GRADER", "ce")
os.environ["MCP_BEARER_TOKEN"] = ""   # in-memory sessions have no HTTP auth layer
os.environ["LANGSMITH_TRACING"] = "false"
