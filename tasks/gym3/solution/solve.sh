#!/bin/bash
set -e

git clone https://github.com/openai/gym3.git /tmp/repo
cd /tmp/repo
git checkout f220142bd21bf196279bc651b395e6f817baa69d

# The task presents this library under the neutral import name `vectorenv`.
# Unlike confection, gym3 uses absolute imports (`from gym3.x import y`), so a
# directory rename alone is not enough: rewrite the package token everywhere.
# `\bgym3\b` only matches the whole word, so the external `gym` dependency
# referenced inside the (out-of-scope) interop module is left untouched.
mv /tmp/repo/gym3 /tmp/repo/vectorenv
find /tmp/repo/vectorenv -name '*.py' -exec sed -i 's/\bgym3\b/vectorenv/g' {} +

# Scope the package to the in-scope public surface. The excluded modules need a
# display (viewer/video_recorder/interactive/internal.renderer), a C library
# (libenv via cffi), torch (types_th), or an old `gym`/`baselines` (interop),
# and the `testing` envs use `np.bool` (removed in numpy >= 1.24); the original
# source files stay on disk but are not imported by the package entrypoint.
cat > /tmp/repo/vectorenv/__init__.py <<'PY'
from vectorenv import types, types_np
from vectorenv.env import Env
from vectorenv.wrapper import Wrapper, unwrap
from vectorenv.concat import ConcatEnv
from vectorenv.extract_dict_ob import ExtractDictObWrapper
from vectorenv.trajectory_recorder import TrajectoryRecorderWrapper
from vectorenv.asynchronous import AsynchronousWrapper
from vectorenv.subproc import SubprocEnv, SubprocError
from vectorenv.util import call_func

__all__ = [
    "types",
    "types_np",
    "Env",
    "Wrapper",
    "unwrap",
    "ConcatEnv",
    "ExtractDictObWrapper",
    "TrajectoryRecorderWrapper",
    "AsynchronousWrapper",
    "SubprocEnv",
    "SubprocError",
    "call_func",
]
PY

# Minimal, modern-numpy-friendly packaging (the original pins numpy<2.0 plus a
# stack of GUI/native deps that have no wheels on Python 3.13; the in-scope code
# only needs numpy at runtime).
cat > /tmp/repo/setup.py <<'PY'
from setuptools import find_packages, setup

setup(
    name="vectorenv",
    version="0.3.3",
    packages=find_packages(),
    install_requires=["numpy"],
    python_requires=">=3.6",
)
PY

cp -a /tmp/repo/. /app/
cd /app
rm -rf /tmp/repo

# setup.sh installs the project offline: numpy + the build backend are pre-baked and the image sets
# PIP_NO_INDEX. --no-build-isolation is REQUIRED so pip uses the baked setuptools/wheel instead of
# fetching an isolated build env (which would fail offline). The cp -a above carries .git, but the
# rewritten setup.py uses a static version so no scm resolution is needed.
echo 'pip install -e . --no-build-isolation' > ./setup.sh
