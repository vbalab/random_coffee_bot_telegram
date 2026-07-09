from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Upstream (MyNES) is a trusted partner feed today, but nothing stops a future
# bug or bad response there from carrying an absurdly long field — and that
# text eventually reaches both the Claude enrichment call and an OpenSearch
# bulk batch. Cap every free-text field so one malformed record can't balloon
# either. A validation failure on a single record is skipped (logged) by
# FetchUsersList()'s per-record try/except, not fatal to the whole sync.
_MAX_STR_LEN = 500
_MAX_LIST_ITEMS = 100


class PreEducation(BaseModel):
    university: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Университет"
    )
    department: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Департамент"
    )
    specialty: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Специальность"
    )
    specialization: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Специализация"
    )

    model_config = ConfigDict(from_attributes=True)


class PostEducation(BaseModel):
    university: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Университет"
    )
    location: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Местонахождение"
    )
    department: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Департамент"
    )
    program_type: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Тип программы"
    )
    program: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Программа"
    )
    degree: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Полученная степень"
    )

    model_config = ConfigDict(from_attributes=True)


class WorkExperience(BaseModel):
    industry: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Отрасль"
    )
    subindustry: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Подотрасль"
    )
    company: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Компания"
    )
    location: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Местонахождение"
    )
    department: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Департамент"
    )
    position: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Должность"
    )

    model_config = ConfigDict(from_attributes=True)


class Program(BaseModel):
    name: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Название программы"
    )
    year: int | None = Field(default=None, description="Год выпуска")

    model_config = ConfigDict(from_attributes=True)


class NesUserOut(BaseModel):
    nes_id: int = Field(description="my.nes ID")


class NesUserIn(NesUserOut):
    # Personal info
    name: str | None = Field(default=None, max_length=_MAX_STR_LEN, description="ФИО")
    # The directory feed sends the field as `email`; we store it as `nes_email`
    # (the model column). alias + populate_by_name lets both forms validate.
    nes_email: str | None = Field(
        default=None, alias="email", max_length=320, description="Email"
    )
    sex: str | None = Field(default=None, max_length=20, description="Пол (MALE/FEMALE)")
    city: str | None = Field(default=None, max_length=_MAX_STR_LEN, description="Город")
    region: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Регион"
    )
    country: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Страна"
    )

    # NES alumni info
    program: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Программа"
    )
    class_name: str | None = Field(
        default=None, max_length=_MAX_STR_LEN, description="Класс"
    )
    programs: list[Program] | None = Field(
        default=None, description="Программы РЭШ (name + year)"
    )
    alumni: bool | None = Field(default=None, description="Alumni status")

    # Hobbies and expertise
    hobbies: list[str] | None = Field(default=None, description="Хобби")
    industry_expertise: list[str] | None = Field(
        default=None, description="Экспертиза по отраслям"
    )
    country_expertise: list[str] | None = Field(
        default=None, description="Экпертиза по странам"
    )
    professional_expertise: list[str] | None = Field(
        default=None, description="Профессиональная экспертиза"
    )

    main_work: WorkExperience | None = Field(
        default=None, description="Основное место работы"
    )
    additional_work: list[WorkExperience] | None = Field(
        default=None, description="Дополнительные места работы"
    )

    pre_nes_education: list[PreEducation] | None = Field(
        default=None, description="Образование до РЭШ"
    )
    post_nes_education: list[PostEducation] | None = Field(
        default=None, description="Образование после РЭШ"
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator(
        "hobbies",
        "industry_expertise",
        "country_expertise",
        "professional_expertise",
        mode="before",
    )
    @classmethod
    def _DropNoneFromStringList(cls, value: Any) -> Any:
        if isinstance(value, list):
            cleaned = [
                item[:_MAX_STR_LEN] for item in value if item is not None
            ]
            return cleaned[:_MAX_LIST_ITEMS]
        return value

    @field_validator(
        "programs",
        "additional_work",
        "pre_nes_education",
        "post_nes_education",
        mode="before",
    )
    @classmethod
    def _CapListLength(cls, value: Any) -> Any:
        if isinstance(value, list):
            return value[:_MAX_LIST_ITEMS]
        return value

    def primary_program(self) -> tuple[str | None, str | None]:
        """The display program (latest year) from `programs`, as (name, year-str).

        Used to populate the scalar `program`/`class_name` columns from the feed's
        `programs` list — by BOTH ingest paths (directory sync + byEmail), so they
        derive the primary program identically.
        """
        progs = [p for p in (self.programs or []) if p and p.name]
        if not progs:
            return None, None
        primary = max(progs, key=lambda p: p.year or 0)
        return primary.name, (str(primary.year) if primary.year else None)
