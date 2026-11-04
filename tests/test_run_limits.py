# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from harbor.models.agent.context import AgentContext
from minisweagent.exceptions import Submitted

from agents.msw_harbor import MiniSweHostAgent


class SyntheticModel:
    """Bounded, provider-free model for exercising the real DefaultAgent loop."""

    def __init__(self, **kwargs):
        self.calls = 0

    def query(self, messages):
        self.calls += 1
        if self.calls == 6:
            raise Submitted({"role": "exit", "content": "synthetic stop", "extra": {}})
        return {
            "role": "assistant",
            "content": "continue",
            "extra": {"cost": 1.0, "actions": []},
        }

    def get_template_vars(self):
        return {}

    def format_message(self, **kwargs):
        return kwargs

    def format_observation_messages(self, *args):
        return [{"role": "tool", "content": "synthetic observation"}]

    def serialize(self):
        return {}


class RunLimitsTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, configured, overrides):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.yaml"
            config.write_text(
                yaml.safe_dump(
                    {
                        "agent": {
                            "system_template": "Synthetic test",
                            "instance_template": "{{task}}",
                            **configured,
                        }
                    }
                ),
                encoding="utf-8",
            )
            agent = MiniSweHostAgent(
                logs_dir=root / "logs", config_path=str(config), **overrides
            )
            with (
                mock.patch(
                    "agents.msw_harbor._model_class", return_value=SyntheticModel
                ),
                mock.patch.object(
                    agent, "_upload_instruction", new_callable=mock.AsyncMock
                ),
                mock.patch.dict("os.environ", {"MSWEA_MODEL_KWARGS": "{}"}),
            ):
                await agent.run("invented fixture", None, AgentContext())
            return json.loads(
                (root / "logs/mini-swe-agent.trajectory.json").read_text()
            )

    async def test_explicit_step_limit_overrides_yaml(self):
        result = await self._run({"step_limit": 4}, {"step_limit": 1})
        self.assertEqual(result["info"]["model_stats"]["api_calls"], 1)

    async def test_explicit_cost_limit_overrides_yaml(self):
        result = await self._run({"cost_limit": 4.0}, {"cost_limit": 1.0})
        self.assertEqual(result["info"]["model_stats"]["api_calls"], 1)

    async def test_omitted_limits_preserve_yaml(self):
        result = await self._run({"step_limit": 4, "cost_limit": 0.0}, {})
        self.assertEqual(result["info"]["model_stats"]["api_calls"], 4)

    async def test_explicit_zero_limits_override_yaml(self):
        result = await self._run(
            {"step_limit": 4, "cost_limit": 4.0}, {"step_limit": 0, "cost_limit": 0.0}
        )
        self.assertEqual(result["info"]["model_stats"]["api_calls"], 6)

    async def test_omitted_limits_preserve_adapter_defaults(self):
        result = await self._run({}, {})
        config = result["info"]["config"]["agent"]
        self.assertEqual(config["step_limit"], 500)
        self.assertEqual(config["cost_limit"], 0.0)


if __name__ == "__main__":
    unittest.main()
