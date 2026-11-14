"""Load agent/config.yaml with ${VAR:-default} environment expansion.

Single source of truth for models, budgets, thresholds and rule files.
Nothing else in the codebase hard-codes a model name or a threshold.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "agent" / "config.yaml"
_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key.strip(), value)


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            return os.environ.get(m.group(1)) or (m.group(2) or "")
        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    _load_dotenv()
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return _expand(raw)


def cfg(path: str, default: Any = None) -> Any:
    """Dotted lookup: cfg('decision.bid_min_fit')."""
    node: Any = load_config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def env(name: str, default: str | None = None) -> str | None:
    _load_dotenv()
    return os.environ.get(name, default)


def model_spec(node: str, profile: str | None = None) -> dict[str, Any]:
    """Resolve which provider/model a node uses under the active profile."""
    conf = load_config()
    profile = profile or os.environ.get("GIGBID_PROFILE") or conf["active_profile"]
    tier = conf["node_models"].get(node, "small")
    spec = dict(conf["profiles"][profile][tier])
    spec["tier"] = tier
    spec["profile"] = profile
    return spec


def fallback_spec(profile: str | None = None) -> dict[str, Any]:
    conf = load_config()
    profile = profile or os.environ.get("GIGBID_PROFILE") or conf["active_profile"]
    return dict(conf["profiles"][profile]["fallback"])


def resolve_path(rel: str) -> Path:
    return ROOT / rel
