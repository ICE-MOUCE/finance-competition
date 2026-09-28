"""Compatibility shim: expose torch_npu as an unavailable CPU-only backend."""
__version__ = "0.0.0-cpu-shim"

# Transformers only needs to detect whether the optional backend is usable.
# Keeping this module importable prevents optional-feature probing from
# breaking the CPU embedding path.
npu = None
