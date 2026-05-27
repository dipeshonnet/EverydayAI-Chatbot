import hashlib
import shutil
from pathlib import Path

from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI

from everydayai_chatbot.prompts import QA_PROMPT
from everydayai_chatbot.settings import AppSettings


SUPPORTED_DOCUMENT_EXTENSIONS = {".txt"}


def load_index(settings: AppSettings, api_key: str) -> VectorStoreIndex:
    fingerprint = get_data_fingerprint(settings.data_dir)

    if has_current_index(settings.storage_dir, settings.storage_fingerprint_file, fingerprint):
        storage_context = StorageContext.from_defaults(persist_dir=str(settings.storage_dir))
        return load_index_from_storage(storage_context)

    if settings.storage_dir.exists():
        shutil.rmtree(settings.storage_dir)

    embed_model = OpenAIEmbedding(api_key=api_key, model=settings.embedding_model)
    documents = read_documents(settings.data_dir)

    if documents:
        parser = SentenceSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        nodes = parser.get_nodes_from_documents(documents)
        index = VectorStoreIndex(nodes, embed_model=embed_model)
    else:
        index = VectorStoreIndex([], embed_model=embed_model)

    index.storage_context.persist(persist_dir=str(settings.storage_dir))
    settings.storage_fingerprint_file.write_text(fingerprint, encoding="utf-8")
    return index


def build_query_engine(settings: AppSettings, index: VectorStoreIndex, api_key: str):
    llm = OpenAI(
        api_key=api_key,
        model=settings.chat_model,
        temperature=settings.temperature,
    )
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

