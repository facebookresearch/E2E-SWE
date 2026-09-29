# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Run mini-swe-agent as a Harbor agent whose actor lives OUTSIDE the sandbox.

Harbor's bundled mini-swe-agent (``harbor.agents.installed.mini_swe_agent``) is a
``BaseInstalledAgent``: it installs the CLI inside the task container and runs it there, so
the sandbox needs network access both to install the agent and to reach the model API.
E2E-SWE requires the opposite — the sandbox is offline and only ever receives shell
commands.

This module keeps mini-swe-agent's scaffold but relocates the actor to the host:

    host                                   sandbox (offline)
    ────────────────────────────────       ─────────────────
    DefaultAgent  ── model query ──► LLM API
         │
         └─ env.execute(cmd) ──────────►  environment.exec(cmd)

Nothing is installed in the container. mini-swe-agent lives in Harbor's own environment.

Usage::

    harbor run -p tasks --agent agents.msw_harbor:MiniSweHostAgent \\
        --model openai/<model> --ak config_path=agents/e2e_swe_mini_sweagent.yaml
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, override

import yaml

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


class HarborEnvironment:
    """mini-swe-agent ``Environment`` backed by a Harbor environment.

    Implements the duck-typed protocol from ``minisweagent`` (``execute`` /
    ``get_template_vars`` / ``serialize``). ``execute`` is synchronous because
    mini-swe-agent's agent loop is synchronous, while Harbor's ``exec`` is a coroutine — the
    loop therefore runs in a worker thread and each command is submitted back to Harbor's
    event loop via ``run_coroutine_threadsafe``.
    """

    def __init__(
        self,
        environment: BaseEnvironment,
        loop: asyncio.AbstractEventLoop,
        *,
        cwd: str = "/app",
        timeout: int = 300,
        env: dict[str, str] | None = None,
    ):
        self.environment = environment
        self.loop = loop
        # Mirrors LocalEnvironmentConfig's shape so templates referencing config fields work.
        self.config = type(
            "HarborEnvironmentConfig",
            (),
            {"cwd": cwd, "timeout": timeout, "env": env or {}},
        )()

    def execute(
        self, action: dict, cwd: str = "", *, timeout: int | None = None
    ) -> dict[str, Any]:
        command = action.get("command", "")
        target_cwd = cwd or self.config.cwd
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.environment.exec(
                    command=command,
                    cwd=target_cwd,
                    env=self.config.env or None,
                    timeout_sec=timeout or self.config.timeout,
                ),
                self.loop,
            )
            # Give the bridge a little longer than the command itself so a container-side
            # timeout surfaces as Harbor's own error rather than as a bridge timeout.
            result = future.result(timeout=(timeout or self.config.timeout) + 30)
            output = "".join(filter(None, (result.stdout, result.stderr)))
            observation = {
                "output": output,
                "returncode": result.return_code,
                "exception_info": "",
            }
        except Exception as e:  # noqa: BLE001 - surfaced to the model as an observation
            observation = {
                "output": "",
                "returncode": -1,
                "exception_info": f"An error occurred while executing the command: {e}",
                "extra": {"exception_type": type(e).__name__, "exception": str(e)},
            }
        self._check_finished(observation)
        return observation

    def _check_finished(self, output: dict) -> None:
        """Raise ``Submitted`` on mini-swe-agent's completion sentinel.

        Mirrors ``LocalEnvironment._check_finished``; the agent loop relies on this
        exception to terminate, so the semantics must match exactly.
        """
        from minisweagent.exceptions import Submitted

        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if (
            lines
            and lines[0].strip() == "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
            and output["returncode"] == 0
        ):
            submission = "".join(lines[1:])
            raise Submitted(
                {
                    "role": "exit",
                    "content": submission,
                    "extra": {"exit_status": "Submitted", "submission": submission},
                }
            )

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        """Template context for the prompts.

        Deliberately excludes ``os.environ``: unlike ``LocalEnvironment`` (where host and
        execution target are the same machine) the host env here is unrelated to the
        sandbox, and leaking it into prompts would be both wrong and a disclosure risk.
        """
        return {
            "cwd": self.config.cwd,
            "timeout": self.config.timeout,
            **kwargs,
        }

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "environment": {
                        "cwd": self.config.cwd,
                        "timeout": self.config.timeout,
                    },
                    "environment_type": f"{type(self).__module__}.{type(self).__name__}",
                }
            }
        }


