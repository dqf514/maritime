"""内置参考数据包：国家 / 时区 / 货币 / 船型 / 油种 / 市场指数 / 计量单位。"""

from __future__ import annotations

from typing import Iterable

# (code, label_en, label_zh, sort_order, meta)
ItemTuple = tuple[str, str, str, int, dict]


def _c(code: str, en: str, zh: str, order: int = 0, **meta) -> ItemTuple:
    return (code, en, zh, order, meta)


# ISO 3166-1 alpha-2 — 航运相关 + 主要国家（中英文）
COUNTRIES: list[ItemTuple] = [
    _c("CN", "China", "中国", 10),
    _c("HK", "Hong Kong, China", "中国香港", 20),
    _c("MO", "Macao, China", "中国澳门", 30),
    _c("TW", "Taiwan, China", "中国台湾", 40),
    _c("SG", "Singapore", "新加坡", 50),
    _c("JP", "Japan", "日本", 60),
    _c("KR", "Korea, Republic of", "韩国", 70),
    _c("KP", "Korea, Democratic People's Republic of", "朝鲜", 80),
    _c("MY", "Malaysia", "马来西亚", 90),
    _c("ID", "Indonesia", "印度尼西亚", 100),
    _c("TH", "Thailand", "泰国", 110),
    _c("VN", "Viet Nam", "越南", 120),
    _c("PH", "Philippines", "菲律宾", 130),
    _c("IN", "India", "印度", 140),
    _c("PK", "Pakistan", "巴基斯坦", 150),
    _c("BD", "Bangladesh", "孟加拉国", 160),
    _c("LK", "Sri Lanka", "斯里兰卡", 170),
    _c("AE", "United Arab Emirates", "阿联酋", 180),
    _c("SA", "Saudi Arabia", "沙特阿拉伯", 190),
    _c("QA", "Qatar", "卡塔尔", 200),
    _c("KW", "Kuwait", "科威特", 210),
    _c("OM", "Oman", "阿曼", 220),
    _c("BH", "Bahrain", "巴林", 230),
    _c("IQ", "Iraq", "伊拉克", 240),
    _c("IR", "Iran", "伊朗", 250),
    _c("TR", "Türkiye", "土耳其", 260),
    _c("EG", "Egypt", "埃及", 270),
    _c("ZA", "South Africa", "南非", 280),
    _c("NG", "Nigeria", "尼日利亚", 290),
    _c("GH", "Ghana", "加纳", 300),
    _c("KE", "Kenya", "肯尼亚", 310),
    _c("TZ", "Tanzania", "坦桑尼亚", 320),
    _c("MA", "Morocco", "摩洛哥", 330),
    _c("DZ", "Algeria", "阿尔及利亚", 340),
    _c("TN", "Tunisia", "突尼斯", 350),
    _c("LR", "Liberia", "利比里亚", 360),
    _c("MH", "Marshall Islands", "马绍尔群岛", 370),
    _c("PA", "Panama", "巴拿马", 380),
    _c("BS", "Bahamas", "巴哈马", 390),
    _c("CY", "Cyprus", "塞浦路斯", 400),
    _c("MT", "Malta", "马耳他", 410),
    _c("GI", "Gibraltar", "直布罗陀", 420),
    _c("IM", "Isle of Man", "马恩岛", 430),
    _c("GB", "United Kingdom", "英国", 440),
    _c("IE", "Ireland", "爱尔兰", 450),
    _c("NO", "Norway", "挪威", 460),
    _c("SE", "Sweden", "瑞典", 470),
    _c("DK", "Denmark", "丹麦", 480),
    _c("FI", "Finland", "芬兰", 490),
    _c("DE", "Germany", "德国", 500),
    _c("NL", "Netherlands", "荷兰", 510),
    _c("BE", "Belgium", "比利时", 520),
    _c("FR", "France", "法国", 530),
    _c("ES", "Spain", "西班牙", 540),
    _c("PT", "Portugal", "葡萄牙", 550),
    _c("IT", "Italy", "意大利", 560),
    _c("GR", "Greece", "希腊", 570),
    _c("HR", "Croatia", "克罗地亚", 580),
    _c("SI", "Slovenia", "斯洛文尼亚", 590),
    _c("PL", "Poland", "波兰", 600),
    _c("RU", "Russian Federation", "俄罗斯", 610),
    _c("UA", "Ukraine", "乌克兰", 620),
    _c("RO", "Romania", "罗马尼亚", 630),
    _c("BG", "Bulgaria", "保加利亚", 640),
    _c("US", "United States", "美国", 650),
    _c("CA", "Canada", "加拿大", 660),
    _c("MX", "Mexico", "墨西哥", 670),
    _c("BR", "Brazil", "巴西", 680),
    _c("AR", "Argentina", "阿根廷", 690),
    _c("CL", "Chile", "智利", 700),
    _c("PE", "Peru", "秘鲁", 710),
    _c("CO", "Colombia", "哥伦比亚", 720),
    _c("VE", "Venezuela", "委内瑞拉", 730),
    _c("UY", "Uruguay", "乌拉圭", 740),
    _c("AU", "Australia", "澳大利亚", 750),
    _c("NZ", "New Zealand", "新西兰", 760),
    _c("PG", "Papua New Guinea", "巴布亚新几内亚", 770),
    _c("FJ", "Fiji", "斐济", 780),
    _c("CH", "Switzerland", "瑞士", 790),
    _c("AT", "Austria", "奥地利", 800),
    _c("CZ", "Czechia", "捷克", 810),
    _c("HU", "Hungary", "匈牙利", 820),
    _c("LU", "Luxembourg", "卢森堡", 830),
    _c("IS", "Iceland", "冰岛", 840),
    _c("IL", "Israel", "以色列", 850),
    _c("JO", "Jordan", "约旦", 860),
    _c("LB", "Lebanon", "黎巴嫩", 870),
    _c("KZ", "Kazakhstan", "哈萨克斯坦", 880),
    _c("UZ", "Uzbekistan", "乌兹别克斯坦", 890),
    _c("MM", "Myanmar", "缅甸", 900),
    _c("KH", "Cambodia", "柬埔寨", 910),
    _c("BN", "Brunei Darussalam", "文莱", 920),
    _c("CU", "Cuba", "古巴", 930),
    _c("JM", "Jamaica", "牙买加", 940),
    _c("TT", "Trinidad and Tobago", "特立尼达和多巴哥", 950),
    _c("DO", "Dominican Republic", "多米尼加", 960),
    _c("CR", "Costa Rica", "哥斯达黎加", 970),
    _c("EC", "Ecuador", "厄瓜多尔", 980),
    _c("AO", "Angola", "安哥拉", 990),
    _c("CI", "Côte d'Ivoire", "科特迪瓦", 1000),
    _c("SN", "Senegal", "塞内加尔", 1010),
    _c("MZ", "Mozambique", "莫桑比克", 1020),
    _c("MU", "Mauritius", "毛里求斯", 1030),
    _c("SC", "Seychelles", "塞舌尔", 1040),
    _c("MV", "Maldives", "马尔代夫", 1050),
    _c("OTHER", "Other / Not listed", "其他 / 未列出", 9999),
]


