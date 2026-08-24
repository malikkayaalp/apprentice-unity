"""Ollama chat client with tool-calling, metrics and a hardened agent loop."""
from __future__ import annotations
import json, re, time, urllib.request, urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable

from core import tokens as _tok

DEFAULT_MODEL = "gpt-oss:120b"

# Model is bitince RAM'de ne kadar kalsin. OLCULDU: 80B/Q4_K_XL modelin ~39 GB'i RAM'de durur
# (14.6 GB VRAM'e sigar), yani bu deger dogrudan bosta tutulan RAM demektir. Yeniden yukleme
# bedeli ~30-60 sn. Ayar dosyasindan okunur (eskiden burada 60m sabitti ve config yok sayiliyordu).
try:
    from core import config as _cfg
    KEEP_ALIVE = _cfg.env_or("APPRENTICE_KEEP_ALIVE", "ollama.keep_alive", "30m")
    # OLCULDU/DENETIM: burasi eskiden sabit "http://localhost:11434" idi; rag.py ve sunucu
    # on kontrolu ollama.url'i okudugu icin kullanici uzak bir sunucu tanimlayinca on kontrol
    # "model yuklu" der, ISCININ KENDISI localhost'a gidip ConnectionRefused ile duserdi.
    OLLAMA = (_cfg.env_or("OLLAMA_URL", "ollama.url", "http://localhost:11434")
              or "http://localhost:11434").rstrip("/")
except Exception:  # cekirdek disinda tek basina kullanim
    import os as _os
    KEEP_ALIVE = _os.environ.get("APPRENTICE_KEEP_ALIVE", "30m")
    OLLAMA = _os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")


@dataclass
class Metrics:
    wall: float = 0.0
    load_s: float = 0.0
    prompt_tokens: int = 0
    prompt_s: float = 0.0
    gen_tokens: int = 0
    gen_s: float = 0.0

    @property
    def pp_tps(self) -> float:
        return self.prompt_tokens / self.prompt_s if self.prompt_s else 0.0

    @property
    def tg_tps(self) -> float:
        return self.gen_tokens / self.gen_s if self.gen_s else 0.0

    def merge(self, o: "Metrics") -> None:
        self.wall += o.wall; self.load_s += o.load_s
        self.prompt_tokens += o.prompt_tokens; self.prompt_s += o.prompt_s
        self.gen_tokens += o.gen_tokens; self.gen_s += o.gen_s

    def as_dict(self) -> dict:
        return {"wall_s": round(self.wall, 2), "load_s": round(self.load_s, 2),
                "prompt_tokens": self.prompt_tokens, "pp_tps": round(self.pp_tps, 1),
                "gen_tokens": self.gen_tokens, "tg_tps": round(self.tg_tps, 1)}


@dataclass
class Turn:
    """One assistant response."""
    content: str = ""
    thinking: str = ""
    tool_calls: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    metrics: Metrics = field(default_factory=Metrics)
    error: str | None = None
    retries: int = 0
    truncated: bool = False
    est_prompt_tokens: int = 0
    done_reason: str = ""
    xml_recovered: int = 0

    @property
    def output_capped(self) -> bool:
        """The reply was cut off by num_predict rather than finishing."""
        return self.done_reason == "length"

    @property
    def empty(self) -> bool:
        """No text and no tool call - nothing to act on."""
        return not self.tool_calls and not (self.content or "").strip()


PARSE_ERROR_MARKERS = ("error parsing tool call", "invalid character",
                       "unexpected end of JSON input")

# Retry temperatures. The first entry keeps the requested (usually greedy) setting;
# a greedy retry would reproduce the identical malformed output, so later attempts
# must add entropy to escape the degenerate token path.
RETRY_TEMPS = (None, 0.35, 0.7)

EMPTY_NUDGE = ("Your last reply was empty: no text and no tool call. You spent the whole "
               "output budget on reasoning. Answer now, briefly and directly. If you "
               "still need data, make exactly one tool call and keep the reasoning short.")

NUDGE = ("Your last tool call could not be parsed. Emit exactly ONE tool call. "
         "Put nothing but strict JSON in the arguments: no commentary, no explanation, "
         "no trailing text, and no characters outside the JSON object. "
         "If several actions are needed, do only the first one now.")


# Which `think` values a model accepts, probed once and cached. Ollama rejects the
# wrong shape with HTTP 400, so this is cheap to determine and expensive to guess:
# mapping qwen3.8's "low" to False disables reasoning entirely instead of setting it
# to low effort.
_THINK_MODES: dict[str, str] = {}


