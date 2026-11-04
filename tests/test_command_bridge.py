# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from agents.msw_harbor import HarborEnvironment


class CommandBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def test_host_timeout_cancels_the_pending_environment_coroutine(self) -> None:
        release = asyncio.Event()
        cancelled = asyncio.Event()

        class WaitingEnvironment:
            async def exec(self, **kwargs):
                try:
                    await release.wait()
                    return SimpleNamespace(stdout="", stderr="", return_code=0)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        bridge = HarborEnvironment(
            WaitingEnvironment(), asyncio.get_running_loop(), timeout=0.01
        )
        try:
            # Exercise the actual bridge deadline, including its 30-second grace.
            observation = await asyncio.wait_for(
                asyncio.to_thread(bridge.execute, {"command": "waiting command"}),
                timeout=35,
            )
            self.assertEqual(observation["returncode"], -1)
            self.assertEqual(observation["extra"]["exception_type"], "TimeoutError")
            await asyncio.sleep(0.05)
            self.assertTrue(cancelled.is_set())
        finally:
            # Release the pending baseline coroutine even if the assertion fails.
            release.set()
            await asyncio.sleep(0)

    async def test_completed_command_keeps_its_output_and_exit_code(self) -> None:
        calls = []

        class CompletedEnvironment:
            async def exec(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(stdout="output", stderr="error", return_code=7)

        bridge = HarborEnvironment(
            CompletedEnvironment(), asyncio.get_running_loop(), cwd="/workspace"
        )
        observation = await asyncio.to_thread(bridge.execute, {"command": "control"})
        self.assertEqual(observation["output"], "outputerror")
        self.assertEqual(observation["returncode"], 7)
        self.assertEqual(calls[0]["cwd"], "/workspace")


if __name__ == "__main__":
    unittest.main()
