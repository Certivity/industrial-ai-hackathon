"""A thin layer over the Anthropic SDK for the agent. One request path for every stage:

  * streaming (long inputs and outputs never hit a request timeout), adaptive thinking with an explicit effort, top-level prompt caching
  * a cost ledger with a budget: the run stops before the call that would start above the cap
  * an on-disk replay cache of identical requests, so a re-run after a change to a later stage replays the earlier stages for free
  * structured output (output_config.format) and a tool loop whose history is append-only (Sonnet 5.5 binds thinking blocks to the
    conversation that produced them: nothing earlier in `messages` may be edited after it was sent)

Sonnet 5.5 rejects forced tool_choice, thinking "disabled" and sampling parameters, so none of them is sent: tools run with "auto" and the
prompt says which tool ends the work; a call that never comes is nudged.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import anthropic

from .config import Settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# model: (input, output, cache read, cache write for 5 minutes) in USD per million tokens, from the model table of the Claude API docs
PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.50),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.50),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-fable-5-1": (10.0, 50.0, 1.0, 12.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
FALLBACK_PRICE = PRICES["claude-sonnet-5-5"]


class BudgetExceeded(RuntimeError):
    pass


class Refused(RuntimeError):
    def __init__(self, category: str | None, explanation: str | None):
        super().__init__(f"the model declined the request (category {category}): {explanation}")
        self.category, self.explanation = category, explanation


def _no_log(_: str) -> None:
    return None


def stderr_log(message: str) -> None:
    print(time.strftime("%H:%M:%S ") + message, file=sys.stderr, flush=True)


@dataclass
class Reply:
    content: list[dict]  # plain dicts: they go back into `messages` unchanged and into the replay cache as they are
    stop_reason: str | None
    model: str
    usage: dict
    stop_details: dict | None = None
    cached: bool = False
    seconds: float = 0.0

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def tool_uses(self) -> list[dict]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    @property
    def fell_back(self) -> bool:
        return any(b.get("type") == "fallback" for b in self.content)

    def json(self) -> Any:
        text = self.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)


@dataclass
class ToolOutcome:
    text: str
    is_error: bool = False


@dataclass
class LoopResult:
    messages: list[dict]
    turns: int
    finished: bool
    reason: str


class Ledger:
    """Tokens, cost and time per stage. `spent` is what this run paid; `replayed` is what cached calls would have cost again."""

    def __init__(self, model: str, max_cost: float):
        self.model, self.max_cost = model, max_cost
        self.price = PRICES.get(model, FALLBACK_PRICE)
        self.priced = model in PRICES
        self._lock = threading.Lock()
        self.stages: dict[str, dict] = {}

    def cost(self, usage: dict) -> float:
        p_in, p_out, p_read, p_write = self.price
        return (usage.get("input_tokens", 0) * p_in + usage.get("output_tokens", 0) * p_out
                + usage.get("cache_read_input_tokens", 0) * p_read + usage.get("cache_creation_input_tokens", 0) * p_write) / 1e6

    def add(self, stage: str, usage: dict, seconds: float, cached: bool, fell_back: bool = False) -> None:
        with self._lock:
            row = self.stages.setdefault(stage, {"calls": 0, "replayed_calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                                                 "spent": 0.0, "replayed": 0.0, "seconds": 0.0, "fallbacks": 0})
            row["replayed_calls" if cached else "calls"] += 1
            row["replayed" if cached else "spent"] += self.cost(usage)
            row["seconds"] += 0.0 if cached else seconds
            row["fallbacks"] += int(fell_back)
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                row[k] += usage.get(k, 0)

    @property
    def spent(self) -> float:
        with self._lock:
            return sum(r["spent"] for r in self.stages.values())

    @property
    def replayed(self) -> float:
        with self._lock:
            return sum(r["replayed"] for r in self.stages.values())

    def check(self) -> None:
        if self.spent >= self.max_cost:
            raise BudgetExceeded(f"spent ${self.spent:.2f} of the ${self.max_cost:.2f} budget; raise AI_AGENT_MAX_COST_USD or --max-cost")

    def summary(self) -> dict:
        with self._lock:
            stages = {k: {**v, "spent": round(v["spent"], 4), "replayed": round(v["replayed"], 4), "seconds": round(v["seconds"], 1)}
                      for k, v in self.stages.items()}
        return {"model": self.model, "priced": self.priced, "spent_usd": round(self.spent, 4), "replayed_usd": round(self.replayed, 4),
                "budget_usd": self.max_cost, "stages": stages}


class LLM:
    def __init__(self, settings: Settings, ledger: Ledger | None = None, log: Callable[[str], None] = _no_log,
                 call_log: Path | None = None, client: anthropic.Anthropic | None = None):
        self.s = settings
        self.ledger = ledger or Ledger(settings.model, settings.max_cost_usd)
        self.log = log
        self.call_log = call_log
        self._client = client
        self._file_lock = threading.Lock()

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.s.api_key, max_retries=6, timeout=900.0)
        return self._client

    # ------------------------------------------------------------------------------------------------------------ one request
    def _tool(self, tool: dict) -> dict:
        return {**tool, "eager_input_streaming": True} if self.s.eager_tools else dict(tool)

    def _kwargs(self, system, messages, tools, schema, effort: str, max_tokens: int, auto_cache: bool) -> dict:
        output: dict = {"effort": effort}
        if schema is not None:
            output["format"] = {"type": "json_schema", "schema": schema}
        kwargs: dict = {"model": self.s.model, "max_tokens": max_tokens, "messages": messages, "output_config": output}
        if auto_cache:  # caches the last cacheable block, which pays off when the same prefix is read again (the history of a tool loop);
            kwargs["cache_control"] = {"type": "ephemeral"}  # a prompt that is sent once would only cost the 25% write premium
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [self._tool(t) for t in tools]
        return kwargs

    def _key(self, kwargs: dict) -> str:
        return hashlib.sha256(json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        return self.s.cache_dir / key[:2] / f"{key}.json" if self.s.cache_dir else None

    def _send(self, kwargs: dict) -> Reply:
        t0 = time.time()
        if self.s.fallbacks:
            stream = self.client.beta.messages.stream(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            stream = self.client.messages.stream(**kwargs)
        with stream as events:
            final = events.get_final_message()
        usage = final.usage
        details = getattr(final, "stop_details", None)
        return Reply(
            content=[block.model_dump(mode="json", exclude_none=True) for block in final.content],
            stop_reason=final.stop_reason, model=final.model,
            usage={"input_tokens": usage.input_tokens or 0, "output_tokens": usage.output_tokens or 0,
                   "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
                   "cache_read_input_tokens": usage.cache_read_input_tokens or 0},
            stop_details=details.model_dump(mode="json", exclude_none=True) if details is not None else None,
            seconds=time.time() - t0)

    def call(self, *, stage: str, label: str, system: str | list | None, messages: list[dict], tools: list[dict] | None = None,
             schema: dict | None = None, effort: str | None = None, max_tokens: int = 16_000, auto_cache: bool = False) -> Reply:
        kwargs = self._kwargs(system, messages, tools, schema, effort or self.s.effort[stage], max_tokens, auto_cache)
        key = self._key(kwargs)
        path = self._cache_path(key)
        if path is not None and path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            reply = Reply(data["content"], data["stop_reason"], data["model"], data["usage"], data.get("stop_details"), cached=True)
            self.ledger.add(stage, reply.usage, 0.0, cached=True, fell_back=reply.fell_back)
            self._record(stage, label, reply)
            return reply
        self.ledger.check()
        reply = self._send(kwargs)
        if path is not None and reply.stop_reason != "refusal":
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"content": reply.content, "stop_reason": reply.stop_reason, "model": reply.model, "usage": reply.usage,
                                       "stop_details": reply.stop_details}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        self.ledger.add(stage, reply.usage, reply.seconds, cached=False, fell_back=reply.fell_back)
        self._record(stage, label, reply)
        return reply

    def _record(self, stage: str, label: str, reply: Reply) -> None:
        u = reply.usage
        cost = self.ledger.cost(u)
        self.log(f"[{stage}] {label}: {'replay' if reply.cached else f'{reply.seconds:.0f}s'} in {u['input_tokens']}+{u['cache_read_input_tokens']}r"
                 f"+{u['cache_creation_input_tokens']}w out {u['output_tokens']} ${cost:.3f} {reply.stop_reason}"
                 + (" FALLBACK" if reply.fell_back else ""))
        if self.call_log is not None:
            row = {"stage": stage, "label": label, "cached": reply.cached, "stop_reason": reply.stop_reason, "model": reply.model,
                   "seconds": round(reply.seconds, 1), "cost": round(cost, 5), "fell_back": reply.fell_back, **u}
            with self._file_lock, self.call_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")

    # --------------------------------------------------------------------------------------------------------- structured output
    def complete_json(self, *, stage: str, label: str, system: str | list | None, user: str | list, schema: dict,
                      effort: str | None = None, max_tokens: int = 16_000) -> dict:
        """One structured answer. A cut-off answer (max_tokens) is asked again with twice the room; a decline raises Refused."""
        messages = [{"role": "user", "content": user}]
        for attempt in range(3):
            reply = self.call(stage=stage, label=label, system=system, messages=messages, schema=schema, effort=effort, max_tokens=max_tokens)
            if reply.stop_reason == "refusal":
                raise Refused((reply.stop_details or {}).get("category"), (reply.stop_details or {}).get("explanation"))
            if reply.stop_reason == "max_tokens":
                max_tokens = min(max_tokens * 2, 64_000)
                continue
            try:
                return reply.json()
            except (json.JSONDecodeError, IndexError) as error:
                self.log(f"[{stage}] {label}: answer is not JSON ({error}); asking again")
        raise RuntimeError(f"{stage}/{label}: no complete JSON answer after 3 attempts")

    # ------------------------------------------------------------------------------------------------------------- tool loop
    def run_tools(self, *, stage: str, label: str, system: str | list, first_user: str | list, tools: list[dict],
                  handle: Callable[[str, dict], ToolOutcome], done: Callable[[], bool], max_turns: int, effort: str | None = None,
                  max_tokens: int = 24_000, nudge: str = "Finish now by calling the submit tool.") -> LoopResult:
        """Run `tools` until `done()`. The history only grows: assistant turns are appended exactly as received (thinking blocks included)
        and every tool result of one turn goes back in one user message."""
        messages: list[dict] = [{"role": "user", "content": first_user}]
        nudges = 0
        turn = 0
        while turn < max_turns:
            turn += 1
            reply = self.call(stage=stage, label=f"{label}#{turn}", system=system, messages=messages, tools=tools, effort=effort,
                              max_tokens=max_tokens, auto_cache=True)
            if reply.stop_reason == "refusal":
                return LoopResult(messages, turn, False, f"refused: {(reply.stop_details or {}).get('category')}")
            if reply.stop_reason == "max_tokens":
                # the turn was cut off, so its tool inputs cannot be trusted; it was never sent back, so dropping it keeps the history append-only
                if max_tokens >= 64_000:
                    return LoopResult(messages, turn, False, "a turn used the whole output budget")
                max_tokens = min(max_tokens * 2, 64_000)
                turn -= 1
                continue
            messages.append({"role": "assistant", "content": reply.content})
            uses = reply.tool_uses
            if not uses:
                if done():
                    return LoopResult(messages, turn, True, "done")
                if nudges >= 2:
                    return LoopResult(messages, turn, False, "the model stopped without submitting")
                nudges += 1
                messages.append({"role": "user", "content": nudge})
                continue
            results = []
            for use in uses:
                try:
                    outcome = handle(use["name"], use.get("input") or {})
                except Exception as error:  # a handler bug must not end the walk; the model is told and can go on
                    outcome = ToolOutcome(f"internal error in {use['name']}: {error}", True)
                results.append({"type": "tool_result", "tool_use_id": use["id"], "content": outcome.text, "is_error": outcome.is_error})
            if done():
                messages.append({"role": "user", "content": results})
                return LoopResult(messages, turn, True, "done")
            if turn == max_turns - 1:
                results.append({"type": "text", "text": "Step limit: submit your selection on your next turn with what you have found."})
            messages.append({"role": "user", "content": results})
        return LoopResult(messages, turn, False, "step limit")
