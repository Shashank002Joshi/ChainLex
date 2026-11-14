"""Shared asynchronous Voyage transport and embedding contract for all corpora."""

import hashlib
import math
from typing import Literal

import httpx

EMBEDDING_MODEL = "voyage-finance-2"
EMBEDDING_DIMENSIONS = 1024
EMBEDDING_VERSION = 1
DEFAULT_EMBEDDING_ENDPOINT = "https://ai.mongodb.com/v1/embeddings"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def validate_vector(vector: list[float]) -> None:
    if len(vector) != EMBEDDING_DIMENSIONS or not all(
        type(value) in (int, float) and math.isfinite(value) for value in vector
    ):
        raise ValueError(f"Expected {EMBEDDING_DIMENSIONS} finite numeric dimensions")


def embedding_metadata(text: str) -> dict:
    return {
        "text_hash": text_hash(text),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_version": EMBEDDING_VERSION,
    }


def has_current_embedding(document: dict, text: str) -> bool:
    if any(document.get(key) != value for key, value in embedding_metadata(text).items()):
        return False
    vector = document.get("embedding")
    if not isinstance(vector, list):
        return False
    try:
        validate_vector(vector)
    except ValueError:
        return False
    return True


class VoyageEmbeddings:
    """Caller owns HTTP client lifecycle. Both document and query return vector lists."""

    def __init__(
        self, client: httpx.AsyncClient, api_key: str, endpoint: str = DEFAULT_EMBEDDING_ENDPOINT
    ):
        if not api_key:
            raise ValueError("CHAINLEX_VOYAGE_API_KEY is required")
        if endpoint not in {DEFAULT_EMBEDDING_ENDPOINT, "https://api.voyageai.com/v1/embeddings"}:
            raise ValueError("Unsupported Voyage endpoint")
        self.client, self.api_key, self.endpoint = client, api_key, endpoint

    async def embed(self, texts: list[str], input_type: Literal["document", "query"]):
        if input_type not in {"document", "query"}:
            raise ValueError("input_type must be document or query")
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding texts must be nonempty strings")
        response = await self.client.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"input": texts, "model": EMBEDDING_MODEL, "input_type": input_type},
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        if [item["index"] for item in data] != list(range(len(texts))):
            raise ValueError("Embedding response count/index mismatch")
        vectors = [item["embedding"] for item in data]
        for vector in vectors:
            validate_vector(vector)
        return vectors
