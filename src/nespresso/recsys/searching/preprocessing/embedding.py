from nespresso.recsys.searching.preprocessing.model import model


def CalculateTokenLen(text: str) -> int:
    tokenized = model.tokenizer(text)

    return len(tokenized["input_ids"])


def CreateEmbedding(text: str) -> list[float]:
    embedding = model.encode(text, normalize_embeddings=True)

    return embedding.tolist()


def CreateEmbeddings(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """
    Batch variant of `CreateEmbedding` for the directory sync. `model.encode`
    releases the GIL during the heavy compute, so callers should run this in a
    worker thread (``asyncio.to_thread``) to avoid blocking the event loop.
    """
    if not texts:
        return []

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
    )

    return [embedding.tolist() for embedding in embeddings]
