import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppSettings:
    base_dir: Path
    data_dir: Path
    storage_dir: Path
    storage_fingerprint_file: Path
    embedding_cache_dir: Path
    chat_model: str
    reasoning_effort: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    similarity_top_k: int
    temperature: float
    response_mode: str


def load_settings(base_dir: Path | None = None) -> AppSettings:
    root = base_dir or Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")

    data_dir = _env_path("DATA_DIR", root / "data", root)
    storage_dir = _env_path("STORAGE_DIR", root / "storage", root)
    embedding_cache_dir = _env_path("EMBEDDING_CACHE_DIR", root / ".cache" / "embeddings", root)
    if embedding_cache_dir.resolve().is_relative_to(storage_dir.resolve()):
        raise RuntimeError("EMBEDDING_CACHE_DIR must be outside STORAGE_DIR.")
    chunk_size = _env_int("CHUNK_SIZE", 384)
    chunk_overlap = _env_int("CHUNK_OVERLAP", 64)
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise RuntimeError("CHUNK_SIZE must be positive and CHUNK_OVERLAP must be smaller than CHUNK_SIZE and nonnegative.")

    return AppSettings(
        base_dir=root,
        data_dir=data_dir,
        storage_dir=storage_dir,
        storage_fingerprint_file=storage_dir / "data_fingerprint.txt",
        embedding_cache_dir=embedding_cache_dir,
        chat_model=os.getenv("CHAT_MODEL", "openai/gpt-oss-20b").strip() or "openai/gpt-oss-20b",
        reasoning_effort=os.getenv("CHAT_REASONING_EFFORT", "low").strip(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip() or "BAAI/bge-small-en-v1.5",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        similarity_top_k=_env_int("SIMILARITY_TOP_K", 4),
        temperature=_env_float("CHAT_TEMPERATURE", 0.2),
        response_mode=os.getenv("RESPONSE_MODE", "compact"),
    )


def get_groq_api_key() -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing from the environment.")
    return api_key


def _env_path(name: str, default: Path, root: Path) -> Path:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    path = Path(raw_value)
    if path.is_absolute():
        return path
    return root / path


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc
