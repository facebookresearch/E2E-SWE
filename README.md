# E2E-SWE

E2E-SWE grades whole-repository generation: the agent is given a specification and must
build the project from nothing, then a **separate** container installs that work and runs a
hidden test suite against it. The agent never sees the tests, and neither container has network
access.

The agent runs on the *host*, outside the sandbox — only shell commands cross the boundary.

`agents/` holds the scaffold; `tasks/` holds the 186 tasks.

## Setup

```bash
uv tool install harbor==0.22.0        # brings mini_swe_agent 2.4.6 with it
```

Python 3.12+ is required (Harbor's own floor, and this adapter uses `typing.override`).

**Harbor needs a one-line patch.** Our tasks set `[verifier] environment_mode = "separate"`,
and on that path stock Harbor hardcodes `skip_tests_upload=True` — it assumes the verifier image
already ships its own `/tests`. These tasks upload the task's `tests/` at grade time instead, so
without the patch `/tests` never arrives and **every task fails with a score of zero**, which
looks exactly like total model failure. In `harbor/trial/trial.py` around line 720:

```diff
                      step_name=step_cfg.name if step_cfg is not None else None,
-                     skip_tests_upload=True,
+                     skip_tests_upload=False,
```

Verify before running anything:

```bash
python -c "import minisweagent, harbor; print(minisweagent.__version__)"
```

## Running

```bash
PYTHONPATH=/path/to/E2E-SWE \
  OPENAI_API_KEY=sk-... \
  MSWEA_MODEL_KWARGS='{"reasoning":{"effort":"xhigh"}}' \
  harbor run -p tasks --agent agents.msw_harbor:MiniSweHostAgent \
    --model openai/gpt-5.6-sol \
    --ak config_path=/path/to/E2E-SWE/agents/e2e_swe_mini_sweagent.yaml \
    --jobs-dir jobs --job-name <name> -n 25 -q -y
```

## Reading results

Per trial, under `jobs/<job>/<task>__<id>/`:

| file | contents |
|---|---|
| `verifier/ctrf.json` | per-test results |
| `verifier/reward.txt` | 1 if every hidden test passed, else 0 |
| `agent/mini-swe-agent.trajectory.json` | full trajectory, rewritten after every step |
| `agent/mini-swe-agent.turns.jsonl` | append-only per-turn log, tailable during a run |
| `result.json` | timings, exceptions, and token usage under `agent_result` |

A task is **resolved** when `verifier/reward.txt` is 1. Equivalently, in `verifier/ctrf.json`,
`results.summary.passed` equals the task's `[verifier].test_case_count` and no test failed, was
skipped, or ended in any other state. The two checks agree.

## License

E2E-SWE is released under the [Creative Commons Attribution-NonCommercial 4.0 International
License](https://creativecommons.org/licenses/by-nc/4.0/) (CC BY-NC 4.0). See [LICENSE](LICENSE).
