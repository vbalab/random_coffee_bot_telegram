from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

from nespresso.core.configs.paths import DIR_EMBEDDING

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

    model = SentenceTransformer(model_name_or_path=str(DIR_EMBEDDING))
    model.max_seq_length = TOKEN_LEN

    return model


model = GetSentenceTransformer()
