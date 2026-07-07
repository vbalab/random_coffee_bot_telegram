import logging

from nespresso.recsys.searching.client import client

PIPELINE_NAME = "nespresso_normalization_pipeline"

# 2 subqueries over the single unified profile field: `text` BM25 + `embedding`
# KNN. The directory self-description and the user's bio are one document now, so
# every doc has exactly one populated text+embedding — the old cv-side
# down-weighting (needed because that lane was sparsely populated) is gone.
_WEIGHTS = [0.5, 0.5]


async def EnsureSearchPipeline() -> None:
    body = {
        "description": "Min-max normalization + arithmetic mean for hybrid BM25+KNN search",
        "phase_results_processors": [
            {
                "normalization-processor": {
                    "normalization": {"technique": "min_max"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {"weights": _WEIGHTS},
                    },
                }
            }
        ],
    }

    await client.transport.perform_request(
        method="PUT",
        url=f"/_search/pipeline/{PIPELINE_NAME}",
        body=body,
    )

    logging.info(f"# OpenSearch search pipeline '{PIPELINE_NAME}' created/updated.")
