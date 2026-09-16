# EverydayAI Chainlit Chatbot

This repo contains a Chainlit chatbot deployed on Railway with native Chainlit conversation persistence and a separate Railway dashboard service for viewing logged conversations.

## Groq setup

The assistant uses Groq for replies and local CPU embeddings for knowledge-file search. An OpenAI API key is not required. The OpenAI Python client remains a dependency because Groq supports its API protocol; all chat requests are explicitly routed to `https://api.groq.com/openai/v1`.

1. Use Python 3.12 and install `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` only if you do not already have one. Set `GROQ_API_KEY` to your Groq key, preserving any existing `DATABASE_URL`. Never commit `.env`.
3. Run `chainlit run app.py`.

The defaults are `CHAT_MODEL=openai/gpt-oss-20b`, `CHAT_REASONING_EFFORT=low`, and `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`. GPT-OSS is an open-weight model hosted by Groq; it does not use OpenAI's API or credentials. When selecting another Groq model, set a reasoning effort it supports; an explicitly empty `CHAT_REASONING_EFFORT` omits that parameter. Remove old `CHAT_MODEL=gpt-...` / `grok-...` or `EMBEDDING_MODEL=text-embedding-...` overrides.

FastEmbed downloads the English embedding model on first use and runs it on the server CPU. Initial setup needs internet access and extra startup time, disk space, and memory. Downloads are cached in `EMBEDDING_CACHE_DIR` (default `.cache/embeddings`), separately from `STORAGE_DIR` (default `storage`). These directories must remain separate. On ephemeral hosting, downloads repeat after deployments unless the cache is on a persistent volume.

Existing OpenAI indexes rebuild automatically. The cache fingerprint includes documents, embedding provider/model, and chunk settings. Document splitting uses the embedding model's tokenizer, with `CHUNK_SIZE=384` and `CHUNK_OVERLAP=64`; oversized chunks are rejected to prevent silent truncation. Changes take effect after restarting the chatbot.

### Railway

Set `GROQ_API_KEY` on the **chatbot service → Variables**, then deploy the updated code. If you previously stored the Groq key under `XAI_API_KEY`, rename that variable to `GROQ_API_KEY`; Groq and Grok/xAI are different providers. Preserve `DATABASE_URL` and the dashboard's credentials. `OPENAI_API_KEY` is no longer used and may be removed. No dashboard configuration or database migration is needed. If using a Railway volume, set separate paths such as `STORAGE_DIR=/app/cache/index` and `EMBEDDING_CACHE_DIR=/app/cache/embeddings` under its mount.

### Validation

Run `python -m unittest discover -s tests -v` for automated regression tests. The suite includes local conversation writes and authenticated dashboard reads using a temporary SQLite database; it does not touch Railway's production database.

Run `python -m scripts.validate_groq` to test authentication and a short real response, or `python -m scripts.validate_groq --rag` to additionally build/reopen the local index and test retrieval with a streamed Groq answer. These checks make small paid API requests, remove `OPENAI_API_KEY` from the test process, and never print credentials or raw provider errors. They distinguish authentication, credits/billing, model permissions, rate limits, and connection failures.

After deployment, ask a knowledge question in the hosted chatbot and confirm the answer is streamed and recorded in the conversation dashboard. Local validation does not verify Railway's configured key.

For the reusable setup guide, see:

- [Chainlit Conversation Logging And Dashboard On Railway](docs/chainlit-railway-conversation-dashboard.md)

## Code Structure

- `app.py`: Chainlit entrypoint and chat event handlers.
- `everydayai_chatbot/settings.py`: environment variables, model names, paths, and RAG tuning.
- `everydayai_chatbot/prompts.py`: assistant response policy and prompt text.
- `everydayai_chatbot/knowledge.py`: training document loading, fingerprinting, index rebuilds, and query engine creation.
- `everydayai_chatbot/conversation_db.py`: Chainlit PostgreSQL persistence helpers.
- `data/`: RAG knowledge files. Add or edit `.txt` files here to update training content.
- `dashboard/`: separate FastAPI conversation dashboard service.
