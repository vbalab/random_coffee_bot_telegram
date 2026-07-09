import asyncio
from collections import defaultdict

# Tracks the active hub message ID per user (chat_id → message_id).
# Used to delete the old hub when /start is called again, and to edit
# the hub message during in-place navigation (admin panel, sub-panels).
HUB_MESSAGES: dict[int, int] = {}

# Serializes SendHub() per chat_id. Without this, two concurrent calls for the
# same user (a double-tap that re-triggers /start, or two navigation actions
# racing) can both read the same "old" message id, both send a fresh hub, and
# leave HUB_MESSAGES/TgUser.panel_message_id pointing at only one of two now-live
# hub messages — the other becomes an orphaned duplicate.
HUB_LOCKS: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
