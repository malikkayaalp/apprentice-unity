"""Per-model token budgeting, because Ollama truncates silently.

Measured on Ollama 0.32.14: when a prompt exceeds num_ctx, the request does NOT fail.
The prompt is cut down (to roughly num_ctx/2 in observation) and the model answers from
the fragment with full confidence. On the 900-line scene dump, qwen3.8 reported
prompt_eval_count=16386 against num_ctx=32768 and produced an answer about a completely
different sector.

There is no /api/tokenize in this version, so token counts are estimated from a
calibrated chars-per-token ratio measured per model. The ratio matters: for identical
content gpt-oss:120b reported 590 prompt tokens where qwen3.8 reported 1199, so a
context budget computed for one model is wrong for the other by a factor of two.
"""
from __future__ import annotations
import json, os, urllib.request
from dataclasses import dataclass

OLLAMA = "http://localhost:11434"
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "reports", "token_ratios.json")

# Fallbacks used before a model has been calibrated.
DEFAULT_RATIO = 3.6

_PROBE = ("Sahnedeki nesnelerin listesi asagidadir. /World/Sector_03/Prop_128 "
          "mesh=SM_prop_128 lod=2 tris=4821 material=M_Stone. Bu satir hem Turkce "
          "hem de teknik icerik barindirir, ki tokenizer farklari ortaya ciksin. ")


def _load() -> dict:
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict) -> None:
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def _probe_tokens(model: str, text: str, num_ctx: int) -> int:
    body = {"model": model, "stream": False, "think": False, "keep_alive": "10m",
            "messages": [{"role": "user", "content": text}],
            "options": {"num_ctx": num_ctx, "temperature": 0.0, "num_predict": 1}}
    req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1200) as r:
        return json.loads(r.read()).get("prompt_eval_count", 0)


def calibrate(model: str, *, force: bool = False, num_ctx: int = 8192) -> float:
    """Measure chars per prompt token for a model. Cached on disk."""
    cache = _load()
    if not force and model in cache:
        return cache[model]["chars_per_token"]
    small = _PROBE * 4
    large = _PROBE * 40
    n_small = _probe_tokens(model, small, num_ctx)
    n_large = _probe_tokens(model, large, num_ctx)
    # Difference cancels the fixed template overhead.
    d_chars, d_tokens = len(large) - len(small), n_large - n_small
    ratio = (d_chars / d_tokens) if d_tokens > 0 else DEFAULT_RATIO
    overhead = max(0, n_small - int(len(small) / ratio))
    cache[model] = {"chars_per_token": round(ratio, 3), "template_overhead": overhead,
                    "probe_small": n_small, "probe_large": n_large}
    _save(cache)
    return ratio


def ratio_for(model: str) -> float:
    return _load().get(model, {}).get("chars_per_token", DEFAULT_RATIO)


# Tool schemas are repetitive JSON and tokenize BETTER than prose, not worse: measured
# on a live 48-tool MCP tool block, 62 082 chars became 15 676 qwen3.8 tokens, or
# 3.96 chars per token against 2.81 for prose. Treating them as dense data over-estimated
# the block by more than three times.
TOOL_RATIOS = {"qwen3.8": 3.90, "qwen3.8:latest": 3.90}
DEFAULT_TOOL_RATIO = 3.40


def tool_ratio_for(model: str) -> float:
    cached = _load().get(model, {}).get("tool_chars_per_token")
    if cached:
        return cached
    return TOOL_RATIOS.get(model, DEFAULT_TOOL_RATIO)


def overhead_for(model: str) -> int:
    return _load().get(model, {}).get("template_overhead", 40)


def density_factor(text: str) -> float:
    """How much worse than prose this text tokenizes.

    A calibration ratio measured on prose badly underestimates machine data. Prose runs
    near 2.8-3.2 chars per token; a line like
        /World/Sector_07/Prop_311  mesh=SM_prop_311  lod=0  tris=48213
    is closer to 1.5, because digits, slashes and underscores each cost a token. Missing
    this is what let a truncated 900-line scene dump slip through undetected.
    """
    if not text:
        return 1.0
    sample = text[:20000]
    dense = sum(1 for c in sample if c.isdigit() or c in "/_=:.,[]{}()<>|-\\\"'")
    frac = dense / len(sample)
    # Calibrated against real counts for the 900-line scene dump: 68 345 chars came back
    # as 29 229 tokens on gpt-oss and 36 804 on qwen3.8, i.e. about 1.35x worse than
    # prose. An earlier 2.6x cap over-estimated by roughly three times.
    return 1.0 + 0.4 * min(frac, 0.5) / 0.5      # 1.0 for prose, up to 1.4 for data


def estimate(model: str, messages: list[dict], tools: list[dict] | None = None) -> int:
    """Estimated prompt tokens for this request, including the tool block.

    Intentionally biased high: underestimating causes silent truncation, while
    overestimating only costs an unnecessary compaction.
    """
    base = ratio_for(model)
    total = 0.0
    for m in messages:
        text = str(m.get("content") or "")
        if text:
            total += len(text) / (base / density_factor(text))
        if m.get("tool_calls"):
            tc = json.dumps(m["tool_calls"], ensure_ascii=False)
            total += len(tc) / (base / density_factor(tc))
        total += 24
    if tools:
        total += len(json.dumps(tools, ensure_ascii=False)) / tool_ratio_for(model)
    return int(total) + overhead_for(model)


@dataclass
class Fit:
    estimated: int
    limit: int
    reserve: int

    @property
    def fits(self) -> bool:
        return self.estimated + self.reserve <= self.limit

    @property
    def headroom(self) -> int:
        return self.limit - self.reserve - self.estimated

    def __str__(self) -> str:
        return ("est=%d limit=%d reserve=%d headroom=%d %s"
                % (self.estimated, self.limit, self.reserve, self.headroom,
                   "OK" if self.fits else "OVERFLOW"))


def check_fit(model: str, messages: list[dict], tools: list[dict] | None,
              num_ctx: int, reserve: int = 1024) -> Fit:
    """Would this request overflow num_ctx? reserve leaves room for the reply."""
    return Fit(estimate(model, messages, tools), num_ctx, reserve)


def detect_truncation(reported_prompt_tokens: int, estimated: int, num_ctx: int) -> bool:
    """Post-hoc check: did Ollama silently cut the prompt?

    Two independent signatures:

    1. Fingerprint. Ollama cuts an oversized prompt to almost exactly num_ctx/2.
       Measured: num_ctx=32768 with an oversized prompt reported 16386, and 16384 is
       exactly half. A genuine prompt landing within a few tokens of exactly half the
       window is very unlikely, so this fires on its own - it does not depend on the
       character-based estimate being accurate, which is what let the first version of
       this check miss a real truncation.

    2. Estimate mismatch. The estimate exceeded the window, yet far fewer tokens were
       actually processed.
    """
    if reported_prompt_tokens <= 0:
        return False
    if abs(reported_prompt_tokens - num_ctx / 2) <= 4:
        return True
    return estimated > num_ctx and reported_prompt_tokens < estimated * 0.85
