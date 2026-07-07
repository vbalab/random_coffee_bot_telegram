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


# Data-grounded knowledge base of the organizations, universities and roles that
# ACTUALLY appear across the NES alumni directory (frequency-ranked from the live
# feed). Used by index-time enrichment to gloss each employer/school with its real
# industry/category and reputation — including Russian firms and rebrands a generic
# model categorizes weakly (Б1 = ex-EY, Технологии Доверия = ex-PwC, Яков и
# Партнёры = ex-McKinsey Russia, Alber Blanc / AIM Tech / Pinely = HFT). Industry
# category names are kept consistent with WORLD_KNOWLEDGE so the query and index
# sides still meet at the same vocabulary. Large enough that the enrichment system
# prompt clears Haiku 4.5's 4096-token prompt-cache floor.
DIRECTORY_KNOWLEDGE = """\
Organizations that appear in THIS alumni network, grouped by category. Use them to
gloss an employer with its industry/category (both languages). Names may be written
in Russian or English; some are Russian rebrands of global firms (noted).

RUSSIAN & INTERNATIONAL BANKS (retail/corporate/universal banking — банки, банкинг):
Сбербанк / Sberbank, ВТБ / VTB, Газпромбанк / Gazprombank, Альфа-Банк / Alfa-Bank,
Тинькофф / Т-Банк / Tinkoff, Райффайзенбанк / Raiffeisen, ЮниКредит / UniCredit,
Росбанк / Rosbank, банк Открытие / Otkritie, Совкомбанк / Sovcombank, Промсвязьбанк
(ПСБ) / PSB, Московский кредитный банк (МКБ) / Credit Bank of Moscow, Уралсиб /
Uralsib, Россельхозбанк / Rosselkhozbank, ОТП Банк / OTP, МТС Банк, Ситибанк /
Citibank, ИНГ Банк / ING, Хоум Кредит, Русский Стандарт, Ренессанс Кредит, ОТКРЫТИЕ,
Банк Москвы, Петрокоммерц, Росбанк.

INVESTMENT BANKING & CAPITAL MARKETS (инвестбанкинг, рынки капитала, M&A, трейдинг):
ВТБ Капитал / VTB Capital, Sberbank CIB, Ренессанс Капитал / Renaissance Capital,
АТОН / Aton, БКС / BCS (Брокеркредитсервис), ТКБ Капитал, Московская биржа / Moscow
Exchange (MOEX), Goldman Sachs, J.P. Morgan, Morgan Stanley, Deutsche Bank, Barclays
Capital, Citi / Citigroup, Credit Suisse, UBS, Bank of America Merrill Lynch, HSBC,
BNP Paribas, Nomura, Royal Bank of Scotland (RBS).

STRATEGY / MANAGEMENT CONSULTING (стратегический консалтинг, управленческий
консалтинг, MBB): McKinsey, Boston Consulting Group (BCG), Bain, Oliver Wyman,
Roland Berger, Kearney, Strategy&, Monitor Group / Monitor Deloitte, Accenture,
Стратеджи Партнерс / Strategy Partners Group, Яков и Партнёры / Yakov & Partners
(ex-McKinsey Russia), AT Consulting, Branan, Glowbyte Consulting (data), Cornerstone
Research and Analysis Group (economic / litigation consulting).

BIG-4 AUDIT & ADVISORY (аудит, консалтинг, бухгалтерия, Big-4): PwC /
PricewaterhouseCoopers / Технологии Доверия (PwC Russia rebrand), Deloitte, EY
(Ernst & Young) / Б1 / B1 (EY Russia rebrand), KPMG / Kept.

BIG TECH / IT / INTERNET (технологии, IT, интернет, разработка, продукт, данные):
Яндекс / Yandex (incl. Яндекс.Такси, Yango, Яндекс.Еда, Лавка), OZON / Ozon Fintech,
Avito, VK, Wildberries, МТС / MTS, МегаФон / MegaFon, ВымпелКом / Билайн / Beeline,
Ростелеком / Rostelecom, Google, Amazon, Microsoft, Meta, IBM, Uber, Zalando,
inDrive, Lamoda, СберМаркет / SberMarket, Delivery Club, Joom, Gett, Циан / Cian,
HeadHunter, ABBYY, Лаборатория Касперского / Kaspersky, Туту.ру, uchi.ru, Osome,
Data Nerds, Accel Club.

HFT / QUANT TRADING / HEDGE FUNDS (высокочастотный трейдинг, HFT, алготрейдинг,
маркет-мейкинг, квант, количественные исследования, хедж-фонды): XTX Markets,
WorldQuant, Pinely, AIM Tech, Alber Blanc, GSA Capital Partners.

PRIVATE EQUITY / VENTURE CAPITAL / INVESTMENT FUNDS (прямые инвестиции, венчурные
инвестиции, PE, VC): Da Vinci Capital, Baring Vostok, Российский фонд прямых
инвестиций (РФПИ) / RDIF, Skolkovo Ventures, Интеррос / Interros, АФК Система / AFK
Sistema, Альфа-Групп / Alfa Group, ЛИДЕР, ПромСвязьКапитал, Fordewind.

CENTRAL BANK, REGULATORS & GOVERNMENT (центральный банк, регуляторы, госсектор,
макроэкономика, ДКП): Банк России / Центральный банк РФ / Bank of Russia (CBR),
Министерство финансов / Ministry of Finance, Министерство экономического развития /
Ministry of Economic Development, Министерство энергетики / Ministry of Energy,
Счётная палата / Accounts Chamber, ВЭБ.РФ / VEB, ДОМ.РФ / DOM.RF, Правительство
Москвы, Российское энергетическое агентство. International financial institutions:
МВФ / IMF, Всемирный банк / World Bank, ЕБРР / EBRD, Евразийский банк развития (ЕАБР)
/ EDB.

ECONOMIC RESEARCH INSTITUTES & THINK TANKS (экономические исследования, аналитика,
академия): ЦЭФИР / CEFIR (Center for Economic and Financial Research), Институт
Гайдара / ИЭПП / институт экономики переходного периода / Gaidar Institute (IET),
Экономическая экспертная группа / ЭЭГ (Economic Expert Group), ЦЭМИ РАН / CEMI,
РАНХиГС / RANEPA, НИФИ / Научно-исследовательский финансовый институт, Сколково /
Skolkovo.

ENERGY, OIL & GAS, METALS & MINING, INDUSTRY (нефть и газ, нефтегаз, энергетика,
металлургия, горнодобывающая промышленность, производство): Роснефть / Rosneft,
Газпром / Gazprom, Газпром нефть / Gazprom Neft, ЛУКОЙЛ / Lukoil, ТНК-BP / TNK-BP,
СИБУР / SIBUR, ЕвроХим / EuroChem, СУЭК / SUEK (coal), EVRAZ / ЕВРАЗ, Полюс / Polyus
(gold), Норильский Никель / Norilsk Nickel, Северсталь / Severstal, Металлоинвест /
Metalloinvest, ERG / Eurasian Resources Group, Росатом / Rosatom (nuclear), РОСНАНО
/ Rusnano, Интер РАО / Inter RAO, ФСК ЕЭС, Трансмашхолдинг, Металлоинвест.

CONSUMER / FMCG / RETAIL (товары народного потребления, ритейл, розничная торговля):
Procter & Gamble, Unilever, Nestlé / Нестле, X5 Retail Group, Nielsen, General
Electric. Real estate / development (недвижимость, девелопмент): Группа Самолёт /
Samolet, ДОМ.РФ, Циан. Rating agencies (рейтинговые агентства): Moody's. Pharma
(фармацевтика): Sanofi. Payments / fintech (платежи, финтех): Visa, Revolut, Plata
Card, LATOKEN (crypto / крипто).

TOP UNIVERSITIES our alumni studied at — all strong quantitative / economics /
finance schools; gloss with field + reputation. Russian: МГУ им. Ломоносова /
Lomonosov Moscow State University (мехмат, ВМК, эконом — top maths & economics),
МФТИ / MIPT / Физтех (top physics & maths), ВШЭ / HSE (economics, CS, maths), НГУ /
Novosibirsk State University, МГТУ им. Баумана / Bauman (engineering), Финансовый
университет / Financial University, МИФИ / MEPhI (physics), Плеханов / Plekhanov
(REU, economics), МГИМО / MGIMO (international relations & economics), СПбГУ / Saint
Petersburg State University, РАНХиГС / RANEPA, МАИ / MAI (aerospace), ЦЭМИ / CEMI,
МЭИ / MPEI, РЭШ / NES. Global: Stanford, MIT, Harvard, University of Chicago,
Princeton, Wharton / UPenn, Columbia, UC Berkeley, UCLA, Michigan, Duke, Northwestern
(Kellogg), Yale, NYU, Penn State, LSE, London Business School (LBS), INSEAD, Bocconi
/ Боккони, Pompeu Fabra / Помпеу Фабра, University College London (UCL), University
of Melbourne, University of Toronto, Boston College.

COMMON ROLES -> implied skills / domains (gloss a role only if not already stated):
Аналитик / Analyst, Финансовый аналитик / Investment Analyst -> финансовый анализ,
оценка, финансовое моделирование / financial analysis, valuation, modeling;
Data Scientist / Data Analyst / Аналитик данных -> машинное обучение, статистика,
Python, анализ данных / machine learning, statistics;
Quantitative Researcher / Quant / Трейдер -> алготрейдинг, деривативы, статистика,
маркет-мейкинг / quantitative trading, derivatives;
Consultant / Консультант / Engagement Manager -> стратегия, консалтинг / strategy
consulting;
Economist / Экономист / Главный экономист / научный сотрудник -> экономические
исследования, эконометрика, макроэкономика / economic research, econometrics;
Assistant/Associate Professor / Преподаватель / Доцент -> академия, преподавание,
исследования / academia, teaching, research;
Product Manager -> управление продуктом, продуктовая аналитика / product management;
Project Manager / Руководитель проектов -> управление проектами / project management;
CEO / Founder / Co-Founder / Генеральный директор -> предпринимательство, лидерство,
стартапы / entrepreneurship, leadership;
CFO / Финансовый директор -> корпоративные финансы / corporate finance;
Risk / Риск-менеджер -> риск-менеджмент / risk management.

MORE ORGANIZATIONS (same industry labels as above):
Banks & brokers (банки, брокеры): Тинькофф Инвестиции, Финам / Finam, БКС Мир
Инвестиций, Открытие Брокер, Freedom Finance / Фридом Финанс, ВЕЛЕС Капитал / Veles
Capital, Абсолют Банк, Ак Барс Банк, банк Санкт-Петербург, Райффайзен.
Investment banking / advisory (инвестбанкинг, M&A): Lazard, Rothschild & Co,
Evercore, Jefferies, Houlihan Lokey, Sova Capital, Financial Consulting Group.
HFT / quant / hedge funds (HFT, алготрейдинг, квант, хедж-фонды): Jane Street,
Citadel / Citadel Securities, Two Sigma, Jump Trading, Hudson River Trading (HRT),
Tower Research, Optiver, IMC, DRW, Virtu, G-Research, Graham Capital Management,
ITS Trading, Bridgewater, Man Group, Millennium, Squarepoint.
Big tech / IT (технологии, IT, разработка): JetBrains, EPAM, Luxoft, СберТех / Sber
tech, 2ГИС / 2GIS, Skyeng, Miro, Semrush, Nebius, Flocktory, Ситимобил, Nvidia,
Apple, Netflix, Booking, Wise, Циан.
Energy / oil & gas / metals & mining (нефтегаз, энергетика, металлургия,
горнодобыча): НОВАТЭК / Novatek, Татнефть / Tatneft, Сургутнефтегаз /
Surgutneftegas, Транснефть / Transneft, РусГидро / RusHydro, РУСАЛ / Rusal, ММК /
MMK, НЛМК / NLMK, ФосАгро / PhosAgro, Уралкалий / Uralkali, Мечел / Mechel, En+.
Consumer / FMCG / retail (товары народного потребления, ритейл): Магнит / Magnit,
Лента / Lenta, ВкусВилл, Mars, PepsiCo, Coca-Cola, Danone, L'Oréal, Mondelez,
Henkel, Reckitt, JTI, Philip Morris (PMI), British American Tobacco (BAT).
Pharma / healthcare (фармацевтика, здравоохранение): Novartis, Pfizer, Roche,
AstraZeneca, Bayer, Johnson & Johnson, Novo Nordisk.
More top universities (сильные университеты — gloss with field/reputation): Oxford,
Cambridge, Imperial College London, University of Warwick, Carnegie Mellon (CMU),
Cornell, Caltech, Georgia Tech, University of Washington, Boston University,
Barcelona GSE / Universitat Pompeu Fabra, Toulouse School of Economics, Central
European University (CEU), Sciences Po, Erasmus University Rotterdam, Tilburg
University, University of Zurich, University of Bonn, University of Amsterdam."""
