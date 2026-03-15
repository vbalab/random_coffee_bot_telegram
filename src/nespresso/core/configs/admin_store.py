import json

from nespresso.core.configs.paths import PATH_ADMINS


class AdminStore:
    """
    Persistent store for admin chat IDs backed by ./data/admins.json.
    On first run (file absent) seeds itself from constants.ADMIN_CHAT_IDS.
    """

    def __init__(self) -> None:
        self._ids: list[int] = []
        self._load()

    def _load(self) -> None:
        if not PATH_ADMINS.exists():
            from nespresso.core.configs.constants import ADMIN_CHAT_IDS

            self._ids = list(ADMIN_CHAT_IDS)
            self._save()
            return

        with open(PATH_ADMINS) as f:
            self._ids = [int(x) for x in json.load(f)]

    def _save(self) -> None:
        PATH_ADMINS.parent.mkdir(parents=True, exist_ok=True)
        with open(PATH_ADMINS, "w") as f:
            json.dump(self._ids, f, indent=2)

    def GetIds(self) -> list[int]:
        return list(self._ids)

    def Contains(self, chat_id: int) -> bool:
        return chat_id in self._ids

    def Add(self, chat_id: int) -> bool:
        """Returns False if already an admin."""
        if chat_id in self._ids:
            return False
        self._ids.append(chat_id)
        self._save()
        return True

    def Remove(self, chat_id: int) -> bool:
        """Returns False if not an admin."""
        if chat_id not in self._ids:
            return False
        self._ids.remove(chat_id)
        self._save()
        return True


admin_store = AdminStore()
