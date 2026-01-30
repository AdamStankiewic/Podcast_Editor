"""
Patch resemble-enhance to make deepspeed import optional.

deepspeed is only needed for training, not inference. On Windows it cannot
be built, so we patch inference.py to import Enhancer and HParams directly
from their source modules, bypassing train.py and the entire utils/ chain
that hard-imports deepspeed.

Import chain WITHOUT patch (fails on Windows):
  inference.py -> train.py -> utils/__init__.py -> distributed.py -> import deepspeed (FAIL)
                                                -> engine.py      -> import deepspeed (FAIL)

Import chain WITH patch (works everywhere):
  inference.py -> enhancer.py (Enhancer class)
               -> hparams.py  (HParams class)
               (train.py is never loaded)

Usage:
    python scripts/patch_resemble_enhance.py
"""
import sys
from pathlib import Path


def patch():
    try:
        import resemble_enhance
    except ImportError:
        print("resemble-enhance is not installed. Install it first:")
        print("  pip install resemble-enhance --no-deps")
        sys.exit(1)

    pkg_dir = Path(resemble_enhance.__file__).parent
    inference_py = pkg_dir / "enhancer" / "inference.py"

    if not inference_py.exists():
        print(f"Could not find {inference_py}")
        sys.exit(1)

    content = inference_py.read_text(encoding="utf-8")

    # Check if already patched
    if "from .enhancer import Enhancer" in content and "from .hparams import HParams" in content:
        print("Already patched!")
        return

    # Replace: from .train import Enhancer, HParams
    # With direct imports that bypass train.py (and its deepspeed dependency chain)
    old = "from .train import Enhancer, HParams"
    new = (
        "from .enhancer import Enhancer  # patched: bypass train.py to avoid deepspeed\n"
        "from .hparams import HParams    # patched: bypass train.py to avoid deepspeed"
    )

    if old not in content:
        print(f"Could not find 'from .train import Enhancer, HParams' in {inference_py}")
        print("The file may have already been modified or the package version changed.")
        sys.exit(1)

    patched = content.replace(old, new)
    inference_py.write_text(patched, encoding="utf-8")
    print(f"Patched {inference_py}")
    print("inference.py now imports directly from enhancer.py and hparams.py,")
    print("bypassing train.py and its deepspeed dependency chain.")


if __name__ == "__main__":
    patch()
