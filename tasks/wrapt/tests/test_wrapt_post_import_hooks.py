"""User-facing behaviour of wrapt's post-import hook mechanism:
``register_post_import_hook``, ``when_imported`` and ``notify_module_loaded``."""

import importlib
import sys
import types

import wrapt


def test_hook_fires_on_import_via_register_and_when_imported(tmp_path, monkeypatch):
    """A hook registered (directly or via the ``@when_imported`` decorator)
    before import fires automatically, with the module as its argument, the
    moment the target module is first imported."""

    monkeypatch.syspath_prepend(str(tmp_path))

    name1 = "wrapt_pih_real"
    (tmp_path / f"{name1}.py").write_text("ANSWER = 99\n")
    importlib.invalidate_caches()  # make the freshly-written module discoverable
    sys.modules.pop(name1, None)
    received = []
    wrapt.register_post_import_hook(lambda module: received.append(module), name1)
    assert received == []  # not fired until import
    imported = __import__(name1)
    assert received == [imported] and received[0].ANSWER == 99

    name2 = "wrapt_pih_decorated"
    (tmp_path / f"{name2}.py").write_text("LOADED = True\n")
    importlib.invalidate_caches()
    sys.modules.pop(name2, None)
    seen = {}

    @wrapt.when_imported(name2)
    def on_import(module):
        seen["module"] = module

    assert callable(on_import) and "module" not in seen
    __import__(name2)
    assert seen["module"].LOADED is True


def test_hook_fires_immediately_or_via_notify_for_loaded_module():
    """Registering a hook for an already-imported module calls it immediately;
    ``notify_module_loaded`` runs the hooks registered against a module's name."""

    name = "wrapt_pih_already"
    module = types.ModuleType(name)
    module.PRESENT = 1
    sys.modules[name] = module
    try:
        fired = []
        wrapt.register_post_import_hook(lambda m: fired.append(m), name)
        assert fired == [module]
    finally:
        sys.modules.pop(name, None)

    notify_name = "wrapt_pih_notify"
    sys.modules.pop(notify_name, None)
    results = []
    wrapt.register_post_import_hook(lambda m: results.append(m.__name__), notify_name)
    assert results == []
    wrapt.notify_module_loaded(types.ModuleType(notify_name))
    assert results == [notify_name]
