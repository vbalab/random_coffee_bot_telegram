"""
One-shot in-container validation: ensure stores → populate the index via a real
sync → run the production-pipeline eval.

    PYTHONPATH=src python -m eval.run_docker

Intended to run as a one-off container against the live db + opensearch:

    docker compose stop bot
    docker compose run --rm -v "$PWD/eval:/usr/src/app/eval" bot python -m eval.run_docker
"""

from __future__ import annotations

import asyncio

from eval.run_opensearch import main as eval_main
from nespresso.api.request import CloseMyNesClient
from nespresso.api.sync import SyncFromMyNES
from nespresso.db.session import EnsureDB, engine
from nespresso.recsys.searching.client import CloseOpenSearchClient
from nespresso.recsys.searching.index import EnsureOpenSearchIndex
from nespresso.recsys.searching.llm.client import CloseLLMClient
from nespresso.recsys.searching.search_pipeline import EnsureSearchPipeline


async def main() -> None:
    await EnsureDB()
    await EnsureOpenSearchIndex()
    await EnsureSearchPipeline()

    print("=== Populating index via SyncFromMyNES (cold reindex can take ~minutes) ===")
    report = await SyncFromMyNES("eval")
    print(f"SYNC: ok={report.ok} alumni={report.alumni} reindexed={report.reindexed} "
          f"index_errors={report.index_errors} delisted={report.delisted} "
          f"took={report.duration_s}s error={report.error}")

    print("\n=== Production-pipeline eval ===")
    await eval_main()

    await CloseOpenSearchClient()
    await CloseMyNesClient()
    await CloseLLMClient()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
