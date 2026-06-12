"""Semantic embeddings for news items via Amazon Titan (Bedrock).

Each item gets one vector computed from its title plus Claude-written short
summary — the title alone is too thin (different outlets headline different
facets of the same event), and the raw article body is too noisy. Vectors are
unit-normalized at the source so cosine similarity is a plain dot product.

Uses the EC2 instance role for credentials (no API keys). Titan V2 embeds one
text per call; at the pipeline's volume (~50-100 new items/day) that is
pennies per month and seconds per run.
"""

from __future__ import annotations

import json
import logging
import struct
from typing import Optional

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "amazon.titan-embed-text-v2:0"
DEFAULT_REGION = "us-east-1"
DEFAULT_DIMENSIONS = 512  # plenty for clustering; halves storage vs 1024

# Titan V2 caps input around 8k tokens; we stay far below it but guard anyway.
_MAX_CHARS = 8000


def _is_transient_aws_error(exc: BaseException) -> bool:
    code = getattr(getattr(exc, "response", None), "get", lambda *_: None)("Error", {})
    code = code.get("Code", "") if isinstance(code, dict) else ""
    return code in ("ThrottlingException", "ServiceUnavailableException",
                    "ModelTimeoutException", "InternalServerException")


class TitanEmbedder:
    """Embeds texts with Bedrock Titan; returns unit-normalized float vectors."""

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        region: str = DEFAULT_REGION,
        dimensions: int = DEFAULT_DIMENSIONS,
        client=None,
    ):
        self.model_id = model_id
        self.dimensions = dimensions
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "bedrock-runtime", region_name=region,
                config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
            )
        self.client = client

    @retry(
        retry=retry_if_exception(_is_transient_aws_error),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        reraise=True,
    )
    def embed(self, text: str) -> "list[float]":
        body = json.dumps({
            "inputText": text[:_MAX_CHARS],
            "dimensions": self.dimensions,
            "normalize": True,
        })
        response = self.client.invoke_model(modelId=self.model_id, body=body)
        payload = json.loads(response["body"].read())
        return payload["embedding"]


def item_embed_text(title: str, short_summary: Optional[str], summary: Optional[str]) -> str:
    """The canonical text an item is embedded from.

    Title plus the best available summary. The Claude-written short summary is
    the ideal semantic fingerprint (event-focused, denoised); fall back to the
    long summary, then title alone, for old rows that predate those fields.
    """
    body = (short_summary or "").strip() or (summary or "").strip()
    return f"{title.strip()}\n{body}" if body else title.strip()


def pack_vector(vector: "list[float]") -> bytes:
    """float32 little-endian blob for SQLite storage."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> "list[float]":
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: "list[float]", b: "list[float]") -> float:
    """Cosine similarity. Vectors are normalized at the source, so this is a
    dot product — but normalize defensively in case a foreign vector slips in."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def mean_vector(vectors: "list[list[float]]") -> "list[float]":
    """Centroid of a set of vectors (not re-normalized; cosine() handles norm)."""
    if not vectors:
        return []
    n = len(vectors)
    return [sum(col) / n for col in zip(*vectors)]