def build_timezones() -> list[ItemTuple]:
    """优先海事常用时区，再补全 zoneinfo 可用区。"""
    preferred = [
        ("Asia/Shanghai", "China Standard Time (Shanghai)", "中国标准时间（上海）", 10),
        ("Asia/Hong_Kong", "Hong Kong", "香港", 20),
        ("Asia/Taipei", "Taipei", "台北", 30),
        ("Asia/Singapore", "Singapore", "新加坡", 40),
        ("Asia/Tokyo", "Tokyo", "东京", 50),
        ("Asia/Seoul", "Seoul", "首尔", 60),
        ("Asia/Jakarta", "Jakarta", "雅加达", 70),
        ("Asia/Bangkok", "Bangkok", "曼谷", 80),
        ("Asia/Kolkata", "Kolkata", "加尔各答", 90),
        ("Asia/Dubai", "Dubai", "迪拜", 100),
        ("Asia/Riyadh", "Riyadh", "利雅得", 110),
        ("Europe/London", "London", "伦敦", 200),
        ("Europe/Amsterdam", "Amsterdam", "阿姆斯特丹", 210),
        ("Europe/Berlin", "Berlin", "柏林", 220),
        ("Europe/Paris", "Paris", "巴黎", 230),
        ("Europe/Madrid", "Madrid", "马德里", 240),
        ("Europe/Rome", "Rome", "罗马", 250),
        ("Europe/Athens", "Athens", "雅典", 260),
        ("Europe/Istanbul", "Istanbul", "伊斯坦布尔", 270),
        ("Europe/Moscow", "Moscow", "莫斯科", 280),
        ("Africa/Cairo", "Cairo", "开罗", 300),
        ("Africa/Lagos", "Lagos", "拉各斯", 310),
        ("Africa/Johannesburg", "Johannesburg", "约翰内斯堡", 320),
        ("America/New_York", "New York (Eastern)", "纽约（美东）", 400),
        ("America/Chicago", "Chicago (Central)", "芝加哥（美中）", 410),
        ("America/Denver", "Denver (Mountain)", "丹佛（美山）", 420),
        ("America/Los_Angeles", "Los Angeles (Pacific)", "洛杉矶（美西）", 430),
        ("America/Sao_Paulo", "São Paulo", "圣保罗", 440),
        ("America/Panama", "Panama", "巴拿马", 450),
        ("America/Buenos_Aires", "Buenos Aires", "布宜诺斯艾利斯", 460),
        ("Australia/Sydney", "Sydney", "悉尼", 500),
        ("Australia/Perth", "Perth", "珀斯", 510),
        ("Pacific/Auckland", "Auckland", "奥克兰", 520),
        ("UTC", "Coordinated Universal Time", "协调世界时 UTC", 1),
    ]
    out: list[ItemTuple] = [(_c(z, en, zh, order)) for z, en, zh, order in preferred]
    seen = {x[0] for x in out}
    try:
        from zoneinfo import available_timezones

        extras = sorted(z for z in available_timezones() if z and not z.startswith("Etc/") and z not in seen)
        for i, z in enumerate(extras):
            city = z.split("/")[-1].replace("_", " ")
            out.append(_c(z, z, f"{city}（{z}）", 2000 + i))
    except Exception:
        pass
    return out


