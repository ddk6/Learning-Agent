from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# 用源码位置推导项目根目录，而不是写死绝对路径。
# 这样项目文件夹改名或移动后，notes/、data/ 等路径仍然能正常工作。
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    notes_dir: Path
    data_dir: Path
    memory_file: Path
    proposal_file: Path
    database_file: Path
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    temperature: float

    @property
    def has_llm(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)


def _load_dotenv(path: Path) -> None:
    # 轻量 dotenv 加载器：只把 .env 中的 KEY=VALUE 放进环境变量。
    # 不打印内容，避免 API Key 等敏感信息进入终端或日志。
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def load_config() -> AppConfig:
    # 配置是运行时边界：路径、模型、温度等都在这里集中生成。
    # Agent 和工具层只消费 AppConfig，避免到处读取环境变量。
    _load_dotenv(PROJECT_ROOT / ".env")

    data_dir = PROJECT_ROOT / "data"
    notes_dir = PROJECT_ROOT / "notes"
    data_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        project_root=PROJECT_ROOT,
        notes_dir=notes_dir,
        data_dir=data_dir,
        memory_file=data_dir / "memory.json",
        proposal_file=data_dir / "proposals.json",
        database_file=data_dir / "learning_agent.db",
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        openai_model=os.environ.get("OPENAI_MODEL", "").strip(),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
        temperature=_float_env("OPENAI_TEMPERATURE", 0.2),
    )
