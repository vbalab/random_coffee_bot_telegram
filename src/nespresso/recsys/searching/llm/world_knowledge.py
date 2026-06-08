"""
Shared world-knowledge taxonomy.

Used by BOTH sides of the match so they speak the same vocabulary:
  - index time (`enrich.py`) — expand a profile's employers/roles into their
    implicit industries/skills before embedding, and
  - query time (`query_understanding.py`) — expand a narrow query (e.g. "HFT",
    "XTX", "венчур") into the same world-knowledge terms for recall.

Keeping a single source means a query and the profiles it should match are
enriched against an identical mental model, in both Russian and English.
"""

WORLD_KNOWLEDGE = """\
High-frequency / quantitative trading (высокочастотный трейдинг, HFT, квант, \
маркет-мейкинг, алготрейдинг, low-latency trading, market making, algorithmic \
trading): XTX Markets, Pinely, Jump Trading, Jane Street, Citadel Securities, \
Two Sigma, Tower Research, Hudson River Trading (HRT), DRW, Optiver, IMC, \
Virtu, Maven, G-Research.

Strategy / management consulting (стратегический консалтинг, управленческий \
консалтинг, MBB): McKinsey, Boston Consulting Group (BCG), Bain, Oliver Wyman, \
Roland Berger, Kearney, Strategy&.

Investment banking / capital markets (инвестбанкинг, рынки капитала, M&A, \
слияния и поглощения): Goldman Sachs, J.P. Morgan, Morgan Stanley, Bank of \
America, Citi, Barclays, Deutsche Bank, UBS, Credit Suisse, VTB Capital, \
Sberbank CIB, Renaissance Capital, Aton.

Big-4 audit / advisory (аудит, консалтинг, бухгалтерия): PwC, Deloitte, EY \
(Ernst & Young), KPMG.

Banking / retail & corporate finance (банки, банкинг): Sberbank (Сбербанк), \
VTB (ВТБ), Tinkoff / T-Bank (Тинькофф, Т-Банк), Alfa-Bank (Альфа-Банк), \
Raiffeisen, Gazprombank (Газпромбанк), Otkritie, Sovcombank.

Big tech / IT / product / data (технологии, IT, разработка, данные, продукт): \
Yandex (Яндекс), Google, Meta, Amazon, Microsoft, Apple, OZON, Avito, VK, \
Wildberries, Sber tech, Nvidia.

Venture capital / private equity (венчур, прямые инвестиции, VC, PE): Sequoia, \
a16z (Andreessen Horowitz), Accel, Baring Vostok, DST Global, Tiger Global, \
Runa Capital, Almaz Capital.

Asset / wealth management & hedge funds (управление активами, хедж-фонды): \
BlackRock, Bridgewater, Fidelity, PIMCO, Man Group, Citadel.

Central banks / regulation / macro (центральный банк, макроэкономика, \
регулирование, ДКП): Bank of Russia (ЦБ РФ, Центробанк), Federal Reserve (ФРС), \
ECB, IMF (МВФ), World Bank.

Crypto / blockchain / web3 / DeFi (крипто, блокчейн, web3, децентрализованные \
финансы, DeFi): Binance, Coinbase, Chainalysis, and any "DeFi"/"web3" wording.

Top quantitative / economics education (сильное количественное образование): \
MIT, Stanford, Harvard, Princeton, LSE, Oxford, Cambridge, MGU / МГУ \
(Lomonosov), MIPT / Физтех, HSE / ВШЭ, NES / РЭШ.

Role -> skills examples: Quant Researcher/Analyst -> statistics, machine \
learning, derivatives, alpha research, эконометрика; Data Scientist -> ML, \
statistics, Python, анализ данных; Portfolio Manager -> asset management, \
investing, управление активами; CFO -> corporate finance, accounting, \
корпоративные финансы; Product Manager -> product strategy, analytics, \
управление продуктом."""