def _model_class(model_name: str, override: str | None = None) -> type:
    """Pick mini-swe-agent's model class from the provider prefix."""
    if override:
        return _import_model_class(override)

    if _is_anthropic(model_name):
        return _streaming_litellm_model()

    if model_name.startswith("openai/") and _may_use_responses_api(model_name):
        from minisweagent.models.litellm_response_model import LitellmResponseModel

        return LitellmResponseModel

    from minisweagent.models.litellm_model import LitellmModel

    return LitellmModel


def _may_use_responses_api(model_name: str) -> bool:
    """Whether litellm's model map contradicts using the Responses API.

    Only a veto, never an endorsement. ``supported_endpoints`` is unpopulated for many models
    (``None`` for ``gpt-4o`` and every Claude id), so absence proves nothing and we fall
    through to the prefix. It also cannot decide the question on its own: ``gpt-5.6-sol``
    lists BOTH ``/v1/chat/completions`` and ``/v1/responses``, because the constraint is about
    tools plus reasoning effort rather than about the endpoint existing.
    """
    try:
        import litellm

        entry = litellm.model_cost.get(model_name.split("/", 1)[-1]) or {}
    except Exception:  # noqa: BLE001 - a missing map must not decide routing
        return True
    endpoints = entry.get("supported_endpoints")
    return not endpoints or "/v1/responses" in endpoints


def _import_model_class(spec: str) -> type:
    """Resolve a mini-swe-agent model-class shortcut or dotted path."""
    from minisweagent.models import get_model_class

    return get_model_class("", spec)


def _default_model_kwargs(cls: type) -> dict[str, Any]:
    """Per-route defaults for the arguments every run needs.

    ``timeout`` is Anthropic-only and is about wall-clock, not size: a single turn there can run
    for many minutes, past litellm's default.

    Reasoning effort is deliberately NOT defaulted. It is the variable under study in most
    runs, so it should be stated explicitly rather than inherited.
    """
    name = cls.__name__
    if name == "LitellmResponseModel":
        return {"max_output_tokens": 128000}
    if name == "StreamingLitellmModel":
        return {"max_tokens": 128000, "timeout": 3600}
    return {"max_completion_tokens": 128000}


def _is_anthropic(model_name: str) -> bool:
    """Whether the model is driven through litellm's Anthropic provider."""
    return (model_name or "").startswith("anthropic/")


def _default_model_config(cls: type) -> dict[str, Any]:
    """Model-class defaults that are not ``model_kwargs``.

    Anthropic prompt caching is opt-in: without explicit ``cache_control`` breakpoints in the
    request, nothing is cached.
    """
    if cls.__name__ == "StreamingLitellmModel":
        return {"set_cache_control": "default_end"}
    return {}


def _needs_streaming(model_name: str) -> bool:
    """Anthropic routes stream, so a long generation is not cut off by a non-streaming cap."""
    return _is_anthropic(model_name)


def _merge_thinking_blocks(chunks: list) -> list[dict]:
    """Rebuild Anthropic thinking blocks from streamed deltas.

    ``litellm.stream_chunk_builder`` drops ``thinking_blocks`` entirely, which would
    silently disable reasoning carryover — the whole reason for using this route. The raw
    deltas do carry them, so reassemble by hand: text arrives incrementally and the
    ``signature`` arrives once, at the end of each block.
    """
    blocks: list[dict] = []
    current: dict | None = None
    for chunk in chunks:
        for choice in getattr(chunk, "choices", None) or []:
            for block in getattr(choice.delta, "thinking_blocks", None) or []:
                if current is None:
                    current = {"type": block.get("type") or "thinking", "thinking": "", "signature": ""}
                current["thinking"] += block.get("thinking") or ""
                if block.get("signature"):
                    current["signature"] = block["signature"]
                    blocks.append(current)
                    current = None
    if current is not None:
        blocks.append(current)
    return blocks


def _drop_empty_text(message: Any) -> None:
    """Blank out ``content`` on a tool-only assistant message, in place.

    Claude routinely answers with a tool call and no prose. That arrives as ``content == ""``,
    and on the next request litellm materialises it into a text block, finds the block empty,
    and rather than dropping it substitutes 60 characters of
    ``[System: Empty message content sanitised to satisfy protocol]`` — which then lives in the
    history and is replayed to the model, attributed to itself, for the rest of the episode.

    The protocol does not require any of this. Measured against the API directly:

        tool_use with no text block        accepted
        empty text block + tool_use        rejected, "text content blocks must be non-empty"
        whitespace text block + tool_use   accepted by the API, but litellm still substitutes

    So ``""`` and ``" "`` both produce the placeholder while ``None`` produces a clean
    ``['tool_use']``. Setting None also records the truth in the trajectory: the model returned
    no text. Only applied when there is a tool call to carry the message, since a message with
    neither text nor tool_use would be invalid.
    """
    if not getattr(message, "tool_calls", None):
        return
    content = getattr(message, "content", None)
    if isinstance(content, str) and not content.strip():
        message.content = None


