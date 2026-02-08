from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

from nespresso.core.configs.paths import DIR_EMBEDDING

# TODO: change

TOKEN_LEN = 384
EMBEDDING_LEN = 768

_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"


def EnsureSentenceTransformer() -> None:
    snapshot_download(
        repo_id=_MODEL_NAME,
        local_dir=DIR_EMBEDDING,
    )


def GetSentenceTransformer() -> SentenceTransformer:
    EnsureSentenceTransformer()

    return SentenceTransformer(model_name_or_path=str(DIR_EMBEDDING))


model = GetSentenceTransformer()
