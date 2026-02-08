from fastapi import APIRouter

router = APIRouter()

# TODO: remove this file

# @router.post(
#     path="/upsert_nes_info/",
#     status_code=status.HTTP_201_CREATED,
#     summary="Create or update NES user.",
#     description="To upsert info about NES user pass body with it's full info even with NULLs.\n\n"
#     "**Authentication**: You must provide the token in the `authorization_token` header.",
#     response_description="`nes_id` of NES user upserted.",
# )
# async def UpsertNesUser(
#     nes_user: Annotated[
#         NesUserIn,
#         Body(
#             title="NesUser info.",
#             description="Request body containing NesUser info.",
#         ),
#     ]
# ) -> NesUserOut:
#     alchemy_nes_user: NesUser = NesUserPydanticToSQLAlchemy(nes_user)

#     ctx = await GetUserContextService()
#     await ctx.UpsertNesUser(alchemy_nes_user)

#     text = GetNesUserModelText(nes_user)
#     await UpsertTextOpenSearch(
#         nes_id=nes_user.nes_id,
#         side=DocSide.mynes,
#         text=text,
#     )

#     return nes_user
