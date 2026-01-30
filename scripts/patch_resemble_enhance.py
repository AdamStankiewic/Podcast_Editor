"""
Patch resemble-enhance to make deepspeed import optional.

deepspeed is only needed for training, not inference. On Windows it cannot
be built, so we wrap the import in try/except to allow inference to work.

Usage:
    python scripts/patch_resemble_enhance.py
"""
import importlib
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
    train_py = pkg_dir / "enhancer" / "train.py"

    if not train_py.exists():
        print(f"Could not find {train_py}")
        sys.exit(1)

    content = train_py.read_text(encoding="utf-8")

    # Check if already patched
    if "except ImportError" in content and "DeepSpeedConfig = None" in content:
        print("Already patched!")
        return

    # Replace the hard import with a try/except
    old = "from deepspeed import DeepSpeedConfig"
    new = (
        "try:\n"
        "    from deepspeed import DeepSpeedConfig\n"
        "except ImportError:\n"
        "    DeepSpeedConfig = None  # deepspeed only needed for training, not inference"
    )

    if old not in content:
        print(f"Could not find the deepspeed import line in {train_py}")
        print("The file may have already been modified or the package version changed.")
        sys.exit(1)

    patched = content.replace(old, new)
    train_py.write_text(patched, encoding="utf-8")
    print(f"Patched {train_py}")
    print("deepspeed import is now optional - inference will work without it.")


if __name__ == "__main__":
    patch()
