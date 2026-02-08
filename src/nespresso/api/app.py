import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from nespresso.api.routers import nes_user
from nespresso.core.logs import flow as logs
from nespresso.core.logs.api import LoggerSetup


@asynccontextmanager
async def Lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await logs.LoggerStart(LoggerSetup)
    yield
    await logs.LoggerShutdown()


app = FastAPI(lifespan=Lifespan)


@app.exception_handler(RequestValidationError)
async def RequestValidationErrorHandler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logging.warning(
        f"Validation error on {request.method} {request.url}: {exc.errors()}"
    )

    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


class Tags(Enum):
    users = "users"
    analytics = "analytics"


app.include_router(nes_user.router, prefix="/user", tags=[Tags.users])