def think_mode(model: str) -> str:
    """Return "levels" if the model takes low/medium/high, else "bool"."""
    if model in _THINK_MODES:
        return _THINK_MODES[model]
    body = {"model": model, "stream": False, "think": "low", "keep_alive": "10m",
            "messages": [{"role": "user", "content": "hi"}],
            "options": {"num_ctx": 2048, "num_predict": 1}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    mode = "levels"
    try:
        urllib.request.urlopen(req, timeout=600).read()
    except urllib.error.HTTPError as e:
        if e.code == 400 and b"think" in e.read():
            mode = "bool"
    except Exception:
        pass
    _THINK_MODES[model] = mode
    return mode


def normalize_think(model: str, think: str | bool | None) -> str | bool | None:
    """Reasoning control is not portable across model families.

    gpt-oss and qwen3.8 both take effort levels; older qwen builds and most other
    models take a boolean. Probe once, then translate.
    """
    if think is None:
        return None
    if think_mode(model) == "levels":
        # Booleans pass through untouched: Ollama accepts `false` on levels-mode models
        # too, and it means OFF (zero thinking tokens). An earlier version mapped
        # False -> "low", which silently re-enabled thinking - a gauntlet run labelled
        # think=OFF burned ~3900 thinking tokens per task because of it.
        if isinstance(think, bool):
            return think
        return think
    if isinstance(think, str):
        return {"low": False, "medium": True, "high": True}.get(think.lower(), True)
    return think


def chat(messages: list[dict], tools: list[dict] | None = None, *,
         model: str = DEFAULT_MODEL, think: str | bool = "low", num_ctx: int = 16384,
         temperature: float = 0.0, num_predict: int = 2048, keep_alive: str = KEEP_ALIVE,
         timeout: int = 3600, extra_options: dict | None = None,
         retries: int = 0) -> Turn:
    """One chat turn. With retries > 0, malformed-tool-call 500s are retried with
    added entropy (see RETRY_TEMPS)."""
    think = normalize_think(model, think)
    est = _tok.estimate(model, messages, tools)
    t_start = time.time()
    last: Turn | None = None
    attempts = min(retries + 1, len(RETRY_TEMPS))
    for attempt in range(attempts):
        temp = temperature if RETRY_TEMPS[attempt] is None else RETRY_TEMPS[attempt]
        turn = _chat_once(messages, tools, model=model, think=think, num_ctx=num_ctx,
                          temperature=temp, num_predict=num_predict,
                          keep_alive=keep_alive, timeout=timeout,
                          extra_options=extra_options)
        if not turn.error or not any(k in turn.error for k in PARSE_ERROR_MARKERS):
            if attempt:
                turn.retries = attempt
            turn.est_prompt_tokens = est
            turn.truncated = _tok.detect_truncation(
                turn.metrics.prompt_tokens, est, num_ctx)
            return turn
        turn.retries = attempt
        last = turn
    if last is not None:
        last.metrics.wall = time.time() - t_start
        return last
    return Turn(error="no attempt made")


def _chat_once(messages: list[dict], tools: list[dict] | None = None, *,
               model: str, think: str | bool, num_ctx: int, temperature: float,
               num_predict: int, keep_alive: str, timeout: int,
               extra_options: dict | None) -> Turn:
    body: dict[str, Any] = {
        "model": model, "messages": messages, "stream": False, "keep_alive": keep_alive,
        "options": {"num_ctx": num_ctx, "temperature": temperature,
                    "num_predict": num_predict, **(extra_options or {})},
    }
    if think is not None:
        body["think"] = think
    if tools:
        body["tools"] = tools
    payload = json.dumps(body).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/chat", payload,
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return Turn(error=f"HTTP {e.code}: {e.read()[:500].decode(errors='replace')}",
                    metrics=Metrics(wall=time.time() - t0))
    except Exception as e:  # noqa: BLE001 - surface transport failures as data
        return Turn(error=f"{type(e).__name__}: {e}", metrics=Metrics(wall=time.time() - t0))

    m = d.get("message", {})
    met = Metrics(wall=time.time() - t0, load_s=d.get("load_duration", 0) / 1e9,
                  prompt_tokens=d.get("prompt_eval_count", 0),
                  prompt_s=d.get("prompt_eval_duration", 0) / 1e9,
                  gen_tokens=d.get("eval_count", 0), gen_s=d.get("eval_duration", 0) / 1e9)
    content = m.get("content", "") or ""
    calls = m.get("tool_calls") or []
    xml_recovered = 0
    if not calls:
        calls, content = parse_xml_tool_calls(content)
        xml_recovered = len(calls)
    return Turn(content=content, thinking=m.get("thinking", "") or "",
                tool_calls=calls, raw=d, metrics=met,
                done_reason=d.get("done_reason", "") or "",
                xml_recovered=xml_recovered)


# Qwen3-Coder emits tool calls in its own XML-ish syntax:
#   <function=execute_code><parameter=action>execute</parameter>
#   <parameter=code>...</parameter></function>
# Ollama's packaging of qwen3-coder:30b-a3b advertises the `tools` capability but ships
# an empty chat template ({{ .Prompt }}), so nothing parses that syntax and the calls
# arrive as ordinary assistant text. The model is behaving correctly; the integration
# layer is not. Measured effect before this fallback existed: three of six eval tasks
# scored zero with "no tool calls made", which looked like a model failure and was not.
_XML_FN = re.compile(r"<function\s*=\s*([A-Za-z_][\w.-]*)\s*>(.*?)</function\s*>", re.S)
_XML_PARAM = re.compile(r"<parameter\s*=\s*([A-Za-z_][\w.-]*)\s*>(.*?)</parameter\s*>", re.S)


def parse_xml_tool_calls(content: str) -> tuple[list[dict], str]:
    """Recover XML-style tool calls from assistant text.

    Returns (tool_calls, leftover_text). Values stay strings; the schema guard coerces
    them to the declared types, which is the same path a normal JSON call takes.
    """
    if not content or "<function" not in content:
        return [], content
    calls = []
    for i, m in enumerate(_XML_FN.finditer(content)):
        args = {k: v.strip() for k, v in _XML_PARAM.findall(m.group(2))}
        calls.append({"id": "xml_%d" % i,
                      "function": {"index": i, "name": m.group(1), "arguments": args}})
    if not calls:
        return [], content
    leftover = _XML_FN.sub("", content)
    leftover = re.sub(r"</?tool_call>", "", leftover).strip()
    return calls, leftover


def tc_name(tc: dict) -> str:
    return (tc.get("function") or {}).get("name", "")


def tc_args(tc: dict) -> dict:
    a = (tc.get("function") or {}).get("arguments", {})
    if isinstance(a, str):
        try:
            return json.loads(a)
        except Exception:
            return {"__unparsed__": a}
    return a if isinstance(a, dict) else {"__nondict__": a}


def assistant_msg(turn: Turn, preserve_thinking: bool = False) -> dict:
    """Rebuild the assistant message for history.

    Thinking is dropped by default: replaying chain of thought costs prompt tokens on
    every later turn. Qwen3.8's model card recommends the opposite for agentic work
    (`preserve_thinking`), so it is an option rather than a hardcoded choice.
    """
    msg: dict[str, Any] = {"role": "assistant", "content": turn.content}
    if preserve_thinking and turn.thinking:
        msg["thinking"] = turn.thinking
    if turn.tool_calls:
        msg["tool_calls"] = turn.tool_calls
    return msg


def tool_msg(tc: dict, result: Any) -> dict:
    out = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return {"role": "tool", "tool_name": tc_name(tc), "content": out}


@dataclass
class LoopResult:
    turns: list[Turn] = field(default_factory=list)
    calls: list[tuple[str, dict]] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    retries: int = 0
    nudges: int = 0
    truncated_steps: int = 0
    empty_turns: int = 0
    xml_recovered: int = 0
    final_text: str = ""
    metrics: Metrics = field(default_factory=Metrics)
    stopped: str = "done"   # done | max_steps | error
    error: str | None = None


def run_agent(messages: list[dict], tools: list[dict],
              dispatch: Callable[[str, dict], Any], *, max_steps: int = 12,
              on_step: Callable[[int, Turn], None] | None = None,
              retries: int = 2, max_nudges: int = 2,
              preserve_thinking: bool = False, **kw) -> LoopResult:
    """Standard tool loop: model -> tool calls -> results -> model ... until text."""
    res = LoopResult(messages=list(messages))
    nudged = 0
    for step in range(max_steps):
        turn = chat(res.messages, tools, retries=retries, **kw)
        res.turns.append(turn)
        res.metrics.merge(turn.metrics)
        res.retries += turn.retries
        res.xml_recovered += turn.xml_recovered
        if turn.truncated:
            # Silent truncation means the model answered from a fragment. Surfacing it
            # is the whole point: an answer built on a cut prompt looks confident and
            # is not trustworthy.
            res.truncated_steps += 1
        if turn.error:
            # Observed root cause of these 500s: the model leaks commentary into the
            # tool-call argument channel, e.g.
            #   raw='We have data for three cities now. Need Izmir too.{"city":...
            # Re-sending the same context reproduces it at any temperature, so the fix
            # is to change the context: append a corrective instruction and continue.
            if (nudged < max_nudges and
                    any(k in turn.error for k in PARSE_ERROR_MARKERS)):
                nudged += 1
                res.nudges = nudged
                res.messages.append({"role": "user", "content": NUDGE})
                continue
            res.stopped, res.error = "error", turn.error
            return res
        if on_step:
            on_step(step, turn)
        if turn.empty:
            # An empty turn used to end the loop silently with no explanation. It happens
            # when reasoning consumes the whole num_predict budget (done_reason="length"),
            # so the visible content never gets generated. Say so and push for an answer.
            res.empty_turns += 1
            if nudged < max_nudges:
                nudged += 1
                res.nudges = nudged
                res.messages.append({"role": "user", "content": EMPTY_NUDGE})
                continue
            res.stopped = "empty_reply"
            res.error = ("model returned an empty reply (done_reason=%s); the output "
                         "budget was spent on reasoning" % (turn.done_reason or "?"))
            return res
        res.messages.append(assistant_msg(turn, preserve_thinking))
        if not turn.tool_calls:
            res.final_text = turn.content
            return res
        for tc in turn.tool_calls:
            name, args = tc_name(tc), tc_args(tc)
            res.calls.append((name, args))
            try:
                out = dispatch(name, args)
            except Exception as e:  # noqa: BLE001 - tool errors are fed back to the model
                out = {"error": f"{type(e).__name__}: {e}"}
            res.messages.append(tool_msg(tc, out))
    res.stopped = "max_steps"
    return res


def chat_stream(messages: list[dict], tools: list[dict] | None = None, *,
                model: str = DEFAULT_MODEL, think: str | bool = False,
                num_ctx: int = 16384, temperature: float = 0.0,
                num_predict: int = 2048, keep_alive: str = "60m",
                timeout: int = 3600, extra_options: dict | None = None,
                on_token=None, on_thinking=None) -> Turn:
    """_chat_once ile AYNI istek govdesi, tek farki stream=True.

    Neden ayri bir fonksiyon: _chat_once, Cloner A/B dahil daha once kosmus her olcumun
    yoludur. Ona dokunmak eski sonuclarla yeni sonuclari kiyaslanamaz yapardi. Bu yol
    yalnizca canli izleme isteyen testler icin kullanilir; uretim ayni (Ollama akisi
    parcali teslim eder, uretilen metni degistirmez).

    on_token(parca, toplam_metin) her yeni parcada cagrilir. Geri cagrimdaki hata
    uretimi durdurmaz - canli goruntu ikincildir, olcum degildir.
    """
    body: dict[str, Any] = {
        "model": model, "messages": messages, "stream": True, "keep_alive": keep_alive,
        "options": {"num_ctx": num_ctx, "temperature": temperature,
                    "num_predict": num_predict, **(extra_options or {})},
    }
    if think is not None:
        body["think"] = think
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(f"{OLLAMA}/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    parts: list[str] = []
    thinking: list[str] = []
    calls: list = []
    last: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                m = d.get("message") or {}
                piece = m.get("content") or ""
                if piece:
                    parts.append(piece)
                    if on_token is not None:
                        try:
                            on_token(piece, "".join(parts))
                        except Exception:
                            pass
                if m.get("thinking"):
                    thinking.append(m["thinking"])
                    # Dusunme fazi da ILERLEME'dir. Bildirilmezse uzun bir dusunme
                    # sirasinda akis olu gorunur; gozetleyici bunu takilma sanip
                    # kosuyu keser (yasandi: 5 dk dusunen model olduruldu).
                    if on_thinking is not None:
                        try:
                            on_thinking(m["thinking"])
                        except Exception:
                            pass
                if m.get("tool_calls"):
                    calls.extend(m["tool_calls"])
                if d.get("done"):
                    last = d
    except urllib.error.HTTPError as e:
        return Turn(error=f"HTTP {e.code}: {e.read()[:500].decode(errors='replace')}",
                    metrics=Metrics(wall=time.time() - t0))
    except Exception as e:  # noqa: BLE001
        return Turn(error=f"{type(e).__name__}: {e}",
                    metrics=Metrics(wall=time.time() - t0))

    met = Metrics(wall=time.time() - t0, load_s=last.get("load_duration", 0) / 1e9,
                  prompt_tokens=last.get("prompt_eval_count", 0),
                  prompt_s=last.get("prompt_eval_duration", 0) / 1e9,
                  gen_tokens=last.get("eval_count", 0),
                  gen_s=last.get("eval_duration", 0) / 1e9)
    content = "".join(parts)
    xml_recovered = 0
    if not calls:
        calls, content = parse_xml_tool_calls(content)
        xml_recovered = len(calls)
    return Turn(content=content, thinking="".join(thinking), tool_calls=calls,
                raw=last, metrics=met, done_reason=last.get("done_reason", "") or "",
                xml_recovered=xml_recovered)
