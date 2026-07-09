import logging

from nespresso.recsys.searching.preprocessing.model import TOKEN_LEN, model


def CalculateTokenLen(text: str) -> int:
    tokenized = model.tokenizer(text)

    return len(tokenized["input_ids"])


def _WarnIfTruncated(text: str) -> None:
    """
    Tripwire for silent embedding truncation. `model.encode` clips any input past
    `max_seq_length` (TOKEN_LEN) with no signal, dropping the tail of a profile
    from its vector — a quiet recall loss. Measured over the whole directory this
    fires for 0/2905 profiles (max 683 tokens, ~⅓ of the cap), so it is a guard
    against future corpus growth, not a hot-path concern; the tokenize pass is
    negligible next to the encoder forward pass.
    """
    n = CalculateTokenLen(text)
    if n > TOKEN_LEN:
        preview = text.strip().split("\n", 1)[0][:80]
        logging.warning(
            "Embedding input truncated: %d tokens > %d cap; tail dropped. [%s]",
            n,
            TOKEN_LEN,
            preview,
        )


def CreateEmbedding(text: str) -> list[float]:
    _WarnIfTruncated(text)
    # normalize_embeddings=True is deliberate belt-and-suspenders: the GTE model
    # already has a 2_Normalize module, but the KNN index uses the default l2 space,
    # which only ranks like cosine for UNIT vectors — so guaranteeing normalization
    # here keeps KNN correct even if the model's pipeline ever changes. Do NOT drop
    # it as "redundant".
    embedding = model.encode(text, normalize_embeddings=True)

    return embedding.tolist()


def CreateEmbeddings(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """
    Batch variant of `CreateEmbedding` for the directory sync. `model.encode`
    releases the GIL during the heavy compute, so async callers should run this
    off the event loop via ``model.RunInference`` (the shared single-worker
    executor) — NOT a bare ``asyncio.to_thread``: the tokenizer is not thread-safe
    and concurrent calls raise "Already borrowed".
    """
    if not texts:
        return []

    for text in texts:
        _WarnIfTruncated(text)

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
    )

    return [embedding.tolist() for embedding in embeddings]
