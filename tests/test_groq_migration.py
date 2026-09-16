import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from llama_index.core import Document, MockEmbedding, Settings
from llama_index.core.schema import MetadataMode
from openai import APIConnectionError, APIStatusError, APITimeoutError
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from everydayai_chatbot import knowledge
from everydayai_chatbot.groq import build_llm, describe_api_error
from everydayai_chatbot.settings import get_groq_api_key, load_settings


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {key: value for key, value in os.environ.items() if key not in {"GROQ_API_KEY", "OPENAI_API_KEY", "CHAT_MODEL", "CHAT_REASONING_EFFORT", "EMBEDDING_MODEL", "EMBEDDING_CACHE_DIR", "DATA_DIR", "STORAGE_DIR", "CHUNK_SIZE", "CHUNK_OVERLAP"}}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        with patch("everydayai_chatbot.settings.load_dotenv"):
            self.settings = load_settings(self.root)
        self.settings.data_dir.mkdir()
        self.document = self.settings.data_dir / "company.txt"
        self.document.write_text("Everyday AI builds business chatbots and automations.", encoding="utf-8")

    def test_key_is_required_even_when_openai_key_exists(self):
        os.environ["OPENAI_API_KEY"] = "unused-test-key"
        with self.assertRaisesRegex(RuntimeError, "GROQ_API_KEY is missing"):
            get_groq_api_key()
        os.environ["GROQ_API_KEY"] = "  test-groq-key  "
        self.assertEqual(get_groq_api_key(), "test-groq-key")

    def test_defaults_and_cache_path_validation(self):
        self.assertEqual(self.settings.chat_model, "openai/gpt-oss-20b")
        self.assertEqual(self.settings.reasoning_effort, "low")
        self.assertEqual((self.settings.chunk_size, self.settings.chunk_overlap), (384, 64))
        os.environ["EMBEDDING_CACHE_DIR"] = "storage/models"
        with self.assertRaisesRegex(RuntimeError, "outside STORAGE_DIR"):
            load_settings(self.root)

    def test_invalid_chunk_settings_fail(self):
        for size, overlap in [(0, 0), (64, 64), (64, -1)]:
            with self.subTest(size=size, overlap=overlap), patch.dict(os.environ, {"CHUNK_SIZE": str(size), "CHUNK_OVERLAP": str(overlap)}):
                with self.assertRaises(RuntimeError):
                    load_settings(self.root)

    def test_real_adapter_routes_stream_to_groq(self):
        requests = []

        def handler(request):
            requests.append(request)
            event = {"id": "test", "object": "chat.completion.chunk", "created": 0, "model": "openai/gpt-oss-20b", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hello"}, "finish_reason": None}]}
            return httpx.Response(200, text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n", headers={"content-type": "text/event-stream"})

        llm = build_llm(self.settings, "test-groq-key")
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            llm._http_client = client
            self.assertEqual("".join(chunk.delta for chunk in llm.stream_complete("Hi")), "Hello")
        self.assertEqual(str(requests[0].url), "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(requests[0].headers["authorization"], "Bearer test-groq-key")
        body = json.loads(requests[0].content)
        self.assertEqual(body["model"], "openai/gpt-oss-20b")
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertTrue(body["stream"])
        llm = build_llm(replace(self.settings, reasoning_effort=""), "test-key")
        self.assertNotIn("reasoning_effort", llm.additional_kwargs)

    def make_embedding(self):
        tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "hello": 1}, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = Whitespace()
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(length=512)
        embedding = MockEmbedding(embed_dim=8)
        object.__setattr__(embedding, "_model", SimpleNamespace(model=SimpleNamespace(tokenizer=tokenizer)))
        return embedding

    def test_splitter_counts_untruncated_model_tokens(self):
        embedding = self.make_embedding()
        parser = knowledge.build_node_parser(self.settings, embedding)
        nodes = parser.get_nodes_from_documents([Document(text="hello " * 1200)])
        self.assertGreater(len(nodes), 3)
        for node in nodes:
            self.assertLessEqual(len(parser._tokenizer(node.get_content(metadata_mode=MetadataMode.EMBED))), 384)
        self.assertEqual(embedding._model.model.tokenizer.truncation["max_length"], 512)
        self.assertEqual(embedding._model.model.tokenizer.padding["length"], 512)
        with self.assertRaisesRegex(RuntimeError, "input limit"):
            knowledge.build_node_parser(replace(self.settings, chunk_size=1024), embedding)

    def test_index_rebuild_reload_and_empty_documents(self):
        embedding = self.make_embedding()
        # Setting no global embedding prevents accidental implicit OpenAI resolution.
        with patch.object(Settings, "_embed_model", None), patch.object(knowledge, "get_embedding_model", return_value=embedding):
            index = knowledge.load_index(self.settings)
            self.assertEqual(len(index.docstore.docs), 1)
            with patch.object(knowledge, "read_documents", side_effect=AssertionError("Unexpected rebuild")):
                reopened = knowledge.load_index(self.settings)
                self.assertTrue(reopened.as_retriever().retrieve("chatbots"))
            # Legacy data-only markers must trigger a rebuild.
            self.settings.storage_fingerprint_file.write_text(knowledge.get_data_fingerprint(self.settings.data_dir))
            with patch.object(knowledge, "read_documents", wraps=knowledge.read_documents) as read:
                knowledge.load_index(self.settings)
                read.assert_called_once()
            self.document.write_text("Updated company knowledge.", encoding="utf-8")
            rebuilt = knowledge.load_index(self.settings)
            self.assertIn("Updated", next(iter(rebuilt.docstore.docs.values())).text)
            self.document.write_text("   ", encoding="utf-8")
            empty = knowledge.load_index(self.settings)
            self.assertEqual(len(empty.docstore.docs), 0)

    def test_fingerprint_tracks_embedding_and_chunk_configuration(self):
        initial = knowledge.get_index_fingerprint(self.settings)
        for settings in [replace(self.settings, embedding_model="another-model"), replace(self.settings, chunk_size=256), replace(self.settings, chunk_overlap=32)]:
            self.assertNotEqual(initial, knowledge.get_index_fingerprint(settings))
        self.assertEqual(initial, knowledge.get_index_fingerprint(replace(self.settings, chat_model="another-chat-model")))

    def test_interrupted_persistence_does_not_leave_valid_marker(self):
        with patch.object(knowledge, "get_embedding_model", return_value=self.make_embedding()):
            knowledge.load_index(self.settings)
            self.document.write_text("Changed document.", encoding="utf-8")
            with patch("llama_index.core.storage.storage_context.StorageContext.persist", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    knowledge.load_index(self.settings)
            self.assertFalse(self.settings.storage_fingerprint_file.exists())

    def test_errors_are_classified_without_exposing_provider_body(self):
        request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        for code, detail, expected in [(401, "bad key", "authentication"), (400, "Incorrect API key provided", "authentication"), (402, "payment", "credit"), (403, "Insufficient credits", "credit"), (403, "denied", "permissions"), (404, "model", "model"), (429, "slow down", "rate limit"), (400, "parameter", "rejected"), (503, "unavailable", "temporarily")]:
            with self.subTest(code=code, detail=detail):
                error = APIStatusError("secret-test-value", response=httpx.Response(code, request=request), body={"error": detail, "key": "secret-test-value"})
                message = describe_api_error(error)
                self.assertIn(expected, message)
                self.assertNotIn("secret-test-value", message)
        self.assertIn("network", describe_api_error(APIConnectionError(request=request)))
        self.assertIn("timed out", describe_api_error(APITimeoutError(request=request)))


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamed_reply_updates_chainlit_message(self):
        import app

        message = SimpleNamespace(content="", send=AsyncMock(), stream_token=AsyncMock(), update=AsyncMock())
        engine = Mock()
        engine.query.return_value = SimpleNamespace(response_gen=iter(["Hello", " world"]))
        with patch.object(app.cl, "Message", return_value=message), patch.object(app.cl.user_session, "get", return_value=engine):
            await app.stream_query_response("Hi")
        self.assertEqual(message.stream_token.await_count, 2)
        message.send.assert_awaited_once()
        message.update.assert_awaited_once()

    async def test_stream_failure_shows_safe_error(self):
        import app

        def failing_stream():
            yield "Partial reply"
            raise RuntimeError("secret-test-value")

        message = SimpleNamespace(content="", send=AsyncMock(), stream_token=AsyncMock(), update=AsyncMock())
        engine = Mock()
        engine.query.return_value = SimpleNamespace(response_gen=failing_stream())
        with patch.object(app.cl, "Message", return_value=message), patch.object(app.cl.user_session, "get", return_value=engine):
            await app.stream_query_response("Hi")
        self.assertNotIn("secret-test-value", message.content)
        message.update.assert_awaited_once()

    async def test_persistence_factory_keeps_database_configuration(self):
        import app

        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:password@localhost/test"}), patch.object(app, "SQLAlchemyDataLayer") as layer:
            app.get_data_layer()
            layer.assert_called_once_with(conninfo="postgresql+asyncpg://user:password@localhost/test")
        with patch.dict(os.environ, {"DATABASE_URL": ""}):
            self.assertIsNone(app.get_data_layer())


if __name__ == "__main__":
    unittest.main()
