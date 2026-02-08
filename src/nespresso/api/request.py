...
from nespresso.api.processing import NesUserPydanticToSQLAlchemy, GetNesUserModelText, UpsertTextOpenSearch, DocSide
from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.schemas.nes_user import NesUserIn
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import UpsertTextOpenSearch
from nespresso.recsys.searching.index import DocSide

...


# TODO: function 1 that takes nes_id, does GET request, gets info and does like the following:
#nes_user: NesUserIn
# alchemy_nes_user: NesUser = NesUserPydanticToSQLAlchemy(nes_user)
# ctx = await GetUserContextService()
# await ctx.UpsertNesUser(alchemy_nes_user)
# text = GetNesUserModelText(nes_user)
# await UpsertTextOpenSearch(
#     nes_id=nes_user.nes_id,
#     side=DocSide.mynes,
#     text=text,
# )

# TODO: function 2 that takes nes_id and makes POST setting permission to True

# TODO: function 3 that takes nes_id and makes POST setting permission to False
