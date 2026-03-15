# Tracks the active hub message ID per user (chat_id → message_id).
# Used to delete the old hub when /start is called again, and to edit
# the hub message during in-place navigation (admin panel, sub-panels).
HUB_MESSAGES: dict[int, int] = {}
