import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

from nespresso.core.configs.paths import DIR_EMBEDDING

_T = TypeVar("_T")

# Alibaba GTE multilingual embeddings are optimized for semantic retrieval,
# including multilingual corpora (e.g. EN + RU CV/resume search).
# Model card: https://huggingface.co/Alibaba-NLP/gte-multilingual-base
TOKEN_LEN = 2048
EMBEDDING_LEN = 768

_MODEL_NAME = "Alibaba-NLP/gte-multilingual-base"


def EnsureSentenceTransformer() -> None:
    snapshot_download(
        repo_id=_MODEL_NAME,
        local_dir=DIR_EMBEDDING,
    )


def GetSentenceTransformer() -> SentenceTransformer:
    EnsureSentenceTransformer()

    model = SentenceTransformer(
        model_name_or_path=str(DIR_EMBEDDING), trust_remote_code=True
    )
    model.max_seq_length = TOKEN_LEN

    return model


model = GetSentenceTransformer()


# All model inference funnels through ONE worker thread. The HuggingFace fast
# tokenizer behind this model is shared by BOTH the GTE encoder and KeyBERT
# (`keyword_model = KeyBERT(model=model)`) and is NOT thread-safe — concurrent
# calls from different threads raise `RuntimeError: Already borrowed`. A single
# worker keeps inference OFF the event loop (so other users' async I/O — Haiku
# calls, OpenSearch — keeps flowing) while guaranteeing tokenizer calls never
# overlap. Every async caller (interactive search, bio-save, directory sync) MUST
# route through `RunInference` rather than `asyncio.to_thread` (which uses the
# multi-thread default pool and would collide).
_INFERENCE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inference")


async def RunInference(fn: Callable[..., _T], *args: object) -> _T:
    """Run a (blocking) model-inference call on the shared single worker thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_INFERENCE_EXECUTOR, fn, *args)
