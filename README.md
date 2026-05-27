# EverydayAI Chainlit Chatbot

This repo contains a Chainlit chatbot deployed on Railway with native Chainlit conversation persistence and a separate Railway dashboard service for viewing logged conversations.

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
