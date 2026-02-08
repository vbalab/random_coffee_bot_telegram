from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from nespresso.db.base import Base


class NesUser(Base):
    __tablename__ = "nes_user"

    nes_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Personal info
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)

    # NES alumni info
    program: Mapped[str | None] = mapped_column(String, nullable=True)
    class_name: Mapped[str | None] = mapped_column(String, nullable=True)

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
            parts = [str(value) for value in data.values() if value]

            if parts:
                entries.append("\n   ".join(parts))

        if not entries:
            return None

        sub = "\n\n".join(f"  – {e}" for e in entries)

        return f"{label}:\n{sub}"

    def SelfDescription(self) -> str:
        text = ""
        text += f"{self.name}\n" if self.name else ""
        text += f"{self.city}," if self.city else ""
        text += f"{self.region}," if self.region else ""
        text += f"{self.country}" if self.country else ""
        text += "\n" if self.city or self.region or self.country else ""
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