CURRENCIES: list[ItemTuple] = [
    _c("USD", "US Dollar", "美元", 10, symbol="$"),
    _c("EUR", "Euro", "欧元", 20, symbol="€"),
    _c("CNY", "Chinese Yuan", "人民币", 30, symbol="¥"),
    _c("HKD", "Hong Kong Dollar", "港币", 40, symbol="HK$"),
    _c("SGD", "Singapore Dollar", "新加坡元", 50, symbol="S$"),
    _c("JPY", "Japanese Yen", "日元", 60, symbol="¥"),
    _c("KRW", "Korean Won", "韩元", 70, symbol="₩"),
    _c("GBP", "Pound Sterling", "英镑", 80, symbol="£"),
    _c("CHF", "Swiss Franc", "瑞士法郎", 90, symbol="CHF"),
    _c("AUD", "Australian Dollar", "澳元", 100, symbol="A$"),
    _c("CAD", "Canadian Dollar", "加元", 110, symbol="C$"),
    _c("NZD", "New Zealand Dollar", "新西兰元", 120, symbol="NZ$"),
    _c("NOK", "Norwegian Krone", "挪威克朗", 130),
    _c("SEK", "Swedish Krona", "瑞典克朗", 140),
    _c("DKK", "Danish Krone", "丹麦克朗", 150),
    _c("INR", "Indian Rupee", "印度卢比", 160),
    _c("AED", "UAE Dirham", "阿联酋迪拉姆", 170),
    _c("SAR", "Saudi Riyal", "沙特里亚尔", 180),
    _c("TRY", "Turkish Lira", "土耳其里拉", 190),
    _c("BRL", "Brazilian Real", "巴西雷亚尔", 200),
    _c("ZAR", "South African Rand", "南非兰特", 210),
    _c("RUB", "Russian Ruble", "俄罗斯卢布", 220),
    _c("MYR", "Malaysian Ringgit", "马来西亚林吉特", 230),
    _c("THB", "Thai Baht", "泰铢", 240),
    _c("IDR", "Indonesian Rupiah", "印尼盾", 250),
    _c("PHP", "Philippine Peso", "菲律宾比索", 260),
    _c("VND", "Vietnamese Dong", "越南盾", 270),
    _c("TWD", "New Taiwan Dollar", "新台币", 280),
    _c("PLN", "Polish Zloty", "波兰兹罗提", 290),
    _c("MXN", "Mexican Peso", "墨西哥比索", 300),
]


