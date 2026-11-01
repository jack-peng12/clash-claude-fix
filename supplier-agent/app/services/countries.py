# (zh aliases, English name, ISO2, languages, local name, ccTLD)
COUNTRIES = [
    (["美国", "美利坚"], "United States", "US", ["en"], "USA", "us"),
    (["英国"], "United Kingdom", "GB", ["en"], "UK", "uk"),
    (["德国"], "Germany", "DE", ["de", "en"], "Deutschland", "de"),
    (["意大利"], "Italy", "IT", ["it", "en"], "Italia", "it"),
    (["西班牙"], "Spain", "ES", ["es", "en"], "España", "es"),
    (["法国"], "France", "FR", ["fr", "en"], "France", "fr"),
    (["捷克"], "Czech Republic", "CZ", ["cs", "en"], "Česko", "cz"),
    (["马耳他"], "Malta", "MT", ["en", "mt"], "Malta", "mt"),
    (["埃及"], "Egypt", "EG", ["en", "ar"], "مصر", "eg"),
    (["荷兰"], "Netherlands", "NL", ["nl", "en"], "Nederland", "nl"),
    (["波兰"], "Poland", "PL", ["pl", "en"], "Polska", "pl"),
    (["爱尔兰"], "Ireland", "IE", ["en"], "Ireland", "ie"),
    (["奥地利"], "Austria", "AT", ["de", "en"], "Österreich", "at"),
    (["瑞士"], "Switzerland", "CH", ["de", "fr", "en"], "Schweiz", "ch"),
    (["比利时"], "Belgium", "BE", ["nl", "fr", "en"], "Belgique", "be"),
    (["葡萄牙"], "Portugal", "PT", ["en"], "Portugal", "pt"),
    (["瑞典"], "Sweden", "SE", ["en"], "Sverige", "se"),
    (["丹麦"], "Denmark", "DK", ["en"], "Danmark", "dk"),
    (["挪威"], "Norway", "NO", ["en"], "Norge", "no"),
    (["芬兰"], "Finland", "FI", ["en"], "Suomi", "fi"),
    (["爱沙尼亚"], "Estonia", "EE", ["en"], "Eesti", "ee"),
    (["拉脱维亚"], "Latvia", "LV", ["en"], "Latvija", "lv"),
    (["立陶宛"], "Lithuania", "LT", ["en"], "Lietuva", "lt"),
    (["斯洛伐克"], "Slovakia", "SK", ["cs", "en"], "Slovensko", "sk"),
    (["匈牙利"], "Hungary", "HU", ["en"], "Magyarország", "hu"),
    (["罗马尼亚"], "Romania", "RO", ["en"], "România", "ro"),
    (["保加利亚"], "Bulgaria", "BG", ["en"], "България", "bg"),
    (["希腊"], "Greece", "GR", ["en"], "Ελλάδα", "gr"),
    (["塞浦路斯"], "Cyprus", "CY", ["en"], "Cyprus", "cy"),
    (["卢森堡"], "Luxembourg", "LU", ["fr", "de", "en"], "Luxembourg", "lu"),
    (["克罗地亚"], "Croatia", "HR", ["en"], "Hrvatska", "hr"),
    (["斯洛文尼亚"], "Slovenia", "SI", ["en"], "Slovenija", "si"),
    (["加拿大"], "Canada", "CA", ["en", "fr"], "Canada", "ca"),
    (["墨西哥"], "Mexico", "MX", ["es", "en"], "México", "mx"),
    (["巴西"], "Brazil", "BR", ["en"], "Brasil", "br"),
    (["澳大利亚", "澳洲"], "Australia", "AU", ["en"], "Australia", "au"),
    (["新西兰"], "New Zealand", "NZ", ["en"], "New Zealand", "nz"),
    (["日本"], "Japan", "JP", ["en"], "Japan", "jp"),
    (["新加坡"], "Singapore", "SG", ["en"], "Singapore", "sg"),
    (["香港"], "Hong Kong", "HK", ["en"], "Hong Kong", "hk"),
    (["阿联酋", "迪拜"], "United Arab Emirates", "AE", ["en", "ar"], "UAE", "ae"),
    (["沙特"], "Saudi Arabia", "SA", ["en", "ar"], "Saudi Arabia", "sa"),
    (["土耳其"], "Turkey", "TR", ["en"], "Türkiye", "tr"),
    (["印度"], "India", "IN", ["en"], "India", "in"),
    (["南非"], "South Africa", "ZA", ["en"], "South Africa", "za"),
    (["尼日利亚"], "Nigeria", "NG", ["en"], "Nigeria", "ng"),
    (["马来西亚"], "Malaysia", "MY", ["en"], "Malaysia", "my"),
    (["泰国"], "Thailand", "TH", ["en"], "Thailand", "th"),
    (["越南"], "Vietnam", "VN", ["en"], "Vietnam", "vn"),
    (["印度尼西亚", "印尼"], "Indonesia", "ID", ["en"], "Indonesia", "id"),
    (["菲律宾"], "Philippines", "PH", ["en"], "Philippines", "ph"),
    (["韩国"], "South Korea", "KR", ["en"], "Korea", "kr"),
]

COMPANY_TYPES = ["GmbH", "UG", "AG", "Ltd", "Limited", "LLC", "LLP", "PLC", "Inc", "Corp", "SRL", "S.r.l.",
                 "SL", "S.L.", "SA", "SAS", "SARL", "s.r.o.", "a.s.", "BV", "B.V.", "Sp. z o.o.", "OÜ", "Pty Ltd"]


def find_by_name(name: str):
    n = name.strip().lower()
    for zh, en, iso, langs, local, tld in COUNTRIES:
        if n in [z.lower() for z in zh] or n in (en.lower(), iso.lower(), local.lower()):
            return to_dict(zh, en, iso, langs, local, tld)
    return None


def to_dict(zh, en, iso, langs, local, tld) -> dict:
    return {"zh": zh[0], "name": en, "iso": iso, "langs": langs, "local": local, "tld": tld}
