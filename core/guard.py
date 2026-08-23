"""Argument validation and repair for tool calls.

Measured failure modes of gpt-oss:120b on this box, in order of frequency:

  1. enum drift        unit="metric" instead of "celsius"; freq="WEEKLY" instead of
                       "weekly"; unit="C". Casing and synonyms, almost never a truly
                       invented value.
  2. shape drift       {"x":1,"y":2,"z":3} where an array [1,2,3] was declared;
                       a bare scalar where an array was declared; "45" for an integer.
  3. semantic drift    ignoring an explicit user constraint under a long tool list
                       (priority "medium" when the user said critical). Not repairable
                       here - only detectable by the caller.

Repairing 1 and 2 in the harness is far cheaper than a round trip: a retry costs a full
prompt re-evaluation, which on this machine is tens of seconds.

Anything that cannot be repaired is turned into a precise, actionable error message for
the model rather than a Python exception.
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field
from typing import Any

# enum synonyms seen in practice, keyed by the canonical value
SYNONYMS: dict[str, tuple[str, ...]] = {
    "celsius": ("metric", "c", "centigrade", "°c", "santigrat", "selsiyus"),
    "fahrenheit": ("imperial", "f", "°f"),
}


@dataclass
class GuardResult:
    args: dict
    repairs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _num(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip().replace(",", ".")
        m = re.fullmatch(r"[-+]?\d+", s)
        if m:
            return int(s)
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _match_enum(value: Any, options: list) -> Any | None:
    """Case-insensitive, then synonym, then unique-prefix match."""
    if value in options:
        return value
    sv = str(value).strip().lower()
    for o in options:
        if str(o).strip().lower() == sv:
            return o
    for o in options:
        if sv in SYNONYMS.get(str(o).strip().lower(), ()):
            return o
    hits = [o for o in options if str(o).strip().lower().startswith(sv)] if sv else []
    if len(hits) == 1:
        return hits[0]
    return None


_XYZ = ("x", "y", "z", "w")


def _coerce(value: Any, spec: dict, path: str, out: GuardResult) -> Any:
    t = spec.get("type")
    enum = spec.get("enum")

    if enum:
        fixed = _match_enum(value, enum)
        if fixed is None:
            out.errors.append("%s=%s is not allowed. Valid values: %s"
                              % (path, json.dumps(value, ensure_ascii=False),
                                 ", ".join(json.dumps(e) for e in enum)))
            return value
        if fixed != value:
            out.repairs.append("%s %s -> %s" % (path, json.dumps(value, ensure_ascii=False),
                                                json.dumps(fixed, ensure_ascii=False)))
        return fixed

    if t == "array":
        item = spec.get("items") or {}
        if isinstance(value, dict):
            keys = [k for k in _XYZ if k in value]
            if keys:                       # {"x":1,"y":2,"z":3} -> [1,2,3]
                value = [value[k] for k in keys]
                out.repairs.append(path + " object -> array")
            else:
                out.errors.append("%s must be an array, got an object" % path)
                return value
        elif isinstance(value, str):
            try:                            # "[1,2,3]" -> [1,2,3]
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    value = parsed
                    out.repairs.append(path + " json-string -> array")
            except Exception:
                parts = [p for p in re.split(r"[,\s]+", value.strip("[]() ")) if p]
                if len(parts) > 1:
                    value = parts
                    out.repairs.append(path + " delimited-string -> array")
                else:
                    value = [value]
                    out.repairs.append(path + " scalar -> array")
        elif not isinstance(value, list):
            value = [value]
            out.repairs.append(path + " scalar -> array")
        return [_coerce(v, item, "%s[%d]" % (path, i), out) for i, v in enumerate(value)]

    if t == "object":
        if isinstance(value, str):
            try:
                value = json.loads(value)
                out.repairs.append(path + " json-string -> object")
            except Exception:
                out.errors.append(path + " must be an object")
                return value
        if not isinstance(value, dict):
            out.errors.append("%s must be an object, got %s" % (path, type(value).__name__))
            return value
        props = spec.get("properties") or {}
        fixed = {}
        for k, v in value.items():
            fixed[k] = _coerce(v, props[k], path + "." + k, out) if k in props else v
        for req in spec.get("required") or []:
            if req not in fixed:
                out.errors.append("%s.%s is required but missing" % (path, req))
        return fixed

    if t in ("integer", "number"):
        n = _num(value)
        if n is None:
            out.errors.append("%s must be a %s, got %s"
                              % (path, t, json.dumps(value, ensure_ascii=False)))
            return value
        if t == "integer" and isinstance(n, float):
            if n.is_integer():
                n = int(n)
            else:
                out.errors.append("%s must be an integer, got %s" % (path, n))
                return value
        if n != value:
            out.repairs.append("%s %s -> %s" % (path, json.dumps(value, ensure_ascii=False), n))
        return n

    if t == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "yes", "1", "evet"):
            out.repairs.append(path + " -> true")
            return True
        if s in ("false", "no", "0", "hayir", "hayır"):
            out.repairs.append(path + " -> false")
            return False
        out.errors.append(path + " must be true or false")
        return value

    if t == "string" and not isinstance(value, str):
        if value is None:
            return ""
        out.repairs.append(path + " -> string")
        return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) \
            else str(value)

    return value


def guard(schema: dict, args: dict) -> GuardResult:
    """Validate and repair one tool call's arguments against its parameter schema."""
    out = GuardResult(args=dict(args or {}))
    params = (schema.get("function") or schema).get("parameters") or {}
    props = params.get("properties") or {}
    fixed: dict[str, Any] = {}
    unknown: list[str] = []
    for k, v in (args or {}).items():
        if k in props:
            fixed[k] = _coerce(v, props[k], k, out)
        else:
            unknown.append(k)
    for req in params.get("required") or []:
        if req not in fixed:
            out.errors.append("required parameter %r is missing" % req)
    if unknown:
        out.repairs.append("dropped unknown parameters: " + ", ".join(sorted(unknown)))
    out.args = fixed
    return out


def guarded_dispatch(tools: list[dict], dispatch, *, log: list | None = None,
                     strict: bool = False):
    """Wrap a dispatch function with schema validation and repair.

    strict=False  repair silently, and hand unrepairable calls back to the model as a
                  structured error it can act on.
    strict=True   never repair; report every deviation. Use this to measure the raw
                  model, not the hardened stack.
    """
    by_name = {(t.get("function") or t)["name"]: t for t in tools}

    def inner(name: str, args: dict):
        schema = by_name.get(name)
        if schema is None:
            return {"error": "unknown tool %r" % name,
                    "available": sorted(by_name)[:40]}
        g = guard(schema, args)
        if log is not None and (g.repairs or g.errors):
            log.append({"tool": name, "repairs": g.repairs, "errors": g.errors,
                        "original": args})
        if g.errors:
            return {"error": "invalid arguments", "problems": g.errors,
                    "hint": "fix the listed parameters and call the tool again"}
        if strict and g.repairs:
            return {"error": "invalid arguments", "problems": g.repairs,
                    "hint": "match the schema exactly"}
        return dispatch(name, g.args)

    inner.inner = dispatch   # sarmalanan dispatch'e erisim (flush gibi ek nitelikler icin)
    return inner
