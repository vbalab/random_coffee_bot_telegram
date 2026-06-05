from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from nespresso.db.base import Base


class NesUser(Base):
    __tablename__ = "nes_user"

    nes_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nes_email: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Personal info
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)

    # NES alumni info
    program: Mapped[str | None] = mapped_column(String, nullable=True)
    class_name: Mapped[str | None] = mapped_column(String, nullable=True)
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

    def SearchText(self) -> str:
        """
        Clean natural-language profile text for embedding + BM25 indexing.

        Unlike FullDescription this drops the English section labels ("Main work:",
        "Program:", …) that repeat on every document and add noise to the vector —
        each line is just the meaningful content.
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
            lines.append(loc_line)

        works = [self.main_work] + (self.additional_work or [])
        for w in works:
            if isinstance(w, dict):
                parts = [
                    w.get(k)
                    for k in ("position", "company", "industry", "department")
                ]
                wl = ", ".join(p for p in parts if p)
                if wl:
                    lines.append(wl)

        for vals in (
            self.professional_expertise,
            self.industry_expertise,
            self.country_expertise,
            self.hobbies,
        ):
            if vals:
                joined = ", ".join(v for v in vals if v)
                if joined:
                    lines.append(joined)

        edus = (self.pre_nes_education or []) + (self.post_nes_education or [])
        for e in edus:
            if isinstance(e, dict):
                parts = [
                    e.get(k)
                    for k in (
                        "university", "specialty", "specialization", "program",
                        "degree",
                    )
                ]
                el = ", ".join(p for p in parts if p)
                if el:
                    lines.append(el)

        return "\n".join(lines)

    def _FormatWorkExperience(
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

            parts = []
            for key, value in data.items():
                if key in ["company", "department", "position"] and value:
                    parts.append(value)

            if parts:
                entries.append(",\n     ".join(parts))

        if not entries:
            return None

        entries = list(set(entries))
        sub = "\n\n".join(f"  – {e}" for e in entries)

        return f"{label}:\n{sub}"

    def SelfDescription(self) -> str:
        text = ""
        text += f"{self.name}\n" if self.name else ""

        text += "[" if self.city or self.region or self.country else ""
        text += f"{self.city}" if self.city else ""
        text += (
            ", "
            if self.city
            and ((self.region and (self.city != self.region)) or self.country)
            else ""
        )
        if self.city != self.region:
            text += f"{self.region}" if self.region else ""
            text += ", " if self.region and self.country else ""
        text += f"{self.country}" if self.country else ""
        text += "]\n" if self.city or self.region or self.country else ""

        text += (
            f"{self.program}'{self.class_name}\n"
            if self.program and self.class_name
            else ""
        )

        return text

    def WorkDescription(self) -> str:
        main_work = self._FormatWorkExperience("Main work", self.main_work)
        additional_work = self._FormatWorkExperience(
            "Additional work", self.additional_work
        )

        text = ""
        text += main_work if main_work else ""
        text += "\n\n" if main_work and additional_work else ""
        text += additional_work if additional_work else ""

        return text