VESSEL_TYPES: list[ItemTuple] = [
    _c("BULK", "Bulk Carrier", "散货船", 10),
    _c("TANKER", "Oil Tanker", "油轮", 20),
    _c("PRODUCT", "Product Tanker", "成品油轮", 30),
    _c("CHEM", "Chemical Tanker", "化学品船", 40),
    _c("LNG", "LNG Carrier", "LNG 船", 50),
    _c("LPG", "LPG Carrier", "LPG 船", 60),
    _c("CONTAINER", "Container Ship", "集装箱船", 70),
    _c("GENERAL", "General Cargo", "杂货船", 80),
    _c("RORO", "Ro-Ro", "滚装船", 90),
    _c("PCTC", "Car Carrier (PCTC)", "汽车运输船", 100),
    _c("REEFER", "Reefer", "冷藏船", 110),
    _c("OFFSHORE", "Offshore / OSV", "海工 / OSV", 120),
    _c("TUG", "Tug", "拖轮", 130),
    _c("BARGE", "Barge", "驳船", 140),
    _c("PASSENGER", "Passenger / Cruise", "客船 / 邮轮", 150),
    _c("OTHER", "Other", "其他", 999),
]


FUEL_GRADES: list[ItemTuple] = [
    _c("VLSFO", "VLSFO (0.5% S)", "低硫燃料油 VLSFO", 10),
    _c("HSFO", "HSFO (3.5% S)", "高硫燃料油 HSFO", 20),
    _c("MGO", "Marine Gas Oil", "船用柴油 MGO", 30),
    _c("MDO", "Marine Diesel Oil", "船用柴油 MDO", 40),
    _c("ULSFO", "ULSFO", "超低硫燃料油 ULSFO", 50),
    _c("LSMGO", "LSMGO", "低硫船用柴油 LSMGO", 60),
    _c("LNG", "LNG", "液化天然气 LNG", 70),
    _c("LPG", "LPG", "液化石油气 LPG", 80),
    _c("METHANOL", "Methanol", "甲醇", 90),
    _c("AMMONIA", "Ammonia", "氨燃料", 100),
    _c("BIOFUEL", "Biofuel blend", "生物燃料掺混", 110),
]


MARKET_SYMBOLS: list[ItemTuple] = [
    _c("BDI", "Baltic Dry Index", "波罗的海干散货指数 BDI", 10),
    _c("BCI", "Baltic Capesize Index", "海岬型指数 BCI", 20),
    _c("BPI", "Baltic Panamax Index", "巴拿马型指数 BPI", 30),
    _c("BSI", "Baltic Supramax Index", "超灵便型指数 BSI", 40),
    _c("BHSI", "Baltic Handysize Index", "灵便型指数 BHSI", 50),
    _c("BDTI", "Baltic Dirty Tanker Index", "原油油轮指数 BDTI", 60),
    _c("BCTI", "Baltic Clean Tanker Index", "成品油轮指数 BCTI", 70),
    _c("FFA-C5", "FFA Capesize C5", "海岬型 FFA C5", 80),
    _c("FFA-P3A", "FFA Panamax P3A", "巴拿马型 FFA P3A", 90),
    _c("USDJPY", "USD/JPY", "美元兑日元", 200),
    _c("USDCNY", "USD/CNY", "美元兑人民币", 210),
    _c("EURUSD", "EUR/USD", "欧元兑美元", 220),
]


