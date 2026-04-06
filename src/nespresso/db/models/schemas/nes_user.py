from pydantic import BaseModel, ConfigDict, Field


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


class NesUserOut(BaseModel):
    nes_id: int = Field(description="my.nes ID")


class NesUserIn(NesUserOut):
    # Personal info
    name: str | None = Field(default=None, description="ФИО")
    city: str | None = Field(default=None, description="Город")
    region: str | None = Field(default=None, description="Регион")
    country: str | None = Field(default=None, description="Страна")

    # NES alumni info
    program: str | None = Field(default=None, description="Программа")
    class_name: str | None = Field(default=None, description="Класс")
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

    model_config = ConfigDict(from_attributes=True)
