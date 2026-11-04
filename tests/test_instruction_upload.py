# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.msw_harbor import MiniSweHostAgent


class LocalUploadEnvironment:
    """Exercise the adapter's shell and file operations inside a temporary root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.sources: list[Path] = []

    async def exec(self, *, command: str, user: str) -> None:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=self.root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError(stderr.decode())

    async def upload_file(self, *, source_path: str, target_path: str) -> None:
        source = Path(source_path)
        self.sources.append(source)
        shutil.copyfile(source, self.root / target_path)


class InstructionUploadTest(unittest.IsolatedAsyncioTestCase):
    async def test_workspaces_preserve_their_literal_path(self) -> None:
        for workspace in (
            "workspace",
            "workspace with spaces",
            "workspace's files",
            "-workspace",
        ):
            with (
                self.subTest(workspace=workspace),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                environment = LocalUploadEnvironment(root)
                cwd = workspace if workspace.startswith("-") else str(root / workspace)
                agent = MiniSweHostAgent(logs_dir=root / "logs", cwd=cwd)
                instruction = "Build a café menu.\nKeep the exact specification.\n"

                await agent._upload_instruction(instruction, environment)

                self.assertEqual(
                    (root / workspace / "instruction.md").read_text(encoding="utf-8"),
                    instruction,
                )
                self.assertEqual(len(environment.sources), 1)
                self.assertFalse(environment.sources[0].exists())
                self.assertEqual({path.name for path in root.iterdir()}, {workspace})


if __name__ == "__main__":
    unittest.main()
