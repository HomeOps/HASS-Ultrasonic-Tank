"""Load model.py from the working tree or from a git revision, and build its parameters."""
from __future__ import annotations

from dataclasses import fields, replace
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = REPO / "custom_components" / "ultrasonic_tank" / "model.py"


def load_model(ref: str | None = None):
    """Import model.py on its own, so the package __init__ (Home Assistant) is not needed.

    With ``ref`` (a git tag or commit) the model.py from that revision is loaded instead
    of the working tree, so a release can be replayed side by side with the current code.
    """
    name = "ultrasonic_tank_model"
    path = MODEL_PATH
    if ref:
        rel = MODEL_PATH.relative_to(REPO).as_posix()
        try:
            source = subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:{rel}"],
                                    check=True, capture_output=True, text=True, encoding="utf-8").stdout
        except subprocess.CalledProcessError as err:
            raise SystemExit(f"--baseline-ref {ref!r}: {err.stderr.strip()}") from err
        path = Path(tempfile.mkdtemp(prefix="tank-model-")) / "model.py"
        path.write_text(source, encoding="utf-8")
        name = f"ultrasonic_tank_model_{ref}".replace(".", "_").replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_parameters(model_module, overrides: list[str], utc_offset_h: float = 0.0):
    """The module's default TankParameters with the site's UTC offset (as HA sets it) and NAME=VALUE overrides."""
    params = model_module.TankParameters()
    known = {f.name for f in fields(params)}
    changes = {"utc_offset_h": utc_offset_h} if "utc_offset_h" in known else {}
    for item in overrides:
        name, sep, value = item.partition("=")
        name = name.strip()
        if not sep or name not in known:
            raise SystemExit(f"--param {item!r}: expected NAME=VALUE with NAME one of {', '.join(sorted(known))}")
        changes[name] = float(value)
    return replace(params, **changes)


def parameter_values(params) -> dict:
    return {f.name: getattr(params, f.name) for f in fields(params)}
