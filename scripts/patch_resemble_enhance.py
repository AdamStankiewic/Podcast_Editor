"""
Patch resemble-enhance to remove deepspeed dependency for inference.

deepspeed is only needed for training, not inference. On Windows it cannot
be built, so we patch both inference.py files to import model classes directly
from their source modules, bypassing train.py and the entire utils/ chain
that hard-imports deepspeed.

Files patched:
  enhancer/inference.py - imports Enhancer, HParams from enhancer.py, hparams.py
  denoiser/inference.py - imports Denoiser, HParams from denoiser.py, hparams.py

Import chain WITHOUT patch (fails without deepspeed):
  inference.py -> train.py -> utils/__init__.py -> distributed.py -> import deepspeed
                                                -> engine.py      -> import deepspeed

Import chain WITH patch (works everywhere):
  inference.py -> enhancer.py / denoiser.py (model class)
               -> hparams.py               (HParams class)
               (train.py is never loaded)

Usage:
    pip install resemble-enhance --no-deps
    python scripts/patch_resemble_enhance.py
"""
import sys
from pathlib import Path


PATCHES = [
    {
        "file": ("enhancer", "inference.py"),
        "old": "from .train import Enhancer, HParams",
        "new": (
            "from .enhancer import Enhancer  # patched: bypass train.py to avoid deepspeed\n"
            "from .hparams import HParams    # patched: bypass train.py to avoid deepspeed"
        ),
        "check": "from .enhancer import Enhancer",
    },
    {
        "file": ("denoiser", "inference.py"),
        "old": "from .train import Denoiser, HParams",
        "new": (
            "from .denoiser import Denoiser  # patched: bypass train.py to avoid deepspeed\n"
            "from .hparams import HParams    # patched: bypass train.py to avoid deepspeed"
        ),
        "check": "from .denoiser import Denoiser",
    },
]


def patch():
    try:
        import resemble_enhance
    except ImportError:
        print("resemble-enhance is not installed. Install it first:")
        print("  pip install resemble-enhance --no-deps")
        sys.exit(1)

    pkg_dir = Path(resemble_enhance.__file__).parent
    patched_count = 0
    skipped_count = 0

    for p in PATCHES:
        filepath = pkg_dir.joinpath(*p["file"])

        if not filepath.exists():
            print(f"WARNING: Could not find {filepath}, skipping")
            continue

        content = filepath.read_text(encoding="utf-8")

        # Check if already patched
        if p["check"] in content:
            print(f"Already patched: {filepath.name}")
            skipped_count += 1
            continue

        if p["old"] not in content:
            print(f"WARNING: Could not find expected import in {filepath}")
            print(f"  Expected: {p['old']}")
            continue

        patched_content = content.replace(p["old"], p["new"])
        filepath.write_text(patched_content, encoding="utf-8")
        print(f"Patched: {filepath}")
        patched_count += 1

    print()
    if patched_count > 0:
        print(f"Done! Patched {patched_count} file(s).")
    if skipped_count > 0:
        print(f"Skipped {skipped_count} file(s) (already patched).")
    if patched_count == 0 and skipped_count == 0:
        print("Nothing to patch.")
    else:
        print("Inference will now work without deepspeed installed.")


if __name__ == "__main__":
    patch()
