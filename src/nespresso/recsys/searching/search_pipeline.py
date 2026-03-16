import logging

from nespresso.recsys.searching.client import client

PIPELINE_NAME = "nespresso_normalization_pipeline"

# 4 subqueries: mynes_text BM25, mynes_embedding KNN, cv_text BM25, cv_embedding KNN
_WEIGHTS = [0.25, 0.25, 0.25, 0.25]


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
