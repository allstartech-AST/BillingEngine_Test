"""List models available to the configured LLM provider."""

from app.config import groq_base_url, llm_provider_name, load_env_files, openai_api_key

load_env_files()


def main() -> None:
    api_key = openai_api_key()
    provider_name = llm_provider_name()
    if not api_key:
        api_key_name = "GROQ_API_KEY" if provider_name == "Groq" else "OPENAI_API_KEY"
        print(f"{api_key_name} is not set in backend/.env.local")
        return

    from openai import OpenAI

    if provider_name == "Groq":
        client = OpenAI(api_key=api_key, base_url=groq_base_url())
    else:
        client = OpenAI(api_key=api_key)
    for model in client.models.list():
        print(model.id)


if __name__ == "__main__":
    main()
