import logging

from nespresso.recsys.searching.client import client

PIPELINE_NAME = "nespresso_normalization_pipeline"

# 4 subqueries: mynes_text BM25, mynes_embedding KNN, cv_text BM25, cv_embedding KNN.
# The `cv` side (user-written bio) is empty for most alumni, so min-max
# normalizing it over a tiny populated set injects noise — downweight it and let
# the directory-sourced `mynes` side carry the ranking.
_WEIGHTS = [0.35, 0.35, 0.15, 0.15]


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
