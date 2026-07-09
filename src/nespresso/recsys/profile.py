from __future__ import annotations

import html
from dataclasses import dataclass

from nespresso.bot.lib.chat.username import GetTgUsername
from nespresso.db.services.user_context import GetUserContextService

# Telegram rejects any message over 4096 chars; the send in io.py would swallow
# the resulting BadRequest and the user would see NO card at all. Render the card
# comfortably under that, leaving headroom for the trailing ellipsis.
_MAX_CARD_LEN = 4000
# The bio is the only free-form, user-controlled field, so it is the realistic
# overflow source. Cap its ESCAPED length so the About block stays well within the
# card budget regardless of how much html.escape expands it.
_MAX_ABOUT_LEN = 3000
_ELLIPSIS = "…"


def _CapEscapedBio(about: str, budget: int) -> str:
    """Truncate the free-form bio so its HTML-escaped form is at most `budget`
    chars. The cut is made on the RAW text (before escaping) so it can never split
    a tag or an entity — raw `about` contains neither. html.escape only ever GROWS
    a string (e.g. ``<`` → ``&lt;``), so binary-search the raw cut point that
    keeps the escaped length within budget."""
    if len(html.escape(about)) <= budget:
        return about

    lo, hi = 0, len(about)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        # +1 for the escaped ellipsis ("…" is not special, escapes to itself).
        if len(html.escape(about[:mid])) + len(_ELLIPSIS) <= budget:
            lo = mid
        else:
            hi = mid - 1

    return about[:lo].rstrip() + _ELLIPSIS


def _TruncateHtmlCard(text: str, limit: int) -> str:
    """Final safety net: keep the rendered HTML card within `limit` chars without
    producing invalid markup. Every line of the card is independently
    tag-balanced — SelfDescription/WorkDescription emit whole `<b>…</b>` /
    `<i>…</i>` pairs per line, the `<code>email</code>` and `<b>About:</b>` lines
    are self-contained, and the escaped bio carries no tags — so cutting on a
    newline boundary can never split a tag or leave one unclosed."""
    if len(text) <= limit:
        return text

    reserve = len("\n") + len(_ELLIPSIS)
    cut = text.rfind("\n", 0, limit - reserve)
    if cut <= 0:
        # No earlier newline (unreachable in practice: the header/contact lines
        # always add newlines before any long field). Fall back to a hard cut —
        # safe here only because such a leading line would be a bounded,
        # tag-balanced field, not the (already raw-capped) bio.
        cut = limit - reserve

    return text[:cut].rstrip() + "\n" + _ELLIPSIS


@dataclass
class Profile:
    nes_id: int
    username: str | None
    email: str | None
    about: str | None
    nes_self: str | None
    nes_work: str | None

    @classmethod
    async def FromNesId(cls, nes_id: int) -> Profile:
        username = None
        email = None
        about = None
        nes_self = None
        nes_work = None

        ctx = await GetUserContextService()
        chat_id = await ctx.GetTgChatIdBy(nes_id=nes_id)

        if chat_id:
            if tg := await GetTgUsername(chat_id):
                username = tg

            if tg_user := await ctx.GetTgUser(chat_id=chat_id):
                if tg_user.about:
                    about = tg_user.about

                if tg_user.nes_email:
                    email = tg_user.nes_email

        if nes_user := await ctx.GetNesUser(nes_id=nes_id):
            nes_self = nes_user.SelfDescription()
            nes_work = nes_user.WorkDescription()

            if email is None and nes_user.nes_email:
                email = nes_user.nes_email

        # TODO: add programm'year and format.

        return cls(
            nes_id=nes_id,
            username=username,
            email=email,
            about=about,
            nes_self=nes_self,
            nes_work=nes_work,
        )

    def DescribeProfile(self) -> str:
        """Profile card as Telegram HTML (sent with parse_mode="HTML")."""
        # Cap the free-form bio (escaped-length-bounded) so the About block can
        # never on its own overflow the card — the cut is raw-side, tag/entity-safe.
        about = self.about
        if about:
            about = _CapEscapedBio(about, _MAX_ABOUT_LEN)

        text = ""
        text += f"{self.nes_self}\n\n" if self.nes_self else ""

        text += f"@{html.escape(self.username)}\n" if self.username else ""
        # <code> renders the email monospace and makes it tap-to-copy in Telegram.
        text += f"<code>{html.escape(self.email)}</code>\n" if self.email else ""
        text += "\n" if self.username or self.email else ""

        text += f"<b>About:</b>\n{html.escape(about)}\n\n" if about else ""

        text += f"{self.nes_work}" if self.nes_work else ""

        # Second-layer guard: even with a capped bio, an unusually long directory
        # profile (many work/education entries) could still overflow — trim on a
        # tag-safe newline boundary.
        return _TruncateHtmlCard(text, _MAX_CARD_LEN)
