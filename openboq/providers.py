"""LLM providers: open-model APIs with automatic fallback and a response cache.

Set one or more API keys; OpenBoQ uses them in the order of NR_LLM_CHAIN (default: the order below, keys present only).
When a provider answers 429 / 5xx / times out, the request goes to the next one and the busy provider rests for a minute.

    $env:NVIDIA_API_KEY = "nvapi-..."  # free – https://build.nvidia.com
    $env:GROQ_API_KEY = "gsk_..."      # free, small – https://console.groq.com
    $env:NR_LLM_CHAIN = "nvidia,groq"               # optional order
    $env:GROQ_MODEL = "openai/gpt-oss-120b"         # optional per-provider model

Cache (NR_LLM_CACHE): "on" (default) stores every answer in data/llm_cache/ keyed by the request content, so the same
document never costs a second call; "replay" only reads the cache (offline demo, nothing is sent); "off" disables it.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

# name: (base_url, key env, default model, max input tokens per request on the free tier ~ for batching)
PRESETS: dict[str, tuple[str, str | None, str, int]] = {
    # free, ~40 req/min, strong open models (dev/evaluation use) – https://build.nvidia.com
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", "mistralai/mistral-large-4-1t-a52b", 30000),
    # free tier only 8K tokens/min -> small batches, prompts shrunk automatically – https://console.groq.com
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b", 6000),
    # EU (France), very cheap; works without a key at 2 req/min – https://endpoints.ai.cloud.ovh.net
    "ovh": ("https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "OVH_AI_ENDPOINTS_ACCESS_TOKEN", "gpt-oss-120b", 30000),
    # EU (Paris), 1M tokens free then ~€0.15/€0.60 per 1M – https://console.scaleway.com
    "scaleway": ("https://api.scaleway.ai/v1", "SCW_SECRET_KEY", "gpt-oss-120b", 30000),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openrouter/free", 20000),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest", 20000),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-flash-latest", 30000),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "gpt-oss-120b", 20000),
    "sambanova": ("https://api.sambanova.ai/v1", "SAMBANOVA_API_KEY", "gpt-oss-120b", 20000),
    "deepinfra": ("https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY", "Qwen/Qwen3-235B-A22B-Instruct-2507", 30000),
    "hf": ("https://router.huggingface.co/v1", "HF_TOKEN", "openai/gpt-oss-120b", 20000),
    "openai": ("", "OPENAI_API_KEY", "gpt-4o-mini", 30000),          # any OpenAI-compatible server: OPENAI_BASE_URL
    "ollama": ("http://localhost:11434/v1", None, "gemma4:12b", 12000),  # local: NR_LLM_CHAIN=ollama, OLLAMA_CONTEXT_LENGTH=16384
}
DEFAULT_ORDER = ["nvidia", "groq", "ovh", "scaleway", "deepinfra", "openrouter", "mistral", "gemini", "cerebras",
                 "sambanova", "hf", "openai"]
KEYLESS = {"ollama", "ovh"}          # usable without a key, but only when named in NR_LLM_CHAIN
CACHE_DIR = Path(os.environ.get("NR_LLM_CACHE_DIR", Path(__file__).resolve().parent.parent / "data" / "llm_cache"))


def chain() -> list[str]:
    """Providers to use, in order. Explicit NR_LLM_CHAIN wins; otherwise every preset whose key is set."""
    raw = os.environ.get("NR_LLM_CHAIN", "").strip()
    names = [n.strip().lower() for n in raw.split(",") if n.strip()] if raw else DEFAULT_ORDER
    out = []
    for n in names:
        if n not in PRESETS:
            continue
        key_env = PRESETS[n][1]
        if (key_env and os.environ.get(key_env)) or (n in KEYLESS and raw):
            out.append(n)
    return out


def model_for(name: str) -> str:
    return os.environ.get(f"{name.upper()}_MODEL") or (os.environ.get("NR_MODEL") if len(chain()) == 1 else None) \
        or PRESETS[name][2]


def token_budget() -> int:
    """Per-request input budget of the first provider – batches are sized to fit it. Fallback providers with a smaller
    budget are skipped for requests that would not fit (see ChainClient)."""
    c = chain()
    return int(os.environ.get(f"{c[0].upper()}_TOKEN_BUDGET", PRESETS[c[0]][3])) if c else 30000


def _est_tokens(kw: dict) -> int:
    return len(json.dumps([kw.get("system"), kw.get("messages")], ensure_ascii=False, default=str)) // 3


def describe() -> str:
    c = chain()
    if not c:
        return "none"
    parts = []
    for n in c:
        explicit = os.environ.get(f"{n.upper()}_MODEL")
        models = [explicit] if explicit else (LANE_MODELS.get(n) or [model_for(n)])
        parts.append(f"{n} ({', '.join(models)})")
    return " → ".join(parts)


# ---------------------------------------------------------------- cache

def _cache_key(kw: dict) -> str:
    body = {k: kw.get(k) for k in ("system", "messages", "tools", "tool_choice", "max_tokens")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:32]


def cache_mode() -> str:
    return os.environ.get("NR_LLM_CACHE", "on").lower()


def cache_get(kw: dict):
    p = CACHE_DIR / f"{_cache_key(kw)}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def cache_put(kw: dict, data: dict):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{_cache_key(kw)}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- chained client

class ProviderError(RuntimeError):
    pass


# Free tiers limit tokens per minute PER MODEL – so several models of one provider are separate "lanes".
LANE_MODELS = {"groq": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]}
LANE_TPM = {"groq": 8000}                 # tokens per minute per model on the free tier
SLOW = {"nvidia"}                          # free queue can take minutes: only used when the fast lanes are exhausted
OUT_RESERVE = 1500                         # expected answer tokens counted against the per-minute limit


class Lane:
    def __init__(self, provider: str, model: str, client):
        self.provider, self.model, self.client = provider, model, client
        self.tpm = int(os.environ.get(f"{provider.upper()}_TPM", LANE_TPM.get(provider, 10 ** 9)))
        self.slow = provider in SLOW
        self.used: list[tuple[float, int]] = []     # (time, tokens) in the last minute
        self.rest_until = 0.0
        self.dead_until = 0.0

    @property
    def name(self):
        return f"{self.provider}:{self.model}"

    def wait_for(self, need: int, now: float) -> float:
        """Seconds until this lane can take a request of `need` tokens."""
        if self.dead_until > now:
            return float("inf")
        self.used = [(t, n) for t, n in self.used if now - t < 60]
        w = max(0.0, self.rest_until - now)
        if need > self.tpm:
            return float("inf")
        total = sum(n for _, n in self.used)
        if total + need <= self.tpm:
            return w
        for t, n in self.used:                       # wait until enough old usage drops out of the window
            total -= n
            if total + need <= self.tpm:
                return max(w, 60 - (now - t) + 0.5)
        return max(w, 60.0)


def _lanes_for(names, clients) -> list[Lane]:
    lanes = []
    for n in names:
        explicit = os.environ.get(f"{n.upper()}_MODEL")
        models = [explicit] if explicit else (
            [m.strip() for m in os.environ.get(f"{n.upper()}_MODELS", "").split(",") if m.strip()] or
            LANE_MODELS.get(n) or [model_for(n)])
        lanes += [Lane(n, m, clients[n]) for m in models]
    return lanes


RUN_USAGE: dict[str, int] = {}     # which model answered how often in the current analysis (all client instances)


def reset_usage():
    RUN_USAGE.clear()


class ChainClient:
    """Anthropic-SDK-shaped client (client.messages.create) over several OpenAI-compatible providers/models.

    Requests are paced per lane (provider+model) against the free-tier tokens-per-minute limit, so they go out as fast
    as allowed instead of running into 429s; slow lanes (NVIDIA's free queue) are only used when every fast lane would
    make the request wait longer than NR_MAX_WAIT seconds or has failed."""

    _lock = threading.Lock()

    def __init__(self, names: list[str] | None = None):
        from .llm_checks import OpenAICompatClient
        self.names = names or chain()
        if not self.names:
            raise ProviderError("no LLM provider configured")
        self.clients = {}
        for n in self.names:
            base, key_env, _, _ = PRESETS[n]
            if n == "openai":
                base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            key = (os.environ.get(key_env, "") if key_env else "") or "none"
            self.clients[n] = OpenAICompatClient(base, key)
        self._lanes = None
        self.messages = self
        self.last_provider = ""
        self.max_wait = float(os.environ.get("NR_MAX_WAIT", "150"))   # NVIDIA's free queue: often 60–260 s
        self.used_counts = RUN_USAGE

    def most_used(self) -> str:
        return max(RUN_USAGE, key=RUN_USAGE.get) if RUN_USAGE else ""

    @property
    def lanes(self) -> list[Lane]:
        if self._lanes is None:
            self._lanes = _lanes_for(self.names, self.clients)
        return self._lanes

    def fast_lanes(self) -> int:
        return sum(1 for l in self.lanes if not l.slow) or 1

    def _pick(self, need: int, avoid: str = ""):
        with self._lock:
            now = time.time()
            fast = [(l.wait_for(need, now), l) for l in self.lanes if not l.slow]
            slow = [(l.wait_for(need, now), l) for l in self.lanes if l.slow]
            if avoid:
                # a second opinion must come from ANOTHER model: wait for one (the slow backup included) up to max_wait;
                # only when none is reachable at all does the same model answer – and the log says so
                others = [(w, l) for w, l in fast + slow if l.name != avoid and w <= self.max_wait]
                if others:                                # a slow lane also needs ~60–90 s to answer: count that
                    w, l = min(others, key=lambda x: x[0] + (75 if x[1].slow else 0))
                    l.used.append((now + w, need))
                    return l, w
            best = min(fast, key=lambda x: x[0], default=(float("inf"), None))
            if best[0] > self.max_wait:
                s = min(slow, key=lambda x: x[0], default=(float("inf"), None))
                if s[1] is not None and s[0] < best[0]:
                    best = s
            if best[1] is None or best[0] == float("inf"):
                return None, 0.0
            best[1].used.append((now + best[0], need))      # reserve the tokens now
            return best[1], best[0]

    def create(self, model=None, **kw):
        from .llm_checks import _Block, _Resp, _is_rate_limit, _wait_seconds
        avoid = kw.pop("_avoid", "")
        mode = cache_mode()
        if mode in ("on", "replay"):
            hit = cache_get(kw)
            if hit is not None and avoid and hit.get("provider") == avoid:
                hit = None                                # cached second opinion came from the same model: ask another
            if hit is not None:
                who = hit.get("provider", "")
                self.last_provider = f"cache ({who})" if who else "cache"
                if who:                                   # remember which model originally gave this cached answer
                    RUN_USAGE[who] = RUN_USAGE.get(who, 0) + 1
                return _Resp([_Block(b["type"], input=b.get("input"), text=b.get("text", "")) for b in hit["content"]])
            if mode == "replay":
                return _Resp([_Block("tool_use", input={"findings": [], "items": []})])
        need = _est_tokens(kw) + min(OUT_RESERVE, int(kw.get("max_tokens") or OUT_RESERVE))
        errors = []
        for _ in range(10):
            lane, wait = self._pick(need, avoid)
            if lane is None:
                break
            if wait > 0:
                time.sleep(wait)
            try:
                resp = lane.client.create(model=lane.model, **kw)
                self.last_provider = lane.name + (" (same model – no other reachable)" if avoid and lane.name == avoid else "")
                RUN_USAGE[lane.name] = RUN_USAGE.get(lane.name, 0) + 1
                if mode == "on":
                    cache_put(kw, {"provider": lane.name, "content": [{"type": b.type, "input": b.input, "text": b.text}
                                                                      for b in resp.content]})
                return resp
            except Exception as e:
                errors.append(f"{lane.name}: {type(e).__name__} {str(e)[:120]}")
                status = getattr(e, "status_code", None)
                with self._lock:
                    if _is_rate_limit(e):
                        lane.rest_until = time.time() + _wait_seconds(e, 1)
                    elif (status and status >= 500) or "timeout" in type(e).__name__.lower() \
                            or "connection" in type(e).__name__.lower():
                        lane.rest_until = time.time() + 30
                    else:                              # 400/404/410: model gone or request invalid for this lane
                        lane.dead_until = time.time() + 900
        raise ProviderError("all providers failed: " + " | ".join(errors[-4:]))


def check(names: list[str] | None = None) -> list[dict]:
    """Send one tiny JSON request to every configured provider and list its strong models (for `cli.py providers`)."""
    from .llm_checks import OpenAICompatClient
    out = []
    for n in names or chain():
        base, key_env, _, _ = PRESETS[n]
        if n == "openai":
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        key = (os.environ.get(key_env, "") if key_env else "") or "none"
        row = {"provider": n, "model": model_for(n), "ok": False, "seconds": None, "error": "", "models": []}
        c = OpenAICompatClient(base, key)
        try:
            ids = [m.id for m in c.client.models.list().data]
            keys = ("gpt-oss", "qwen3", "deepseek", "mistral", "gemma", "kimi", "glm", "llama")
            row["models"] = sorted(i for i in ids if any(k in i.lower() for k in keys))[:25]
        except Exception as e:
            row["error"] = f"models: {type(e).__name__} {str(e)[:80]}"
        t = time.time()
        try:
            r = c.create(model=model_for(n), max_tokens=200, system="Antworte nur mit JSON.",
                         tools=[{"input_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}],
                         messages=[{"role": "user", "content": 'Gib {"ok": true} zurück.'}])
            row["ok"] = bool(r.content and r.content[0].input)
            row["seconds"] = round(time.time() - t, 1)
        except Exception as e:
            row["error"] = f"{type(e).__name__} {str(e)[:160]}"
        out.append(row)
    return out
