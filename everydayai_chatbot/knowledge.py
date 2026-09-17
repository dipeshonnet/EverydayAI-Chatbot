import hashlib
import json
from functools import lru_cache
from pathlib import Path

from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.fastembed import FastEmbedEmbedding
from tokenizers import Tokenizer

from everydayai_chatbot.groq import build_llm
from everydayai_chatbot.prompts import QA_PROMPT
from everydayai_chatbot.settings import AppSettings


SUPPORTED_DOCUMENT_EXTENSIONS = {".txt"}


@lru_cache(maxsize=1)
def get_embedding_model(model_name: str, cache_dir: str) -> FastEmbedEmbedding:
    return FastEmbedEmbedding(
        model_name=model_name,
        cache_dir=cache_dir,
        providers=["CPUExecutionProvider"],
        threads=1,
        # Keep inference within small hosting plans' memory limits.
        embed_batch_size=1,
        enable_cpu_mem_arena=False,
    )


def build_node_parser(settings: AppSettings, embed_model: FastEmbedEmbedding) -> SentenceSplitter:
    # Clone FastEmbed's actual model tokenizer, without changing inference settings.
    # Truncation/padding must be disabled for accurate counts of long documents.
    model_tokenizer = embed_model._model.model.tokenizer
    tokenizer = Tokenizer.from_str(model_tokenizer.to_str())
    truncation = tokenizer.truncation
    if truncation and settings.chunk_size > truncation["max_length"] - tokenizer.num_special_tokens_to_add(False):
        raise RuntimeError("CHUNK_SIZE exceeds the embedding model's input limit. Reduce CHUNK_SIZE.")
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return SentenceSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        tokenizer=lambda text: tokenizer.encode(text, add_special_tokens=False).ids,
    )


def load_index(settings: AppSettings) -> VectorStoreIndex:
    fingerprint = get_index_fingerprint(settings)
    embed_model = get_embedding_model(settings.embedding_model, str(settings.embedding_cache_dir))
    parser = build_node_parser(settings, embed_model)

    if has_current_index(settings.storage_dir, settings.storage_fingerprint_file, fingerprint):
        storage_context = StorageContext.from_defaults(persist_dir=str(settings.storage_dir))
        return load_index_from_storage(storage_context, embed_model=embed_model)

    documents = read_documents(settings.data_dir)

    if documents:
        nodes = parser.get_nodes_from_documents(documents)
        index = VectorStoreIndex(nodes, embed_model=embed_model)
    else:
        index = VectorStoreIndex([], embed_model=embed_model)

    # Persist replaces index files; never recursively delete a user-configured path.
    # An interrupted write must not leave a valid cache marker behind.
    settings.storage_fingerprint_file.unlink(missing_ok=True)
    index.storage_context.persist(persist_dir=str(settings.storage_dir))
    settings.storage_fingerprint_file.write_text(fingerprint, encoding="utf-8")
    return index


def build_query_engine(settings: AppSettings, index: VectorStoreIndex, api_key: str):
    llm = build_llm(settings, api_key)
    return index.as_query_engine(
        llm=llm,
        text_qa_template=QA_PROMPT,
        streaming=True,
        similarity_top_k=settings.similarity_top_k,
        response_mode=settings.response_mode,
    )


def read_documents(data_dir: Path) -> list[Document]:
    documents: list[Document] = []
    for path in get_document_paths(data_dir):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            documents.append(Document(text=text, metadata={"source": path.name}))
    return documents


def get_data_fingerprint(data_dir: Path) -> str:
    fingerprint = hashlib.sha256()
    for path in get_document_paths(data_dir):
        fingerprint.update(path.name.encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(path.read_bytes())
        fingerprint.update(b"\0")
    return fingerprint.hexdigest()


def get_index_fingerprint(settings: AppSettings) -> str:
    configuration = {
        "version": 2,
        "documents": get_data_fingerprint(settings.data_dir),
        "embedding_provider": "fastembed",
        "embedding_model": settings.embedding_model,
        "tokenizer": "embedding-model",
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }
    return hashlib.sha256(json.dumps(configuration, sort_keys=True).encode("utf-8")).hexdigest()


def get_document_paths(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []

    return sorted(
        path
        for path in data_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_DOCUMENT_EXTENSIONS
    )


def has_current_index(storage_dir: Path, fingerprint_file: Path, fingerprint: str) -> bool:
    if not storage_dir.exists() or not fingerprint_file.exists():
        return False

    try:
        return fingerprint_file.read_text(encoding="utf-8").strip() == fingerprint
    except OSError:
        return False
