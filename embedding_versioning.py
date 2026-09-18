"""Pure vector identity helpers. No persistence, routing or network side effects."""
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Optional
from urllib.parse import urlsplit


@dataclass(frozen=True)
class EmbeddingRoute:
    url: str
    api_key: str
    model_id: str
    provider_id: Optional[int]
    api_format: str
    source: str
    provider_name: Optional[str]
    profile: str


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model_id: str
    profile: str
    dim: int
    provider_id: Optional[int]


def _scaled_norm(vector):
    scale = max(abs(x) for x in vector)
    if scale == 0:
        return None
    scaled = [x / scale for x in vector]
    norm = math.sqrt(math.fsum(x*x for x in scaled))
    if not math.isfinite(scale * norm):
        return None
    return scaled, norm


def is_usable_vector(vector):
    if not isinstance(vector, list) or not vector:
        return False
    try:
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in vector):
            return False
        return _scaled_norm(vector) is not None
    except (OverflowError, ValueError, TypeError):
        return False


def cosine_similarity(a, b):
    if not is_usable_vector(a) or not is_usable_vector(b) or len(a) != len(b):
        return None
    a_scaled, a_norm = _scaled_norm(a)
    b_scaled, b_norm = _scaled_norm(b)
    value = math.fsum((x/a_norm)*(y/b_norm) for x, y in zip(a_scaled, b_scaled))
    return max(-1., min(1., value)) if math.isfinite(value) else None


def embedding_endpoint_identity(url):
    parsed = urlsplit(url)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('invalid embedding endpoint')
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    port = parsed.port or (443 if parsed.scheme.lower() == 'https' else 80)
    return f'{parsed.scheme.lower()}://{host}:{port}{parsed.path.rstrip("/")}'


def embedding_profile_for_route(route):
    source_tag = f'provider:{route.provider_id}' if route.source == 'provider' else 'env'
    recipe = ['emb-v1', source_tag, embedding_endpoint_identity(route.url), route.model_id, route.api_format, 'text-v1']
    return hashlib.sha256(json.dumps(recipe,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


def embedding_source_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def build_memory_embedding_text(title, content):
    return f'{title} {content}' if title else content


def build_file_chunk_embedding_text(content):
    return content


def embedding_db_payload(result, source_text):
    if not isinstance(result, EmbeddingResult) or not is_usable_vector(result.vector) or result.dim != len(result.vector):
        return (None,)*5
    return (json.dumps(result.vector,allow_nan=False), result.profile, result.model_id,
            result.dim, embedding_source_hash(source_text))


def classify_embedding_row(row_embedding, row_profile, row_dim, row_source_hash, current_profile, current_source_text):
    try:
        vector = json.loads(row_embedding) if isinstance(row_embedding, str) else row_embedding
    except (ValueError, TypeError):
        return 'missing'
    if not is_usable_vector(vector):
        return 'missing'
    if row_profile != current_profile or row_dim != len(vector) or row_source_hash != embedding_source_hash(current_source_text):
        return 'stale'
    return 'current'
