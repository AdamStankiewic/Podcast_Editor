"""
Patch resemble-enhance to work without deepspeed (Windows compatibility).

deepspeed is a training-only dependency that cannot be built on Windows.
Instead of patching individual files, this script creates a lightweight
stub 'deepspeed' package that satisfies all imports used by resemble-enhance
at inference time.

The stub provides:
  - deepspeed.init_distributed() -> no-op
  - deepspeed.DeepSpeedConfig -> dummy class
  - deepspeed.accelerator.get_accelerator() -> mock accelerator
  - deepspeed.runtime.engine.DeepSpeedEngine -> base class (nn.Module)
  - deepspeed.runtime.utils.clip_grad_norm_ -> no-op

If real deepspeed is already installed, this script does nothing.

Usage:
    pip install resemble-enhance --no-deps
    python scripts/patch_resemble_enhance.py
"""
import sys
from pathlib import Path


def _find_site_packages():
    """Find the site-packages directory for the current environment."""
    for p in sys.path:
        if "site-packages" in p and Path(p).is_dir():
            return Path(p)
    raise RuntimeError("Could not find site-packages directory")


def _is_real_deepspeed_installed():
    """Check if real deepspeed (not our stub) is installed."""
    try:
        import deepspeed
        # Our stub has a _IS_STUB attribute
        return not getattr(deepspeed, "_IS_STUB", False)
    except ImportError:
        return False


STUB_INIT = '''\
"""
Minimal deepspeed stub for resemble-enhance inference on Windows.
Only provides the classes/functions that resemble-enhance imports.
Created by scripts/patch_resemble_enhance.py
"""
_IS_STUB = True


class DeepSpeedConfig:
    """Stub - only used in training code paths."""
    def __init__(self, *args, **kwargs):
        pass


def init_distributed(*args, **kwargs):
    """Stub - distributed training not needed for inference."""
    pass
'''

STUB_ACCELERATOR = '''\
"""Stub deepspeed.accelerator module."""


class _MockAccelerator:
    def communication_backend_name(self):
        return "nccl"


def get_accelerator():
    return _MockAccelerator()
'''

STUB_RUNTIME_INIT = '''\
"""Stub deepspeed.runtime module."""
'''

STUB_RUNTIME_ENGINE = '''\
"""Stub deepspeed.runtime.engine module."""
from torch import nn


class DeepSpeedEngine(nn.Module):
    """Stub - Engine inherits from this but only uses nn.Module methods at inference."""
    def __init__(self, *args, **kwargs):
        super().__init__()

    def load_checkpoint(self, *args, **kwargs):
        pass

    def save_checkpoint(self, *args, **kwargs):
        pass

    @property
    def global_steps(self):
        return 0

    def gradient_clipping(self):
        return 1.0

    @property
    def mpu(self):
        return None

    def get_global_grad_norm(self):
        return None
'''

STUB_RUNTIME_UTILS = '''\
"""Stub deepspeed.runtime.utils module."""


def clip_grad_norm_(*args, **kwargs):
    """Stub - gradient clipping not needed at inference."""
    return 0.0
'''


def patch():
    # Check if real deepspeed is installed
    if _is_real_deepspeed_installed():
        print("Real deepspeed is already installed - no stub needed.")
        return

    site_packages = _find_site_packages()
    ds_dir = site_packages / "deepspeed"
    runtime_dir = ds_dir / "runtime"
    accelerator_dir = ds_dir / "accelerator"

    # Check if stub already exists
    if ds_dir.exists():
        init_content = (ds_dir / "__init__.py").read_text(encoding="utf-8") if (ds_dir / "__init__.py").exists() else ""
        if "_IS_STUB" in init_content:
            print("Deepspeed stub already installed.")
            return
        else:
            print(f"WARNING: {ds_dir} exists but is not our stub. Skipping.")
            return

    # Create stub package
    print(f"Creating deepspeed stub in {ds_dir}...")

    ds_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    accelerator_dir.mkdir(parents=True, exist_ok=True)

    (ds_dir / "__init__.py").write_text(STUB_INIT, encoding="utf-8")
    (accelerator_dir / "__init__.py").write_text(STUB_ACCELERATOR, encoding="utf-8")
    (runtime_dir / "__init__.py").write_text(STUB_RUNTIME_INIT, encoding="utf-8")
    (runtime_dir / "engine.py").write_text(STUB_RUNTIME_ENGINE, encoding="utf-8")
    (runtime_dir / "utils.py").write_text(STUB_RUNTIME_UTILS, encoding="utf-8")

    print("Deepspeed stub installed successfully!")
    print("resemble-enhance inference will now work without real deepspeed.")
    print()
    print("Note: This stub only supports inference. For training, install real deepspeed on Linux.")


def remove_stub():
    """Remove the stub if it exists (e.g., before installing real deepspeed)."""
    import shutil
    site_packages = _find_site_packages()
    ds_dir = site_packages / "deepspeed"

    if not ds_dir.exists():
        print("No deepspeed stub found.")
        return

    init_file = ds_dir / "__init__.py"
    if init_file.exists() and "_IS_STUB" in init_file.read_text(encoding="utf-8"):
        shutil.rmtree(ds_dir)
        print("Deepspeed stub removed.")
    else:
        print("Found real deepspeed, not removing.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--remove":
        remove_stub()
    else:
        patch()
