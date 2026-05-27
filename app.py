import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

from everydayai_chatbot.conversation_db import (
    ensure_chainlit_schema,
    get_database_url,
    to_sqlalchemy_async_url,
)
from everydayai_chatbot.knowledge import build_query_engine as build_rag_query_engine
from everydayai_chatbot.knowledge import load_index
from everydayai_chatbot.settings import get_openai_api_key, load_settings


SETTINGS = load_settings()


@cl.data_layer
def get_data_layer():
    database_url = get_database_url()
    if not database_url:
        return None

    return SQLAlchemyDataLayer(conninfo=to_sqlalchemy_async_url(database_url))


@cl.cache
def get_index():
    return load_index(SETTINGS, get_openai_api_key())


def build_query_engine():
    return build_rag_query_engine(
        settings=SETTINGS,
        index=get_index(),
        api_key=get_openai_api_key(),
    )


async def ensure_conversation_logging_ready() -> None:
    try:
        await ensure_chainlit_schema()
    except Exception as exc:
        print(f"Could not initialize conversation logging: {exc}")


async def stream_query_response(query_text: str) -> None:
    query_engine = cl.user_session.get("query_engine")
    if query_engine is None:
        await cl.Message(content="The assistant is not ready yet. Please refresh the page.").send()
        return

    response_message = cl.Message(content="")
    await response_message.send()

    try:
        response = await cl.make_async(query_engine.query)(query_text)
        if getattr(response, "response_gen", None):
            for token in response.response_gen:
                await response_message.stream_token(token)
            await response_message.update()
            return

        response_message.content = str(response)
        await response_message.update()
    except Exception as exc:
        response_message.content = f"Sorry, I ran into an error while answering: {exc}"
        await response_message.update()


@cl.on_chat_start
async def on_chat_start() -> None:
    loading_message = cl.Message(content="Initializing the assistant...")
    await loading_message.send()

    try:
        await ensure_conversation_logging_ready()
        cl.user_session.set("query_engine", build_query_engine())
        await loading_message.remove()
        await cl.Message(content="Hi! What would you like to know about us?").send()
    except Exception as exc:
        loading_message.content = f"Startup failed: {exc}"
        await loading_message.update()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    await stream_query_response(message.content)