def _streaming_litellm_model() -> type:
    """``LitellmModel`` that streams and reassembles, for providers that need it."""
    import litellm
    from minisweagent.models.litellm_model import LitellmModel
    from minisweagent.models.utils.actions_toolcall import BASH_TOOL

    class StreamingLitellmModel(LitellmModel):
        def _query(self, messages: list[dict[str, str]], **kwargs):
            merged = self.config.model_kwargs | kwargs
            # Without this no chunk carries usage and stream_chunk_builder falls back to
            # its own estimate, which was wildly wrong on long streams (completion=8 for a
            # 686s generation). With it, the provider's real counts arrive on the last chunk.
            merged.setdefault("stream_options", {"include_usage": True})
            chunks = []
            try:
                for chunk in litellm.completion(
                    model=self.config.model_name, messages=messages,
                    tools=[BASH_TOOL], stream=True, **merged
                ):
                    chunks.append(chunk)
            except litellm.exceptions.AuthenticationError as e:
                e.message += " You can permanently set your API key with `mini-extra config set KEY VALUE`."
                raise
            response = litellm.stream_chunk_builder(chunks)
            message = response.choices[0].message
            if blocks := _merge_thinking_blocks(chunks):
                message.thinking_blocks = blocks
            _drop_empty_text(message)
            return response

    return StreamingLitellmModel




def _usage_totals(messages: list[dict]) -> dict[str, int]:
    """Sum per-turn token usage across a mini-swe-agent message history.

    Handles both history shapes: ``LitellmResponseModel`` stores the whole Responses object
    (``usage.input_tokens`` / ``output_tokens``), while ``LitellmModel`` stores a chat message
    with the response under ``extra.response.usage`` (``prompt_tokens`` / ``completion_tokens``).

    Input is summed per call, so it counts each turn's full context and therefore re-counts
    history — that is what "tokens used" means for billing, not the size of the final context.
    """
    totals = {"input": 0, "cache": 0, "output": 0, "reasoning": 0, "turns": 0}
    for m in messages:
        if m.get("object") == "response":
            u = m.get("usage") or {}
            inp, out = u.get("input_tokens"), u.get("output_tokens")
            cache = (u.get("input_tokens_details") or {}).get("cached_tokens")
            rsn = (u.get("output_tokens_details") or {}).get("reasoning_tokens")
        else:
            if m.get("role") != "assistant":
                continue
            u = ((m.get("extra") or {}).get("response") or {}).get("usage") or {}
            if not u:
                continue
            inp, out = u.get("prompt_tokens"), u.get("completion_tokens")
            cache = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
            rsn = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
        inp, out = inp or 0, out or 0
        # Some gateway routes report a bogus prompt count while total_tokens stays
        # correct. Prefer the total when the parts disagree with it, so the figure is
        # not silently wrong for those models.
        total = u.get("total_tokens")
        if total and inp + out != total:
            inp = max(total - out, 0)
        totals["input"] += inp
        totals["output"] += out
        totals["cache"] += cache or 0
        totals["reasoning"] += rsn or 0
        totals["turns"] += 1
    return totals


def _as_role_content(message: dict) -> tuple[str, str]:
    """Flatten a history entry to ``(role, text)`` for the turn log.

    Chat-shaped entries already carry ``role``/``content``. ``LitellmResponseModel`` instead
    stores the whole Responses object (``object == "response"``), whose text and tool calls
    live in an ``output`` array — without unpacking it every assistant turn would log as empty.
    """
    if message.get("object") != "response":
        return str(message.get("role") or ""), str(message.get("content") or "")

    parts: list[str] = []
    for item in message.get("output") or []:
        kind = item.get("type")
        if kind == "message":
            for block in item.get("content") or []:
                if text := block.get("text"):
                    parts.append(text)
        elif kind == "function_call":
            parts.append(f"[{item.get('name')}] {item.get('arguments')}")
        elif kind == "reasoning":
            # Content is encrypted and opaque; record only that a step happened.
            parts.append(f"[reasoning {item.get('id', '')}]")
    return "assistant", "\n".join(parts)


