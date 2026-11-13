"""Standalone worker entry point: never execute the web application's __init__.

The web package imports routers and database services. A speech subprocess
must load only the voice modules, even when its environment has those installed.
"""
import importlib.util
from pathlib import Path
import sys
import types


def main():
    root = Path(__file__).resolve().parent
    package = types.ModuleType("_nova_voice_worker")
    package.__path__ = [str(root)]
    sys.modules[package.__name__] = package
    name = package.__name__ + ".local_voice_demo"
    spec = importlib.util.spec_from_file_location(name, root / "local_voice_demo.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.main()


if __name__ == "__main__":
    main()
