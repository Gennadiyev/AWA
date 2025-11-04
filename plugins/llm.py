"""
Module for interacting with LLMs using OpenAI's AsyncOpenAI client.

Provides functionality to initialize multiple LLM clients based on the configuration file in `plugins/configs/llm.json`.

The key names of the configuration dictionary correspond to the `model` parameter in the `query()` function.
"""

import json
from pathlib import Path

import httpx
from openai import AsyncOpenAI


# Global dict to store initialized clients
_clients: dict[str, AsyncOpenAI] = {}
_config: dict = {}


def _load_config():
    """Load LLM configuration from llm.json"""
    config_path = Path(__file__).parent / "configs" / "llm.json"

    if not config_path.exists():
        raise FileNotFoundError(f"LLM config file not found: {config_path}")

    with open(config_path, "r") as f:
        return json.load(f)


def _initialize_clients():
    """Initialize all LLM clients based on configuration"""
    global _clients, _config

    _config = _load_config()

    for client_name, client_config in _config.items():
        # Extract config values
        base_url = client_config.get("base_url")
        api_key = client_config.get("api_key")
        proxy = client_config.get("proxy")

        # Create httpx client if proxy is specified
        http_client = None
        if proxy:
            http_client = httpx.AsyncClient(proxy=proxy)

        # Initialize AsyncOpenAI client
        _clients[client_name] = AsyncOpenAI(
            api_key=api_key, base_url=base_url, http_client=http_client
        )


# Initialize clients on module load
_initialize_clients()


async def query(message: str, model: str, system_message: str = "") -> str:
    """
    Send a query to the LLM and get a response.

    Args:
        message: User message to send
        model: Client name (key from config) to use (required)
        system_message: Optional system message for context

    Returns:
        Response text from the LLM
    """
    # Get the client based on the model name
    if model not in _clients:
        raise ValueError(
            f"Model '{model}' not found in configuration. "
            f"Available models: {', '.join(_clients.keys())}"
        )

    client = _clients[model]

    # Get the actual model_id from config
    model_id = _config[model].get("model_id")
    if not model_id:
        raise ValueError(f"No model_id specified for client '{model}' in config")

    # Build messages
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": message})

    # Make async API call
    response = await client.chat.completions.create(
        model=model_id, messages=messages, extra_body={"thinking": {"type": "disabled"}}
    )

    content = response.choices[0].message.content
    return content if content is not None else ""
