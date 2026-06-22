from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PreEducation(BaseModel):
    university: str | None = Field(default=None, description="Университет")
    department: str | None = Field(default=None, description="Департамент")
    specialty: str | None = Field(default=None, description="Специальность")
    specialization: str | None = Field(default=None, description="Специализация")

    model_config = ConfigDict(from_attributes=True)


class PostEducation(BaseModel):
    university: str | None = Field(default=None, description="Университет")
    location: str | None = Field(default=None, description="Местонахождение")
    department: str | None = Field(default=None, description="Департамент")
    program_type: str | None = Field(default=None, description="Тип программы")
    program: str | None = Field(default=None, description="Программа")
    degree: str | None = Field(default=None, description="Полученная степень")

    model_config = ConfigDict(from_attributes=True)


class WorkExperience(BaseModel):
    industry: str | None = Field(default=None, description="Отрасль")
    subindustry: str | None = Field(default=None, description="Подотрасль")
    company: str | None = Field(default=None, description="Компания")
    location: str | None = Field(default=None, description="Местонахождение")
    department: str | None = Field(default=None, description="Департамент")
    position: str | None = Field(default=None, description="Должность")

    model_config = ConfigDict(from_attributes=True)


class Program(BaseModel):
    name: str | None = Field(default=None, description="Название программы")
    year: int | None = Field(default=None, description="Год выпуска")

    model_config = ConfigDict(from_attributes=True)


class NesUserOut(BaseModel):
    nes_id: int = Field(description="my.nes ID")


class NesUserIn(NesUserOut):
    # Personal info
    name: str | None = Field(default=None, description="ФИО")
    # The directory feed sends the field as `email`; we store it as `nes_email`
    # (the model column). alias + populate_by_name lets both forms validate.
    nes_email: str | None = Field(default=None, alias="email", description="Email")
    sex: str | None = Field(default=None, description="Пол (MALE/FEMALE)")
    city: str | None = Field(default=None, description="Город")
    region: str | None = Field(default=None, description="Регион")
    country: str | None = Field(default=None, description="Страна")

    # NES alumni info
    program: str | None = Field(default=None, description="Программа")
    class_name: str | None = Field(default=None, description="Класс")
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
            return [item for item in value if item is not None]
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
