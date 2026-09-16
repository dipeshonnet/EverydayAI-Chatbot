"""Run explicitly: python -m scripts.validate_groq [--rag]. Uses paid Groq requests."""

import argparse
import os

from openai import OpenAI

from everydayai_chatbot.groq import GROQ_API_BASE, describe_api_error
from everydayai_chatbot.settings import get_groq_api_key, load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rag", action="store_true", help="Also verify local retrieval and a streamed answer.")
    args = parser.parse_args()
    try:
        settings = load_settings()
        # Prove neither the credential check nor retrieval needs OpenAI credentials.
        os.environ.pop("OPENAI_API_KEY", None)
        api_key = get_groq_api_key()
        kwargs = {"reasoning_effort": settings.reasoning_effort} if settings.reasoning_effort else {}
        with OpenAI(api_key=api_key, base_url=GROQ_API_BASE, timeout=30.0, max_retries=0) as client:
            response = client.chat.completions.create(
                model=settings.chat_model,
                messages=[{"role": "user", "content": "Reply with the word OK."}],
                max_tokens=256,
                temperature=settings.temperature,
                **kwargs,
            )
        if not response.choices or not (response.choices[0].message.content or "").strip():
            print("FAIL: Groq accepted the request but returned no answer.")
            return 1
        print("PASS: Groq authenticated the key and returned a nonempty answer from the configured model.")

        if args.rag:
            from everydayai_chatbot.knowledge import build_query_engine, load_index

            index = load_index(settings)
            # Exercise the persisted-index path as well as initial creation.
            index = load_index(settings)
            engine = build_query_engine(settings, index, api_key)
            response = engine.query("What services does Everyday AI offer?")
            tokens = list(response.response_gen)
            answer = "".join(tokens).strip()
            if not response.source_nodes or not answer or answer == "Empty Response":
                print("FAIL: Retrieval or the streamed Groq answer was empty.")
                return 1
            print(f"PASS: Local retrieval returned {len(response.source_nodes)} sources and Groq returned a streamed answer.")
            print("PASS: No OPENAI_API_KEY was present during validation.")
        return 0
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc) == "GROQ_API_KEY is missing from the environment.":
            print("FAIL: GROQ_API_KEY is missing from the environment.")
        else:
            print(f"FAIL: {describe_api_error(exc)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
