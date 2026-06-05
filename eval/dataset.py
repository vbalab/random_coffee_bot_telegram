"""
Find-search evaluation dataset.

Ground truth is defined as a deterministic **predicate over the real MyNES
profile fields**, so "relevant" is objective and reproducible — no hand-labeling.
For each query we materialize the gold set (all alumni matching the predicate)
from the live directory and score how well a retrieval system ranks that set.

Queries are intentionally bilingual (RU/EN) to test cross-language retrieval:
e.g. the English query "venture investors" must surface profiles whose Russian
`professional_expertise` is "Венчурные инвестиции".

Run `python -m eval.run` (see run.py) to compute metrics for each backend.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

Profile = dict
Predicate = Callable[[Profile], bool]


# --------------------------------------------------------------------------- #
# Field helpers (normalize the messy real data)                               #
# --------------------------------------------------------------------------- #
def _n(s: object) -> str:
    return " ".join(str(s or "").casefold().split())


def city(r: Profile, sub: str) -> bool:
    return sub in _n(r.get("city")) or sub in _n(r.get("region"))


def pe(r: Profile, *vals: str) -> bool:
    have = set(r.get("professional_expertise") or [])
    return any(v in have for v in vals)


def ie(r: Profile, *vals: str) -> bool:
    have = set(r.get("industry_expertise") or [])
    return any(v in have for v in vals)


def ce(r: Profile, *vals: str) -> bool:
    have = set(r.get("country_expertise") or [])
    return any(v in have for v in vals)


def _works(r: Profile) -> list[dict]:
    ws = [r.get("main_work")] + (r.get("additional_work") or [])
    return [w for w in ws if isinstance(w, dict)]


def _edu(r: Profile) -> list[dict]:
    return [
        e
        for f in ("pre_nes_education", "post_nes_education")
        for e in (r.get(f) or [])
        if isinstance(e, dict)
    ]


def company(r: Profile, *subs: str) -> bool:
    return any(sub in _n(w.get("company")) for w in _works(r) for sub in subs)


def position(r: Profile, *subs: str) -> bool:
    return any(sub in _n(w.get("position")) for w in _works(r) for sub in subs)


def university(r: Profile, *subs: str) -> bool:
    return any(sub in _n(e.get("university")) for e in _edu(r) for sub in subs)


def specialty(r: Profile, *subs: str) -> bool:
    return any(
        sub in _n(e.get("specialty")) or sub in _n(e.get("specialization"))
        for e in _edu(r)
        for sub in subs
    )


# --------------------------------------------------------------------------- #
# The query set                                                               #
# --------------------------------------------------------------------------- #
@dataclass
class EvalQuery:
    id: str
    text: str  # what a user types
    category: str
    predicate: Predicate
    note: str = ""


QUERIES: list[EvalQuery] = [
    EvalQuery("venture", "венчурные инвесторы", "expertise",
              lambda r: pe(r, "Венчурные инвестиции")),
    EvalQuery("ml", "specialists in machine learning and data science", "expertise",
              lambda r: pe(r, "Машинное обучение", "Анализ данных")),
    EvalQuery("ds_moscow", "data scientists in Moscow", "multi",
              lambda r: city(r, "москва") and pe(r, "Машинное обучение", "Анализ данных")),
    EvalQuery("sberbank", "кто работал в Сбербанке", "company",
              lambda r: company(r, "сбербанк")),
    EvalQuery("mna", "эксперты по слияниям и поглощениям", "expertise",
              lambda r: pe(r, "Слияния и поглощения")),
    EvalQuery("london", "alumni in London", "location",
              lambda r: city(r, "лондон")),
    EvalQuery("oilgas", "нефтегазовая отрасль", "industry",
              lambda r: ie(r, "Нефть и газ")),
    EvalQuery("traders", "трейдеры", "expertise",
              lambda r: pe(r, "Трейдинг", "Алготрейдинг")),
    EvalQuery("teachers", "преподаватели", "expertise",
              lambda r: pe(r, "Преподавание")),
    EvalQuery("risk", "риск-менеджеры", "expertise",
              lambda r: pe(r, "Риск-менеджмент")),
    EvalQuery("ds_sber", "data scientists in Moscow who work at Sberbank", "multi",
              lambda r: city(r, "москва") and company(r, "сбербанк")
              and pe(r, "Машинное обучение", "Анализ данных")),
    EvalQuery("founders", "основатели стартапов", "expertise",
              lambda r: pe(r, "Стартапы и инновации", "Предпринимательство")),
    EvalQuery("corpfin", "корпоративные финансы", "expertise",
              lambda r: pe(r, "Корпоративные финансы")),
    EvalQuery("blockchain", "blockchain and crypto experts", "expertise",
              lambda r: pe(r, "Blockchain и криптовалюты")),
    EvalQuery("realestate", "real estate industry", "industry",
              lambda r: ie(r, "Недвижимость")),

    # --- country expertise ---
    EvalQuery("ce_usa", "эксперты по рынку США", "country_expertise",
              lambda r: ce(r, "США")),
    EvalQuery("ce_asia", "specialists in Asian markets", "country_expertise",
              lambda r: ce(r, "Азия")),
    EvalQuery("ce_europe", "эксперты по континентальной Европе", "country_expertise",
              lambda r: ce(r, "Континентальная Европа")),
    EvalQuery("ce_em", "emerging markets specialists", "country_expertise",
              lambda r: ce(r, "Emerging markets")),

    # --- education (pre/post NES) ---
    EvalQuery("uni_msu", "выпускники МГУ", "education",
              lambda r: university(r, "ломоносов")),
    EvalQuery("uni_mipt", "graduates of MIPT / Физтеха", "education",
              lambda r: university(r, "физико-техническ")),
    EvalQuery("uni_hse", "выпускники ВШЭ", "education",
              lambda r: university(r, "высшая школа экономики")),
    EvalQuery("spec_phys", "люди с физическим образованием", "education",
              lambda r: specialty(r, "физик")),

    # --- company ---
    EvalQuery("co_yandex", "кто работает в Яндексе", "company",
              lambda r: company(r, "яндекс")),
    EvalQuery("co_mck", "McKinsey alumni", "company",
              lambda r: company(r, "mckinsey")),
    EvalQuery("co_tbank", "сотрудники Т-Банка / Тинькофф", "company",
              lambda r: company(r, "т-банк", "тинькоф")),
    EvalQuery("co_cbr", "people at the Central Bank of Russia", "company",
              lambda r: company(r, "центральный банк")),
    EvalQuery("co_bcg", "BCG consultants", "company",
              lambda r: company(r, "boston consulting")),
    EvalQuery("co_ozonavito", "OZON or Avito employees", "company",
              lambda r: company(r, "ozon", "avito")),
    EvalQuery("co_vtbcap", "ВТБ Капитал", "company",
              lambda r: company(r, "втб капитал")),

    # --- role / position ---
    EvalQuery("pos_ds", "data scientists", "role",
              lambda r: position(r, "data scientist")),
    EvalQuery("pos_quant", "quantitative researchers / квонты", "role",
              lambda r: position(r, "quantitative")),
    EvalQuery("pos_ceo", "CEOs and founders", "role",
              lambda r: position(r, "ceo", "founder")),
    EvalQuery("pos_consult", "консультанты", "role",
              lambda r: position(r, "consultant", "консультант")),
    EvalQuery("pos_pm", "продакт-менеджеры", "role",
              lambda r: position(r, "product manager")),

    # --- industry ---
    EvalQuery("ind_it", "IT и телеком", "industry",
              lambda r: ie(r, "IT, телеком")),
    EvalQuery("ind_edu", "сфера образования", "industry",
              lambda r: ie(r, "Образование")),
    EvalQuery("ind_health", "здравоохранение и фарма", "industry",
              lambda r: ie(r, "Здравоохранение и фармацевтика")),
    EvalQuery("ind_transport", "транспорт и логистика", "industry",
              lambda r: ie(r, "Транспорт и логистика")),
    EvalQuery("ind_retail", "ритейл и торговля", "industry",
              lambda r: ie(r, "Оптовая и розничная торговля")),

    # --- professional expertise (extra coverage) ---
    EvalQuery("pe_econometrics", "эконометрика", "expertise",
              lambda r: pe(r, "Эконометрика")),
    EvalQuery("pe_algo", "алготрейдинг", "expertise",
              lambda r: pe(r, "Алготрейдинг")),
    EvalQuery("pe_marketing", "маркетологи", "expertise",
              lambda r: pe(r, "Маркетинг")),
    EvalQuery("pe_sales", "sales / продажи", "expertise",
              lambda r: pe(r, "Продажи")),
    EvalQuery("pe_am", "asset management", "expertise",
              lambda r: pe(r, "Управление активами")),
    EvalQuery("pe_macro", "macroeconomics experts", "expertise",
              lambda r: pe(r, "Макроэкономика", "Макроэкономическая")),

    # --- multi-constraint ---
    EvalQuery("mc_ml_yandex", "ML engineers at Yandex", "multi",
              lambda r: company(r, "яндекс")
              and pe(r, "Машинное обучение", "Анализ данных")),
    EvalQuery("mc_strat_consult", "консультанты McKinsey, BCG или Bain", "multi",
              lambda r: company(r, "mckinsey", "boston consulting", "bain")),
    EvalQuery("mc_founders_it", "founders in IT", "multi",
              lambda r: ie(r, "IT, телеком")
              and pe(r, "Стартапы и инновации", "Предпринимательство")),

    # --- location variety (incl. another EN↔RU city case) ---
    EvalQuery("loc_spb", "выпускники в Санкт-Петербурге", "location",
              lambda r: city(r, "санкт-петербург")),
    EvalQuery("loc_ny", "alumni in New York", "location",
              lambda r: city(r, "нью-йорк")),
    EvalQuery("loc_dolgo", "люди в Долгопрудном", "location",
              lambda r: city(r, "долгопрудн")),

    # --- phrasing / robustness ---
    EvalQuery("typo_ds", "датасаентисты", "phrasing",
              lambda r: position(r, "data scientist")
              or pe(r, "Машинное обучение", "Анализ данных")),
    EvalQuery("vague_finance", "кто из мира финансов", "phrasing",
              lambda r: pe(r, "Корпоративные финансы", "Управление активами",
                           "Коммерческие банки")),
    EvalQuery(
        "nl_vc",
        "I'm looking for someone who can advise on venture capital fundraising",
        "phrasing", lambda r: pe(r, "Венчурные инвестиции")),

    EvalQuery(
        "mae2002", "Выпускников мужчин программы МАЭ 2002", "unsupported",
        lambda r: False,
        note="program/class_year/gender absent from /user/list — gold is empty by "
        "construction; documents the data gap until MyNES adds those fields.",
    ),
    EvalQuery(
        "mf2015women", "женщины-выпускницы программы МФ 2015", "unsupported",
        lambda r: False,
        note="gender + program + class_year all absent from the feed.",
    ),
]


# --------------------------------------------------------------------------- #
# Profiles + gold materialization                                             #
# --------------------------------------------------------------------------- #
_LIST_URL = "https://my.nes.ru/new-api-2/user/list"
_LOCAL_CACHE = "/tmp/nes_list.json"


def LoadProfiles() -> list[Profile]:
    """Load alumni profiles: local cache → live /user/list fallback."""
    if os.path.exists(_LOCAL_CACHE):
        with open(_LOCAL_CACHE) as f:
            data = json.load(f)
    else:
        req = urllib.request.Request(_LIST_URL, headers={"accept": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
            data = json.load(resp)
    # dedupe alumni by nes_id (feed has identical duplicates)
    by_id: dict[int, Profile] = {}
    for r in data:
        if r.get("alumni") and r["nes_id"] not in by_id:
            by_id[r["nes_id"]] = r
    return list(by_id.values())


def MaterializeGold(profiles: list[Profile]) -> dict[str, set[int]]:
    gold: dict[str, set[int]] = {}
    for q in QUERIES:
        gold[q.id] = {r["nes_id"] for r in profiles if q.predicate(r)}
    return gold


def SaveDataset(path: str = "eval/dataset.json") -> dict:
    profiles = LoadProfiles()
    gold = MaterializeGold(profiles)
    out = {
        "total_alumni": len(profiles),
        "queries": [
            {
                "id": q.id,
                "text": q.text,
                "category": q.category,
                "gold_count": len(gold[q.id]),
                "gold_nes_ids": sorted(gold[q.id]),
                "note": q.note,
            }
            for q in QUERIES
        ],
    }
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out