UNITS: list[ItemTuple] = [
    _c("MT", "Metric ton", "公吨", 10),
    _c("M3", "Cubic metre", "立方米", 20),
    _c("BBL", "Barrel", "桶", 30),
    _c("TEU", "TEU", "标箱 TEU", 40),
    _c("DAY", "Day", "天", 50),
    _c("NM", "Nautical mile", "海里", 60),
    _c("KN", "Knot", "节", 70),
    _c("KT", "Kilotonne", "千吨", 80),
]


COUNTERPARTY_TYPES: list[ItemTuple] = [
    _c("charterer", "Charterer", "租船人", 10),
    _c("owner", "Owner / Shipowner", "船东", 20),
    _c("broker", "Broker", "经纪人", 30),
    _c("agent", "Agent", "代理", 40),
    _c("shipper", "Shipper", "托运人", 50),
    _c("consignee", "Consignee", "收货人", 60),
    _c("supplier", "Supplier", "供应商", 70),
    _c("operator", "Operator", "经营人", 80),
    _c("other", "Other", "其他", 909),
]


DATASETS: list[dict] = [
    {
        "code": "countries",
        "name_en": "Countries / Flags",
        "name_zh": "国家 / 船旗",
        "description_en": "ISO 3166-1 alpha-2 country and flag codes",
        "description_zh": "ISO 3166-1 双字母国家/船旗代码",
        "sort_order": 10,
        "items": COUNTRIES,
    },
    {
        "code": "timezones",
        "name_en": "Time zones",
        "name_zh": "时区",
        "description_en": "IANA time zones",
        "description_zh": "IANA 时区标识",
        "sort_order": 20,
        "items": None,  # built at seed via build_timezones()
    },
    {
        "code": "currencies",
        "name_en": "Currencies",
        "name_zh": "货币",
        "description_en": "ISO 4217 currency codes",
        "description_zh": "ISO 4217 货币代码",
        "sort_order": 30,
        "items": CURRENCIES,
    },
    {
        "code": "vessel_types",
        "name_en": "Vessel types",
        "name_zh": "船型",
        "description_en": "Commercial vessel type codes",
        "description_zh": "商船船型代码",
        "sort_order": 40,
        "items": VESSEL_TYPES,
    },
    {
        "code": "fuel_grades",
        "name_en": "Fuel grades",
        "name_zh": "燃油牌号",
        "description_en": "Marine bunker grades",
        "description_zh": "船用燃油牌号",
        "sort_order": 50,
        "items": FUEL_GRADES,
    },
    {
        "code": "market_symbols",
        "name_en": "Market symbols",
        "name_zh": "市场指数 / 品种",
        "description_en": "Baltic / FFA / FX symbols",
        "description_zh": "波罗的海指数、FFA、汇率品种",
        "sort_order": 60,
        "items": MARKET_SYMBOLS,
    },
    {
        "code": "units",
        "name_en": "Units of measure",
        "name_zh": "计量单位",
        "description_en": "Common maritime units",
        "description_zh": "航运常用计量单位",
        "sort_order": 70,
        "items": UNITS,
    },
    {
        "code": "counterparty_types",
        "name_en": "Counterparty types",
        "name_zh": "对手方类型",
        "description_en": "Business relationship types for counterparties",
        "description_zh": "对手方业务关系类型",
        "sort_order": 80,
        "items": COUNTERPARTY_TYPES,
    },
]


def iter_system_items(dataset_code: str) -> Iterable[ItemTuple]:
    if dataset_code == "timezones":
        return build_timezones()
    for ds in DATASETS:
        if ds["code"] == dataset_code and ds["items"] is not None:
            return ds["items"]
    return []
