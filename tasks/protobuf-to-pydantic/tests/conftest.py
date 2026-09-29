"""Shared fixtures/helpers for the protobuf-to-pydantic test-suite.

Compiles the proto fixtures (and runs the protoc plugin) at collection time, then exposes helpers for
building pydantic models through each of the three generation flows.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import proto_build  # noqa: E402

# Compile the plain message modules before collection. The plugin flow is built lazily (see
# ``plugin_models``) so that a buggy plugin only fails the plugin tests, not the whole suite.
proto_build.build_base()

from plugin_config import (  # noqa: E402  (importable because proto_build put tests/ on sys.path)
    CustomCommentTemplate,
    CustomerField,
    customer_any,
    local_dict,
)
from protobuf_to_pydantic import (  # noqa: E402
    msg_to_pydantic_model,
    pydantic_model_to_py_code,
)
try:  # the reference impl memoises models in a module-level cache; reset it between conversions.
    from protobuf_to_pydantic.gen_model import clear_create_model_cache  # noqa: E402
except ImportError:  # an implementation that does not cache needs no reset.
    def clear_create_model_cache() -> None:  # type: ignore[misc]
        pass

__all__ = [
    "CustomCommentTemplate",
    "CustomerField",
    "customer_any",
    "local_dict",
    "runtime_model",
    "codegen_model",
    "plugin_models",
]


def plugin_models():
    """Flow (c): build (once) and return the protoc-plugin-generated ``demo_p2p_p2p`` model module."""
    return proto_build.build_plugin()


def runtime_model(msg_cls, **kwargs):
    """Flow (a): build a pydantic model class directly from a live protobuf message class.

    The library memoises generated models in a module-level cache keyed by message; clear it first so each
    call honours the options passed here (``pydantic_base``, ``enable_enum_name_value_desc``, ...) instead of
    returning a model cached by an earlier test.
    """
    clear_create_model_cache()
    kwargs.setdefault("local_dict", local_dict)
    # ``template`` is only passed by callers whose message uses a custom template hook (e.g. the numeric
    # messages' ``default_template = "p2p@timestamp|..."`` fields); most messages don't need one.
    return msg_to_pydantic_model(msg_cls, **kwargs)


def codegen_model(class_name, *msg_cls, **kwargs):
    """Flow (b): runtime-build model(s), serialize them to source, exec the source, return the named class.

    Exercises ``pydantic_model_to_py_code``: the returned class is reconstructed purely from generated
    source text, so its behaviour proves the emitted code is correct (no fragile string comparison).
    """
    kwargs.setdefault("local_dict", local_dict)
    clear_create_model_cache()
    models = [msg_to_pydantic_model(m, **kwargs) for m in msg_cls]
    code = pydantic_model_to_py_code(*models)
    namespace: dict = {}
    exec(compile(code, "<generated_code>", "exec"), namespace)  # noqa: S102
    if class_name not in namespace:
        raise AssertionError(f"generated code did not define {class_name!r}.\n--- generated ---\n{code}")
    return namespace[class_name]
