from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv_file(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("HKIPO_HOST", "127.0.0.1")
    port: int = int(os.getenv("HKIPO_PORT", "8000"))
    data_root: Path = Path(os.getenv("HKIPO_DATA_ROOT", "/home/ma-user/work/data"))
    runtime_root: Path = Path(
        os.getenv("HKIPO_RUNTIME_ROOT", str(PROJECT_ROOT / "runtime"))
    )
    max_pages: int = int(os.getenv("HKIPO_MAX_PAGES", "0"))
    max_evidence: int = int(os.getenv("HKIPO_MAX_EVIDENCE_PER_ANALYSIS", "12000"))
    rag_enabled: bool = os.getenv("HKIPO_RAG_ENABLED", "1") not in {"0", "false", "False"}
    rag_base_url: str = os.getenv("HKIPO_RAG_BASE_URL", "http://127.0.0.1:8000")
    rag_timeout_s: float = float(os.getenv("HKIPO_RAG_TIMEOUT_S", "45"))
    rag_top_k: int = int(os.getenv("HKIPO_RAG_TOP_K", "8"))
    rag_ranking_profile: str = os.getenv("HKIPO_RAG_RANKING_PROFILE", "hge")
    parser_backend: str = os.getenv("HKIPO_PARSER_BACKEND", "auto")
    mineru_evidence_root: Path = Path(
        os.getenv(
            "HKIPO_MINERU_EVIDENCE_ROOT",
            "/home/ma-user/work/IPO_Sentinel_Platform/ipo_rag_eval_final/data/evidence",
        )
    )
    working_evidence_limit: int = int(os.getenv("HKIPO_WORKING_EVIDENCE_LIMIT", "240"))

    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    doubao_api_key: str = os.getenv("DOUBAO_API_KEY", "")
    doubao_access_key_id: str = os.getenv("DOUBAO_ACCESS_KEY_ID", "")
    doubao_secret_access_key: str = os.getenv("DOUBAO_SECRET_ACCESS_KEY", "")
    doubao_model: str = os.getenv("DOUBAO_MODEL", "doubao-pro-32k")
    doubao_base_url: str = os.getenv(
        "DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
    )

    agent_room_auto_start: bool = os.getenv("HKIPO_AGENT_ROOM_AUTO_START", "1") not in {
        "0",
        "false",
        "False",
    }
    default_llm_provider: str = os.getenv("HKIPO_DEFAULT_LLM_PROVIDER", "deepseek")

    @property
    def database_path(self) -> Path:
        return self.runtime_root / "hkipo.sqlite3"

    @property
    def report_root(self) -> Path:
        return self.runtime_root / "reports"

    @property
    def model_root(self) -> Path:
        return self.runtime_root / "models"

    def ensure_directories(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.report_root.mkdir(parents=True, exist_ok=True)
        self.model_root.mkdir(parents=True, exist_ok=True)


settings = Settings()
