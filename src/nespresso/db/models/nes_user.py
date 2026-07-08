import html
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from nespresso.db.base import Base

# Display-side NES program abbreviations (full feed name -> conventional short
# name from nes.ru). Programs without a standard abbreviation keep their full
# name. The parser (query_understanding.py) maps the REVERSE for search.
_PROGRAM_ABBR: dict[str, str] = {
    "Магистр экономики": "МАЭ",
    "Бакалавр экономики": "БАЭ",
    "Мастер финансов": "МИФ",
    "Финансы, инвестиции, банки": "ФИБ",
    "Экономика и анализ данных": "ЭАД",
    "Мини-Мастер финансов": "Мини-МИФ",
}


class NesUser(Base):
    __tablename__ = "nes_user"

    nes_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nes_email: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Personal info
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    sex: Mapped[str | None] = mapped_column(String, nullable=True)  # "MALE" / "FEMALE"
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)

    # NES alumni info. `programs` is the directory feed's list of {name, year};
    # `program`/`class_name` hold the primary (latest) one for display/analytics.
    program: Mapped[str | None] = mapped_column(String, nullable=True)
    class_name: Mapped[str | None] = mapped_column(String, nullable=True)
    programs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    alumni: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Hobbies and expertise
    hobbies: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    industry_expertise: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    country_expertise: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    professional_expertise: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )

    # Work experiences
    main_work: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    additional_work: Mapped[list[dict[str, str]] | None] = mapped_column(
        JSON, nullable=True
    )

    # Education
    pre_nes_education: Mapped[list[dict[str, str]] | None] = mapped_column(
        JSON, nullable=True
    )
    post_nes_education: Mapped[list[dict[str, str]] | None] = mapped_column(
        JSON, nullable=True
    )

    # --- MyNES directory sync ---
    # `listed`  — whether the user is currently present in the MyNES directory
    #             (i.e. has "Show in a class' directory" enabled). When a user
    #             drops out of `GET /user/list`, the hourly sync sets this False
    #             and removes their OpenSearch document (they stop being
    #             searchable / matchable) without deleting the row.
    # `mynes_text_hash` — sha256 of the indexed `mynes` FullDescription text;
    #             used to skip re-embedding unchanged profiles during sync.
    # `synced_at` — last time this row was refreshed from the MyNES directory.
    listed: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("TRUE"),
        default=True,
        nullable=False,
    )
    mynes_text_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Persisted retrieval texts (visible in an admin DB export): the raw directory
    # self-description (`SearchText`), the raw user bio (as of the last sync), and
    # the final enriched text that is embedded + indexed in OpenSearch.
    mynes_text: Mapped[str | None] = mapped_column(String, nullable=True)
    about_text: Mapped[str | None] = mapped_column(String, nullable=True)
    enriched_text: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    def _FormatScalarFields(self) -> list[str]:
        labels = {
            "Name": self.name,
            "City": self.city,
            "Region": self.region,
            "Country": self.country,
            "Program": self.program,
            "Class": self.class_name,
        }

        return [f"{label}: {val}" for label, val in labels.items() if val]

    def _FormatListFields(self) -> list[str]:
        labels = {
            "Hobbies": self.hobbies,
            "Industry expertise": self.industry_expertise,
            "Country expertise": self.country_expertise,
            "Professional expertise": self.professional_expertise,
        }

        return [
            f"{label} – {', '.join(vals)}" for label, vals in labels.items() if vals
        ]

    def _FormatSection(
        self,
        label: str,
        models: (
            Mapped[dict[str, str] | None]
            | Sequence[Mapped[dict[str, str] | None]]
            | None
        ),
    ) -> str | None:
        if not models:
            return None

        if not isinstance(models, list):
            items = [models]
        else:
            items = models

        entries: list[str] = []
        for m in items:
            if isinstance(m, dict):
                data = m
            else:
                data = m.model_dump()
            parts = [f"{k}: {v}" for k, v in data.items() if v]

            if parts:
                entries.append(" | ".join(parts))

        if not entries:
            return None

        entries = list(set(entries))
        sub = "\n".join(f"  – {e}" for e in entries)

        return f"{label}:\n{sub}"

    def FullDescription(self) -> str:
        sections: list[str] = []
        sections += self._FormatScalarFields()
        sections += self._FormatListFields()

        main_work = self._FormatSection("Main work", self.main_work)
        if main_work:
            sections.append(main_work)

        for label, attr in [
            ("Additional work", self.additional_work),
            ("Pre-NES education", self.pre_nes_education),
            ("Post-NES education", self.post_nes_education),
        ]:
            section = self._FormatSection(label, attr)
            if section:
                sections.append(section)

        return ".\n".join(sections)

    def _SearchWork(self, label: str, work: object) -> str | None:
        """One role-labeled work line: "<label>: <position> at <company>, <industry>"."""
        if not isinstance(work, dict):
            return None
        position = str(work.get("position") or "").strip()
        company = str(work.get("company") or "").strip()
        who = " at ".join(p for p in (position, company) if p)
        extra = ", ".join(
            str(work.get(k)).strip()
            for k in ("industry", "department")
            if work.get(k) and str(work.get(k)).strip()
        )
        body = ", ".join(p for p in (who, extra) if p)
        return f"{label}: {body}" if body else None

    def _SearchEducation(
        self, label: str, edu: object, keys: tuple[str, ...]
    ) -> str | None:
        """One role-labeled education line, e.g. "Post-NES education: <uni>, <dept>"."""
        if not isinstance(edu, dict):
            return None
        body = ", ".join(
            str(edu[k]).strip() for k in keys if edu.get(k) and str(edu[k]).strip()
        )
        return f"{label}: {body}" if body else None

    def SearchText(self) -> str:
        """
        Role-framed profile text for embedding + BM25 indexing.

        Each fact is one uniform ``Label: value`` line whose label names the
        person→entity RELATION. A bare "Высшая школа экономики" line leaves the
        encoder guessing (a school? an employer? current or past?); "Post-NES
        education: Высшая школа экономики" resolves it. These labels are a small,
        fixed, role-DISCRIMINATIVE vocabulary — the opposite of FullDescription's
        content-free section headers: they partition the record by meaning and
        echo how queries are phrased ("кто работает в…", "PhD из…", "учился в…"),
        which is what a natural-language-trained encoder aligns on. They also cue
        CLS pooling to weight the professional core over softer interest/market
        fields. `sex`/`email` stay out (structured-only / PII).
        """
        lines: list[str] = []

        if self.name:
            lines.append(self.name)

        loc = [self.city]
        if self.region and self.region != self.city:
            loc.append(self.region)
        if self.country:
            loc.append(self.country)
        loc_line = ", ".join(p for p in loc if p)
        if loc_line:
            lines.append(f"Location: {loc_line}")

        # NES program(s) + class year.
        progs: list[str] = []
        for p in self.programs or []:
            if isinstance(p, dict) and p.get("name"):
                year = p.get("year")
                progs.append(f"{p['name']} ({year})" if year else str(p["name"]))
        if progs:
            lines.append("NES program: " + ", ".join(progs))

        # Employment — main_work is the CURRENT role, additional_work is PRIOR
        # experience (mirrors the card's Текущая занятость / Предыдущий опыт).
        current = self._SearchWork("Current position", self.main_work)
        if current:
            lines.append(current)
        for work in self.additional_work or []:
            previous = self._SearchWork("Previous position", work)
            if previous:
                lines.append(previous)

        for label, vals in (
            ("Professional expertise", self.professional_expertise),
            ("Industry expertise", self.industry_expertise),
            ("Market expertise", self.country_expertise),
        ):
            joined = ", ".join(v for v in (vals or []) if v)
            if joined:
                lines.append(f"{label}: {joined}")

        # Education, split pre/post-NES so the encoder can tell them apart.
        for label, edus, keys in (
            (
                "Pre-NES education",
                self.pre_nes_education,
                ("university", "department", "specialty", "specialization"),
            ),
            (
                "Post-NES education",
                self.post_nes_education,
                ("university", "department", "program", "degree"),
            ),
        ):
            for edu in edus or []:
                line = self._SearchEducation(label, edu, keys)
                if line:
                    lines.append(line)

        hobbies = ", ".join(v for v in (self.hobbies or []) if v)
        if hobbies:
            lines.append(f"Interests: {hobbies}")

        return "\n".join(lines)

    def _FormatEntries(
        self,
        label: str,
        items: Sequence[object],
        normal_keys: tuple[str, ...],
        italic_key: str,
    ) -> str | None:
        """A <b>bold</b>-labelled section. Each entry is one line —
        "<normal>, <i>italic</i>" — so the organization/school reads as plain text
        and the role/degree is italicized, separating the two within a line.
        ALL dynamic content is HTML-escaped (the card is sent with parse_mode=HTML).
        """
        entries: list[str] = []
        for m in items:
            if not isinstance(m, dict):
                continue
            normal = ", ".join(
                html.escape(str(m[k]).strip())
                for k in normal_keys
                if m.get(k) and str(m[k]).strip()
            )
            italic_val = str(m.get(italic_key) or "").strip()
            if italic_val:
                italic = f"<i>{html.escape(italic_val)}</i>"
                line = f"{normal}, {italic}" if normal else italic
            else:
                line = normal
            if line:
                entries.append(line)

        entries = list(dict.fromkeys(entries))  # dedupe, preserve order
        if not entries:
            return None
        sub = "\n".join(f"  – {e}" for e in entries)
        return f"<b>{label}</b>:\n{sub}"

    def _WorkSection(self, label: str, models: object) -> str | None:
        if not models:
            return None
        items = models if isinstance(models, list) else [models]
        return self._FormatEntries(label, items, ("company", "department"), "position")

    def _ProgramsDisplay(self) -> str:
        """NES program(s) as conventional abbreviations + class year, e.g.
        "МАЭ'2008" (instead of the long "Магистр экономики")."""
        parts: list[str] = []
        for p in self.programs or []:
            if isinstance(p, dict) and p.get("name"):
                abbr = _PROGRAM_ABBR.get(p["name"], p["name"])
                year = p.get("year")
                parts.append(
                    f"{html.escape(str(abbr))}'{year}" if year else html.escape(str(abbr))
                )
        if not parts and self.program:  # fall back to the derived scalar
            abbr = _PROGRAM_ABBR.get(self.program, self.program)
            parts.append(
                f"{html.escape(str(abbr))}'{self.class_name}"
                if self.class_name
                else html.escape(str(abbr))
            )
        return ", ".join(parts)

    def SelfDescription(self) -> str:
        """Card header (HTML): <b>name</b>, [location], program-abbr'year."""
        lines: list[str] = []
        if self.name:
            lines.append(f"<b>{html.escape(self.name)}</b>")

        loc = [self.city]
        if self.region and self.region != self.city:
            loc.append(self.region)
        if self.country:
            loc.append(self.country)
        loc_str = ", ".join(p for p in loc if p)
        if loc_str:
            lines.append(f"[{html.escape(loc_str)}]")

        prog = self._ProgramsDisplay()
        if prog:
            lines.append(prog)

        return ("\n".join(lines) + "\n") if lines else ""

    def WorkDescription(self) -> str:
        """Employment + post-NES education sections (HTML, bold headers)."""
        sections: list[str] = []
        cur = self._WorkSection("Текущая занятость", self.main_work)
        if cur:
            sections.append(cur)
        prev = self._WorkSection("Предыдущий опыт", self.additional_work)
        if prev:
            sections.append(prev)
        if self.post_nes_education:
            edu = self._FormatEntries(
                "Образование после РЭШ",
                self.post_nes_education,
                ("university", "program"),
                "degree",
            )
            if edu:
                sections.append(edu)
        return "\n\n".join(sections)
