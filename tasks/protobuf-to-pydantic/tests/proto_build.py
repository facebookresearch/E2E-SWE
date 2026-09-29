"""Compile the proto fixtures and expose the generated message modules.

The fixtures carry ``validate`` / ``p2p_validate`` field options, the same Protobuf packages the
implementation under test compiles into ``protobuf_to_pydantic.protos``. To avoid a descriptor-pool
"duplicate symbol" clash, the fixtures REUSE the implementation's already-compiled rule modules instead of
registering a second copy: we import ``protobuf_to_pydantic.protos.{p2p_validate_pb2,validate_pb2}``, then
compile only the demo messages against the exact file names those modules registered, aliasing the
generated imports back to them.

Flows:
* ``build_base()`` -> the demo message modules (runtime + code-generation flows). Called at collection.
* ``build_plugin()`` -> runs the protoc plugin to emit ``*_p2p`` model modules (plugin flow). Called lazily
  by the plugin tests, so a buggy plugin fails only those tests.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

TESTS_DIR = Path(__file__).parent
PROTO_DIR = TESTS_DIR / "proto"
PLUGIN_CONFIG = TESTS_DIR / "plugin_config.py"

_gen_dir: Path | None = None
_inc_dir: Path | None = None
_plugin_done = False


def _run(cmd: list[str], cwd: str | None = None) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(TESTS_DIR), env.get("PYTHONPATH", "")])
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def _module_name_for(proto_name: str) -> str:
    """The Python module name protoc generates for a proto file path (e.g. protos/x.proto -> protos.x_pb2)."""
    return proto_name[: -len(".proto")].replace("/", ".") + "_pb2"


def _alias_module(mod_name: str, target) -> None:
    """Make ``import mod_name`` resolve to an already-imported module ``target`` (with package stubs)."""
    parts = mod_name.split(".")
    for i in range(1, len(parts)):
        pkg = ".".join(parts[:i])
        if pkg not in sys.modules:
            stub = types.ModuleType(pkg)
            stub.__path__ = []  # mark as package
            sys.modules[pkg] = stub
    sys.modules[mod_name] = target
    if len(parts) > 1:
        setattr(sys.modules[".".join(parts[:-1])], parts[-1], target)


def _gen() -> Path:
    global _gen_dir
    if _gen_dir is None:
        _gen_dir = Path(tempfile.mkdtemp(prefix="p2p_fixtures_"))
        sys.path.insert(0, str(_gen_dir))
        sys.path.insert(0, str(TESTS_DIR))  # so generated ``from plugin_config import ...`` resolves
    return _gen_dir


def _stage_demo() -> tuple[Path, list[str]]:
    """Stage the proto include dir and return ``(include_dir, protos_to_compile)``.

    Preferred path: reuse the implementation's already-compiled ``protobuf_to_pydantic.protos`` rule modules
    (so the rule packages are registered exactly once, avoiding a descriptor-pool "duplicate symbol" clash
    with implementations that import their protos eagerly). The demo protos are rewritten to import the rule
    files under the implementation's registered names, and only the demos are compiled.

    Fallback (when the implementation's compiled protos can't be imported -- e.g. a gencode/runtime version
    mismatch): compile our own copies of the rule protos alongside the demos.
    """
    try:
        from protobuf_to_pydantic.protos import p2p_validate_pb2, validate_pb2  # registers the rule packages
        n_p2p = p2p_validate_pb2.DESCRIPTOR.name
        n_val = validate_pb2.DESCRIPTOR.name
        _alias_module(_module_name_for(n_p2p), p2p_validate_pb2)
        _alias_module(_module_name_for(n_val), validate_pb2)
        inc = Path(tempfile.mkdtemp(prefix="p2p_inc_"))
        for name, src in ((n_p2p, "p2p_validate.proto"), (n_val, "validate.proto")):
            dst = inc / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text((PROTO_DIR / src).read_text())
        for demo, rule_src, rule_name in (("demo_p2p.proto", "p2p_validate.proto", n_p2p),
                                          ("demo_pgv.proto", "validate.proto", n_val)):
            text = (PROTO_DIR / demo).read_text().replace(f'import "{rule_src}"', f'import "{rule_name}"')
            (inc / demo).write_text(text)
        return inc, ["demo_p2p.proto", "demo_pgv.proto"]
    except Exception:
        # Implementation's protos are unusable; compile our own (it cannot have registered the packages).
        return PROTO_DIR, ["p2p_validate.proto", "validate.proto", "demo_p2p.proto", "demo_pgv.proto"]


def build_base() -> Path:
    """Compile the demo message modules used by the runtime and code-generation flows."""
    global _inc_dir
    gen = _gen()
    _inc_dir, protos = _stage_demo()
    _run([sys.executable, "-m", "grpc_tools.protoc", f"-I{_inc_dir}", f"--python_out={gen}", *protos])
    return gen


def build_plugin():
    """Run the protoc plugin and import the generated ``demo_p2p_p2p`` model module (cached)."""
    global _plugin_done
    gen = _gen()
    inc = _inc_dir if _inc_dir is not None else _stage_demo()[0]
    if not _plugin_done:
        _run(
            [
                sys.executable, "-m", "grpc_tools.protoc", f"-I{inc}", f"--python_out={gen}",
                f"--protobuf-to-pydantic_out=config_path={PLUGIN_CONFIG}:{gen}", "demo_p2p.proto",
            ]
        )
        _plugin_done = True
    return importlib.import_module("demo_p2p_p2p")
