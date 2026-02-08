from nespresso.api.request import (
    AllowDataSharingPermission,
    DenyDataSharingPermission,
    GetNesUserFromMyNES,
)

sample_nes_ids = [
    1,
    11,
    111,
    1111,
    11111,
    111111,
    1111111,
    11111111,
    111111111,
    1111111111,
    11111111111,
    111111111111,
    1111111111111,
    11111111111111,
    111111111111111,
]


async def FindSomeNesUsers():
    for nes_id in sample_nes_ids:
        await AllowDataSharingPermission(nes_id)
        await GetNesUserFromMyNES(nes_id)
        await DenyDataSharingPermission(nes_id)
