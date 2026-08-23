"""Harness-level recovery rules for MCP calls.

Measured on this model: a system-prompt instruction of the form "if a lookup by a
translated name returns nothing, list everything with an empty filter instead of giving
up" is NOT reliably followed. The model searched for the Turkish word "Zemin", got zero
results, and stopped - twice, with the instruction present verbatim.

Conclusion: recovery behaviour that must always happen belongs in code. Prompts are for
preferences; the harness is for guarantees.

A rule fires on the tool result, not on the model's intent, so it cannot be argued with.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Any, Callable


def _as_obj(result: Any) -> Any:
    if isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:
            return result
    return result


def looks_empty(result: Any) -> bool:
    """True when a lookup came back with nothing useful."""
    o = _as_obj(result)
    if isinstance(o, dict):
        if o.get("count") == 0:
            return True
        for k in ("objects", "actors", "results", "items", "entries", "matches"):
            v = o.get(k)
            if isinstance(v, list) and not v:
                return True
    if isinstance(o, list) and not o:
        return True
    if isinstance(o, str) and re.search(r"\b(no|0)\s+(results?|objects?|matches?)\b",
                                        o, re.IGNORECASE):
        return True
    return False


@dataclass
class Rule:
    """When `when` holds for a call's result, retry with `widen(args)` and annotate."""
    tools: tuple[str, ...]
    when: Callable[[dict, Any], bool]
    widen: Callable[[dict], dict]
    note: str


def drop_filters(*keys: str) -> Callable[[dict], dict]:
    def f(args: dict) -> dict:
        return {k: v for k, v in args.items() if k not in keys}
    return f


#: Defaults that cover the search-returned-nothing failure seen in engine bridges.
DEFAULT_RULES: list[Rule] = [
    Rule(tools=("unity_find_objects", "find_objects", "unity_manage_gameobject"),
         when=lambda a, r: looks_empty(r) and bool(a.get("name_contains")),
         widen=drop_filters("name_contains"),
         note="The name filter matched nothing, so the unfiltered scene listing is "
              "included below. Scene names are in English; pick the matching object "
              "yourself and retry with its exact path."),
    Rule(tools=("unreal_list_actors", "list_actors"),
         when=lambda a, r: looks_empty(r) and bool(a.get("class_filter")),
         widen=drop_filters("class_filter"),
         note="The class filter matched nothing, so the unfiltered actor list is "
              "included below."),
]


def resilient(dispatch: Callable[[str, dict], Any],
              rules: list[Rule] | None = None,
              log: list | None = None) -> Callable[[str, dict], Any]:
    """Wrap a dispatch function so empty lookups automatically widen once."""
    rs = rules if rules is not None else DEFAULT_RULES

    def inner(name: str, args: dict) -> Any:
        result = dispatch(name, args)
        for rule in rs:
            if name not in rule.tools:
                continue
            try:
                fires = rule.when(args or {}, result)
            except Exception:
                fires = False
            if not fires:
                continue
            wider = rule.widen(dict(args or {}))
            if wider == (args or {}):
                continue
            retry = dispatch(name, wider)
            if log is not None:
                log.append({"tool": name, "original_args": args, "widened_args": wider})
            return {"original_query": args, "original_result_was_empty": True,
                    "note": rule.note, "widened_query": wider,
                    "widened_result": _as_obj(retry)}
        return result

    return inner
