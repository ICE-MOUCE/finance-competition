"""Launch the RAG API without inheriting the ModelArts torch_npu package."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path




ROOT = Path(__file__).resolve().parent / "ipo_rag_eval_final"
RAG_SITE = ROOT / ".venv_rag_npu" / "lib" / "python3.11" / "site-packages"
SHIMS = Path(__file__).resolve().parent / "rag_cpu_shims"
PROJECT_SITE = ROOT / ".venv" / "lib" / "python3.11" / "site-packages"
SYSTEM_SITE = Path("/home/ma-user/miniconda/envs/torch-2.9/lib/python3.11/site-packages")
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(SHIMS))
sys.path.insert(2, str(RAG_SITE))
if SYSTEM_SITE.is_dir():
    sys.path.insert(3, str(SYSTEM_SITE))
sys.path.insert(4, str(PROJECT_SITE))
sys.argv = [str(ROOT / "scripts" / "run_rag_api.py"), *sys.argv[1:]]
runpy.run_path(str(ROOT / "scripts" / "run_rag_api.py"), run_name="__main__")