def _tracing_agent_class() -> type:
    """DefaultAgent subclass that appends a compact record per turn.

    ``DefaultAgent.run`` already calls ``save(config.output_path)`` in a ``finally`` after
    every step, so the full trajectory JSON is rewritten each turn (and survives crashes).
    That file is authoritative but is rewritten wholesale; this adds an append-only JSONL
    so a run can be tailed live and turns diffed without re-reading the whole trajectory.
    """
    import time

    from minisweagent.agents.default import DefaultAgent

    class TracingAgent(DefaultAgent):
        turn_log: Any = None  # set by the caller after construction

        def step(self) -> list[dict]:
            start_idx = len(self.messages)
            t0 = time.time()
            error: Exception | None = None
            try:
                return super().step()
            except Exception as e:  # noqa: BLE001 - re-raised below, recorded first
                error = e
                raise
            finally:
                self._append_turn(start_idx, t0, error)

        def _append_turn(
            self, start_idx: int, t0: float, error: Exception | None
        ) -> None:
            if not self.turn_log:
                return
            cap = 50_000  # the full text is in the trajectory JSON; this view stays tailable
            new = []
            for m in self.messages[start_idx:]:
                role, content = _as_role_content(m)
                new.append(
                    {
                        "role": role,
                        "content": content[:cap],
                        "truncated": len(content) > cap,
                        "extra": m.get("extra", {}),
                    }
                )
            record = {
                "turn": self.n_calls,
                "elapsed_sec": round(time.time() - t0, 2),
                "cost_cumulative": self.cost,
                "error": None if error is None else f"{type(error).__name__}: {error}",
                "messages": new,
            }
            try:
                with open(self.turn_log, "a") as f:
                    f.write(json.dumps(record, default=str) + "\n")
            except Exception:  # noqa: BLE001 - tracing must never fail a run
                pass

    return TracingAgent


