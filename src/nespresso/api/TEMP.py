from nespresso.api.request import (
    AllowDataSharingPermission,
    DenyDataSharingPermission,
    GetNesUserFromMyNES,
)

sample_nes_ids = [*range(200)]

async def FindSomeNesUsers():
    for nes_id in sample_nes_ids:
        await AllowDataSharingPermission(nes_id)
        await GetNesUserFromMyNES(nes_id)
        await DenyDataSharingPermission(nes_id)
