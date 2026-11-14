"""LLM access for every node: model chosen by config, structured output,
token + cost accounting, timeouts, bounded retries and a fallback model.

All providers are OpenAI-compatible (Groq, Ollama, OpenRouter, vLLM), so one
client class covers them; no model name appears anywhere else in the code.
Set GIGBID_LLM_CACHE=1 to cache responses on disk (evals: reproducible and
gentle on free-tier quotas).
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from common.config import ROOT, cfg, env, fallback_spec, load_config, model_spec

T = TypeVar("T", bound=BaseModel)
CACHE_DIR = ROOT / "data" / "processed" / "llm_cache"


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    latency_s: float = 0.0
    by_node: dict[str, dict] = field(default_factory=dict)

    def add(self, node: str, model: str, it: int, ot: int, usd: float, latency: float) -> None:
        self.calls += 1
        self.input_tokens += it
        self.output_tokens += ot
        self.usd += usd
        self.latency_s += latency
        n = self.by_node.setdefault(node, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0,
                                           "latency_s": 0.0, "model": model})
        n["calls"] += 1
        n["input_tokens"] += it
        n["output_tokens"] += ot
        n["usd"] += usd
        n["latency_s"] += latency

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# Per-run usage accumulator (one per graph thread / eval item).
current_usage: contextvars.ContextVar[Usage | None] = contextvars.ContextVar("current_usage", default=None)


class LLMError(RuntimeError):
    pass


def _price(provider: str, model: str) -> tuple[float, float]:
    prices = load_config()["providers"][provider].get("prices", {})
    return tuple(prices.get(model, (0.0, 0.0)))  # type: ignore[return-value]


def _client(spec: dict):
    from langchain_openai import ChatOpenAI
    prov = load_config()["providers"][spec["provider"]]
    key = env(prov["api_key_env"]) or ("ollama" if spec["provider"] == "ollama" else None)
    if not key:
        raise LLMError(f"missing API key env var {prov['api_key_env']} for provider {spec['provider']}")
    return ChatOpenAI(model=spec["model"], base_url=prov["base_url"], api_key=key,
                      temperature=spec.get("temperature", 0.0), timeout=cfg("node_runtime.timeout_s", 60),
                      max_retries=0)


def _cache_key(spec: dict, messages: list[dict], schema: str) -> Path:
    h = hashlib.sha256(json.dumps([spec["provider"], spec["model"], spec.get("temperature"), messages, schema],
                                  sort_keys=True).encode()).hexdigest()[:32]
    return CACHE_DIR / f"{h}.json"


def _extract_json(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON object in model output")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def _invoke(spec: dict, node: str, messages: list[dict], schema: type[BaseModel] | None) -> tuple[str, int, int]:
    client = _client(spec)
    kwargs: dict[str, Any] = {}
    if schema is not None:
        kwargs["response_format"] = {"type": "json_object"}
    lc_msgs = [(m["role"], m["content"]) for m in messages]
    resp = client.invoke(lc_msgs, **kwargs)
    meta = resp.usage_metadata or {}
    return str(resp.content), int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0))


def chat(node: str, messages: list[dict], schema: type[T] | None = None, *, profile: str | None = None,
         spec_override: dict | None = None) -> T | str:
    """Call the model configured for `node`. Returns a validated `schema` instance or text."""
    from common import fake_llm
    if fake_llm.enabled():
        if (u := current_usage.get()) is not None:
            u.add(node, "fake", 0, 0, 0.0, 0.0)
        return fake_llm.respond(node, messages, schema)
    spec = spec_override or model_spec(node, profile)
    if schema is not None:
        messages = messages[:-1] + [{
            "role": messages[-1]["role"],
            "content": messages[-1]["content"] + "\n\nReturn ONLY a JSON object matching this JSON schema:\n"
            + json.dumps(schema.model_json_schema())}]
    use_cache = os.environ.get("GIGBID_LLM_CACHE") == "1"
    ck = _cache_key(spec, messages, schema.__name__ if schema else "")
    retries = cfg("node_runtime.max_retries", 2)
    backoff = cfg("node_runtime.backoff_base_s", 1.5)
    specs = [spec] + ([fallback_spec(profile)] if spec.get("tier", "small") == "small" else [])
    last_err: Exception | None = None
    for sp in specs:
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                if use_cache and ck.exists():
                    cached = json.loads(ck.read_text(encoding="utf-8"))
                    text, it, ot = cached["text"], cached["it"], cached["ot"]
                    latency = cached.get("latency", 0.0)
                else:
                    text, it, ot = _invoke(sp, node, messages, schema)
                    latency = time.time() - t0
                    if use_cache:
                        CACHE_DIR.mkdir(parents=True, exist_ok=True)
                        ck.write_text(json.dumps({"text": text, "it": it, "ot": ot, "latency": latency}),
                                      encoding="utf-8")
                pin, pout = _price(sp["provider"], sp["model"])
                usd = (it * pin + ot * pout) / 1e6
                if (u := current_usage.get()) is not None:
                    u.add(node, sp["model"], it, ot, usd, latency)
                if schema is None:
                    return text
                return schema.model_validate(_extract_json(text))
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                last_err = e
                messages = messages + [{"role": "user", "content": f"Your last output was invalid ({str(e)[:200]}). "
                                                                   "Return only valid JSON for the schema."}]
            except LLMError:
                raise
            except Exception as e:  # network, 429, 5xx
                last_err = e
                msg = str(e)
                wait = backoff ** (attempt + 1)
                m = re.search(r"try again in ([\d.]+)s", msg)
                if m:
                    wait = min(30.0, float(m.group(1)) + 0.5)
                time.sleep(wait)
    raise LLMError(f"{node}: all attempts failed: {last_err}")