class MiniSweHostAgent(BaseAgent):
    """Harbor agent that drives mini-swe-agent from the host."""

    def __init__(
        self,
        *args,
        config_path: str | None = None,
        model_class: str | None = None,
        step_limit: int = 500,
        cost_limit: float = 0.0,
        command_timeout: int = 300,
        cwd: str = "/app",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._config_path = config_path
        # Escape hatch for endpoints the provider prefix mis-describes: an OpenAI-compatible
        # server that implements only chat completions needs model_class=litellm.
        self._model_class_override = model_class
        self._step_limit = step_limit
        self._cost_limit = cost_limit
        self._command_timeout = command_timeout
        self._cwd = cwd
        self._env: HarborEnvironment | None = None

    @staticmethod
    @override
    def name() -> str:
        return "mini-swe-agent-host"

    @override
    def version(self) -> str:
        import minisweagent

        return minisweagent.__version__

    @override
    async def setup(self, environment: BaseEnvironment) -> None:
        """Nothing to do: the actor runs on the host and installs nothing in the sandbox."""
        return

    def _load_config(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return ``(agent_kwargs, model_kwargs)`` from the config file.

        mini-swe-agent's own runners split the YAML into ``agent:`` / ``model:`` /
        ``environment:`` sections and hand each to its own constructor. We build the
        environment ourselves (it is Harbor's container), but ``model:`` must still reach the
        model — that is where ``observation_template`` and ``format_error_template`` live.
        """
        if not self._config_path:
            raise ValueError(
                "config_path is required: mini-swe-agent's system_template and "
                "instance_template have no defaults."
            )
        raw = yaml.safe_load(Path(self._config_path).read_text())
        # Accept both a bare mapping and mini-swe-agent's {agent: {...}} config layout.
        if "agent" not in raw and "model" not in raw:
            return raw, {}
        return raw.get("agent", {}), raw.get("model", {})

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        loop = asyncio.get_running_loop()
        self._env = HarborEnvironment(
            environment,
            loop,
            cwd=self._cwd,
            timeout=self._command_timeout,
        )

        # The prompt tells the model the spec is at <cwd>/instruction.md, and for long
        # specs it matters that the file is really there (the model greps and re-reads it
        # rather than relying on context). Harbor only passes the instruction as prompt
        # text, so place the file ourselves, matching the reference harness.
        await self._upload_instruction(instruction, environment)

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        trajectory_path = self.logs_dir / "mini-swe-agent.trajectory.json"
        turn_log_path = self.logs_dir / "mini-swe-agent.turns.jsonl"

        agent_kwargs, model_config = self._load_config()
        agent_kwargs.setdefault("step_limit", self._step_limit)
        agent_kwargs.setdefault("cost_limit", self._cost_limit)
        # DefaultAgent.run() saves to this path after every step, in a finally — so the
        # trajectory is current even if the run crashes or is killed mid-task.
        agent_kwargs["output_path"] = trajectory_path

        # Least to most specific: route defaults, then the config file's `model.model_kwargs`,
        # then MSWEA_MODEL_KWARGS. Merged per key, so setting one value in the environment
        # does not discard the others.
        model_name = self.model_name or ""
        cls = _model_class(model_name, self._model_class_override)
        model_config = _default_model_config(cls) | model_config
        model_kwargs = _default_model_kwargs(cls)
        model_kwargs |= model_config.pop("model_kwargs", None) or {}
        model_kwargs |= json.loads(os.environ.get("MSWEA_MODEL_KWARGS", "{}"))

        model = cls(
            **model_config,
            model_name=model_name,
            # Cost data is unavailable for gateway-hosted model names; without this the
            # run aborts on a missing-cost lookup rather than on anything substantive.
            cost_tracking="ignore_errors",
            model_kwargs=model_kwargs,
        )
        self.logger.info(f"model kwargs: {json.dumps(model_kwargs, sort_keys=True)}")
        agent = _tracing_agent_class()(model=model, env=self._env, **agent_kwargs)
        agent.turn_log = turn_log_path

        # The agent loop is synchronous and blocks on env.execute(); run it off the event
        # loop so run_coroutine_threadsafe has a live loop to submit commands back to.
        try:
            exit_status, result = await asyncio.to_thread(
                self._run_sync, agent, instruction
            )
        finally:
            # save() already ran per step; this guarantees a final write even if the agent
            # raised before its own finally could fire.
            agent.save(trajectory_path)
            # Harbor leaves these None unless the agent fills them in; populating here means
            # they land in result.json and are reportable without re-parsing trajectories.
            # trial.py only falls back to populate_context_post_run() while the context is
            # still empty, so setting them here wins.
            self._populate_usage(context, agent)
            self.logger.info(
                f"mini-swe-agent: steps={agent.n_calls} cost={agent.cost} "
                f"trajectory={trajectory_path} turns={turn_log_path}"
            )
        self.logger.info(f"mini-swe-agent finished: exit_status={exit_status}")

    def _populate_usage(self, context: AgentContext, agent: Any) -> None:
        """Fill Harbor's AgentContext token/cost fields from the agent's own history."""
        try:
            t = _usage_totals(agent.messages)
        except Exception as e:  # noqa: BLE001 - accounting must never fail a trial
            self.logger.warning(f"could not compute token usage: {e}")
            return
        context.n_input_tokens = t["input"]
        context.n_output_tokens = t["output"]
        context.n_cache_tokens = t["cache"]
        # agent.cost is 0.0 whenever litellm has no pricing for the model name, which is the
        # case for gateway-hosted names. Reporting 0.0 would read as "free" rather
        # than "unknown", so leave it unset in that case.
        if agent.cost:
            context.cost_usd = agent.cost
        context.metadata = {
            **(context.metadata or {}),
            "n_turns": t["turns"],
            "n_reasoning_tokens": t["reasoning"],
        }

    async def _upload_instruction(
        self, instruction: str, environment: BaseEnvironment
    ) -> None:
        import tempfile

        target = f"{self._cwd}/instruction.md"
        tmp = None
        try:
            await environment.exec(command=f"mkdir -p {self._cwd}", user="root")
            with tempfile.NamedTemporaryFile(
                "w", suffix=".md", delete=False, encoding="utf-8"
            ) as f:
                f.write(instruction)
                tmp = f.name
            await environment.upload_file(source_path=tmp, target_path=target)
            self.logger.info(f"placed spec at {target} ({len(instruction)} chars)")
        except Exception as e:  # noqa: BLE001 - the spec is also in the prompt
            self.logger.warning(f"could not place {target}: {e}")
        finally:
            if tmp:
                Path(tmp).unlink(missing_ok=True)

    @staticmethod
    def _run_sync(agent: Any, instruction: str) -> tuple[str, str]:
        out = agent.run(instruction)
        if isinstance(out, dict):
            return str(out.get("exit_status", "")), str(out.get("submission", ""))
        return "", str(out)
