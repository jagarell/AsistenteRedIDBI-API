"""Configuración del motor de chat leída de variables de entorno."""
import os


class ChatSettings:
    # 'builtin' (reglas, por defecto), 'flowise' o 'openai'.
    proposal_engine: str = os.getenv("CHAT_PROPOSAL_ENGINE", "builtin").lower()

    # Seam Flowise
    flowise_url: str = os.getenv("FLOWISE_URL", "")
    flowise_api_key: str = os.getenv("FLOWISE_API_KEY", "")
    flowise_chatflow_id: str = os.getenv("FLOWISE_CHATFLOW_ID", "")

    # Seam OpenAI
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    request_timeout: float = float(os.getenv("CHAT_HTTP_TIMEOUT", "20"))


settings = ChatSettings()
