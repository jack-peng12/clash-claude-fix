"""Initial (v1) business skills.

The six internal training documents have NOT been provided yet. Every skill therefore lists them
under `sources` with status "未提供", and the v1 rules below are general industry rules written by
the developer, to be replaced/confirmed once the documents are imported. Do not treat them as
company policy until a human reviewer activates a version that cites the documents.
"""

TRAINING_DOCS = [
    "《海外资源培训文档终版》",
    "《海外资源培训手册·精简执行版》",
    "《董事沟通话术》",
    "《董事开场白和资料》",
    "《海外受薪董事渠道合作落地方案》",
    "《渠道合作全套配套物料清单》",
]


def _sources(relevant: list[int]) -> list[dict]:
    return [
        {"doc": TRAINING_DOCS[i], "section": "", "status": "未提供，待导入后逐条对照"}
        for i in relevant
    ] + [{"doc": "开发者通用行业规则 v1", "section": "全部", "status": "临时规则，待业务负责人确认"}]


GLOBAL_BOUNDARIES = [
    "AI 无权签约、付款、承诺成交、承诺价格或接受任何付款条款。",
    "供应商口头/邮件声明只能记为“供应商声称”，不得记为已核验事实。",
    "平台历史（如是否注册过亚马逊）无法由 AI 核实，一律标记为待人工核验。",
    "供应商一旦被人工接管，AI 停止一切自动对外沟通。",
    "明确拒绝或要求停止联系的供应商，永久停止自动消息。",
]

# --------------------------------------------------------------------------------------------
# Criteria catalog: shared by parsing, screening, inquiry and reply analysis.
# Keyword matching is case-insensitive substring matching on page/message text.
# --------------------------------------------------------------------------------------------
CRITERIA = [
    {
        "key": "inventory",
        "label": "有现成公司库存",
        "zh_keywords": ["现成公司", "库存"],
        "positive": ["shelf compan", "ready made compan", "ready-made compan", "readymade compan",
                     "off the shelf", "off-the-shelf", "aged compan", "vintage compan",
                     "vorratsgesellschaft", "vorrats-gmbh", "mantelgesellschaft", "gmbh kaufen",
                     "società pronta", "societa pronta", "srl pronta", "sociedad preconstituida",
                     "sociedades preconstituidas", "société prête", "ready company", "companies for sale",
                     "company for sale", "ready-made s.r.o", "ready made s.r.o", "hotová společnost",
                     "ready-made ltd", "shelf ltd", "existing compan", "ready-to-use compan",
                     "we have available", "currently available", "in stock"],
        "negative": ["no shelf compan", "do not sell compan", "don't sell compan", "no longer sell",
                     "not available at the moment", "out of stock", "no companies available"],
        "question_en": "Do you currently have ready-made (shelf) companies available? Could you share a list with incorporation dates?",
        "question_zh": "目前是否有现成公司库存？能否提供清单及成立日期？",
    },
    {
        "key": "vat_registered",
        "label": "已注册VAT",
        "zh_keywords": ["vat", "增值税"],
        "positive": ["vat registered", "vat-registered", "with vat", "vat number", "vat registration",
                     "ust-idnr", "umsatzsteuer-id", "partita iva", "nif-iva", "vat certificate", "registered for vat"],
        "negative": ["without vat", "non-vat", "not vat registered", "no vat registration", "not registered for vat"],
        "question_en": "Is the company already VAT registered (and which VAT scheme)?",
        "question_zh": "公司是否已注册VAT（何种VAT方案）？",
    },
    {
        "key": "eori",
        "label": "EORI",
        "zh_keywords": ["eori"],
        "positive": ["eori"],
        "negative": ["no eori", "without eori"],
        "question_en": "Does the company have an EORI number?",
        "question_zh": "公司是否有EORI号？",
    },
    {
        "key": "bank_account",
        "label": "附带企业银行账户",
        "zh_keywords": ["银行", "账户", "对公"],
        "positive": ["bank account", "business account", "corporate account", "bankkonto", "geschäftskonto",
                     "conto corrente", "cuenta bancaria", "bankovní účet", "compte bancaire"],
        "negative": ["no bank account", "without bank account", "bank account not included",
                     "bank account is not included", "does not include a bank account"],
        "question_en": "Does the company come with an existing business bank account? Which bank?",
        "question_zh": "是否附带企业银行账户？哪家银行？",
    },
    {
        "key": "director_continue",
        "label": "董事可继续任职并配合审核",
        "zh_keywords": ["董事"],
        "positive": ["nominee director", "director service", "local director", "resident director",
                     "director can remain", "director will remain", "director can stay", "director is willing",
                     "geschäftsführer", "amministratore", "administrador", "jednatel"],
        "negative": ["director will resign", "director cannot remain", "no director service",
                     "director must be replaced", "director can't remain", "director can not remain"],
        "question_en": "Can the current director remain in office after the transfer and cooperate with platform verification (ID, video call)?",
        "question_zh": "现任董事交割后能否继续任职并配合平台审核（证件、视频验证）？",
    },
    {
        "key": "no_ecommerce_history",
        "label": "未以公司主体注册过电商平台（如亚马逊）",
        "zh_keywords": ["亚马逊", "amazon", "电商平台", "未注册过"],
        "positive": ["never registered on amazon", "no amazon history", "never traded", "dormant",
                     "no trading history", "no marketplace history", "never used for amazon"],
        "negative": ["amazon account included", "existing amazon account", "used on amazon",
                     "previously sold on amazon", "has an amazon seller account"],
        "question_en": "Has the company ever been registered as a seller on Amazon or any other online marketplace?",
        "question_zh": "该公司是否曾以公司主体注册过亚马逊或其他电商平台卖家账户？",
        "always_human_verify": True,
    },
    {
        "key": "incorporation_age",
        "label": "成立时间",
        "zh_keywords": ["成立", "年以上", "老公司"],
        "positive": ["aged compan", "vintage compan", "year old compan", "years old compan"],
        "negative": [],
        "question_en": "When was each available company incorporated?",
        "question_zh": "可售公司分别成立于何时？",
    },
    {
        "key": "trading_history",
        "label": "历史经营记录",
        "zh_keywords": ["经营记录", "经营历史", "有流水"],
        "positive": ["trading history", "with turnover", "trading compan", "revenue history"],
        "negative": ["never traded", "dormant", "no trading history"],
        "question_en": "Does the company have any trading history or has it been dormant since incorporation?",
        "question_zh": "公司是否有经营历史，还是成立后一直休眠？",
    },
    {
        "key": "no_debt_litigation",
        "label": "无债务、诉讼和税务异常",
        "zh_keywords": ["债务", "诉讼", "干净", "税务异常"],
        "positive": ["no liabilities", "no debts", "free of liabilities", "clean history", "lastenfrei",
                     "schuldenfrei", "good standing", "no outstanding", "debt-free", "debt free"],
        "negative": ["has liabilities", "outstanding debt", "pending litigation", "tax arrears"],
        "question_en": "Can you confirm the company has no debts, litigation or tax arrears, and provide a certificate of good standing?",
        "question_zh": "能否确认无债务、诉讼及欠税，并提供良好存续证明？",
    },
    {
        "key": "tax_filing_ok",
        "label": "税务登记及申报正常",
        "zh_keywords": ["申报", "税务登记", "年报"],
        "positive": ["accounts filed", "tax returns filed", "confirmation statement", "annual return",
                     "filings up to date", "up to date with filings"],
        "negative": ["overdue accounts", "late filing", "struck off"],
        "question_en": "Are all statutory filings and tax returns up to date?",
        "question_zh": "所有法定申报和税务申报是否均已按时完成？",
    },
    {
        "key": "paid_up_capital",
        "label": "注册资本及实缴证明",
        "zh_keywords": ["注册资本", "实缴"],
        "positive": ["paid-up capital", "paid up capital", "share capital", "stammkapital", "capitale sociale",
                     "capital social", "fully paid"],
        "negative": [],
        "question_en": "What is the registered share capital and is it fully paid up (with proof)?",
        "question_zh": "注册资本多少，是否已实缴并可提供证明？",
    },
    {
        "key": "real_address_lease",
        "label": "真实商业地址及租赁文件",
        "zh_keywords": ["地址", "租赁", "办公室"],
        "positive": ["office lease", "lease agreement", "physical office", "business address",
                     "registered office", "geschäftsadresse", "virtual office"],
        "negative": ["no address service", "address not included"],
        "question_en": "Is a real business address with a lease agreement included or available?",
        "question_zh": "是否包含真实商业地址及租赁合同？",
    },
    {
        "key": "annual_maintenance",
        "label": "公司年度维护",
        "zh_keywords": ["年度维护", "年审", "记账", "秘书"],
        "positive": ["annual maintenance", "company secretary", "accounting service", "bookkeeping",
                     "annual renewal", "compliance service"],
        "negative": [],
        "question_en": "Do you offer annual maintenance (accounting, filings, registered office) and at what cost?",
        "question_zh": "是否提供年度维护（记账、申报、注册地址）及费用？",
    },
    {
        "key": "price",
        "label": "收购价格",
        "zh_keywords": ["价格", "报价", "预算", "费用"],
        "positive": [],
        "negative": [],
        "question_en": "What is the price for each available company, and what exactly is included?",
        "question_zh": "每家公司的价格是多少，具体包含哪些内容？",
    },
    {
        "key": "delivery_time",
        "label": "交付周期",
        "zh_keywords": ["交付", "周期", "多久"],
        "positive": ["within 24 hours", "same day", "within 48 hours", "transfer within", "delivered within",
                     "turnaround"],
        "negative": [],
        "question_en": "How long does the transfer take from agreement to completed handover?",
        "question_zh": "从确认到完成交割需要多长时间？",
    },
    {
        "key": "long_term_supply",
        "label": "长期供应能力",
        "zh_keywords": ["长期", "批量", "持续供应"],
        "positive": ["regular supply", "bulk", "volume discount", "partner program", "reseller"],
        "negative": [],
        "question_en": "Are you able to supply companies on a regular basis, and do you offer partner or volume terms?",
        "question_zh": "能否长期持续供货，是否有合作伙伴或批量条件？",
    },
]

LEVELS = {
    "required": "必须满足",
    "preferred": "优先满足",
    "not_required": "不作要求",
    "to_confirm": "待确认",
}

SEARCH_TEMPLATES = {
    "en": ["buy ready made company {country}", "{country} shelf company for sale",
           "aged {country} company for sale with bank account", "{country} {ctype} shelf company VAT registered",
           "off the shelf company {country} provider", "{country} ready-made company with nominee director"],
    "de": ["Vorratsgesellschaft kaufen {country_local}", "Vorrats-GmbH kaufen", "GmbH Mantel kaufen {country_local}",
           "Vorratsgesellschaft mit USt-IdNr"],
    "it": ["società pronta vendita {country_local}", "srl pronta acquisto", "società già costituita in vendita"],
    "es": ["sociedad preconstituida {country_local}", "comprar sociedad preconstituida", "empresa ya constituida en venta"],
    "fr": ["société prête à l'emploi {country_local}", "acheter société déjà immatriculée"],
    "cs": ["ready made s.r.o. prodej", "prodej hotových společností", "hotová s.r.o. na prodej"],
    "nl": ["kant-en-klare BV kopen", "BV kopen {country_local}"],
    "pl": ["gotowa spółka z o.o. sprzedaż", "gotowe spółki na sprzedaż"],
    "mt": ["malta shelf company for sale", "ready made company malta"],
    "ar": ["شركة جاهزة للبيع {country_local}"],
}

SEARCH_BLOCKLIST = [
    "wikipedia.org", "youtube.com", "facebook.com", "linkedin.com", "reddit.com", "twitter.com", "x.com",
    "instagram.com", "quora.com", "gov.uk", "europa.eu", "amazon.com", "amazon.de", "amazon.co.uk",
    "investopedia.com", "medium.com", "tiktok.com", "pinterest.com", "bing.com", "duckduckgo.com",
    "google.com", "indeed.com", "glassdoor.com", "trustpilot.com", "find-and-update.company-information.service.gov.uk",
]

RISK_RULES = [
    {"pattern": "guaranteed amazon approval", "level": "high", "reason": "承诺平台审核必过，疑似违规服务"},
    {"pattern": "bypass verification", "level": "high", "reason": "宣称绕过平台审核"},
    {"pattern": "bypass kyc", "level": "high", "reason": "宣称绕过KYC"},
    {"pattern": "no kyc", "level": "high", "reason": "无KYC，合规风险"},
    {"pattern": "fake document", "level": "high", "reason": "涉及伪造文件"},
    {"pattern": "rent identity", "level": "high", "reason": "身份租借"},
    {"pattern": "rent an identity", "level": "high", "reason": "身份租借"},
    {"pattern": "stealth account", "level": "high", "reason": "隐身账户/规避封号"},
    {"pattern": "crypto only", "level": "medium", "reason": "仅接受加密货币付款"},
    {"pattern": "payment upfront in full", "level": "medium", "reason": "要求全额预付"},
    {"pattern": "100% upfront", "level": "medium", "reason": "要求全额预付"},
    {"pattern": "western union", "level": "medium", "reason": "不可追溯付款方式"},
    {"pattern": "struck off", "level": "medium", "reason": "公司可能已被注销"},
    {"pattern": "pending litigation", "level": "medium", "reason": "存在诉讼"},
    {"pattern": "tax arrears", "level": "medium", "reason": "存在欠税"},
]

INTENT_SIGNALS = [
    {"key": "has_inventory", "label": "确认有可售现成公司",
     "patterns": ["we have", "available", "in stock", "we can offer", "we currently have", "attached is the list",
                  "list of available", "following companies"], "weight": 30},
    {"key": "provided_price", "label": "提供了报价", "patterns": ["__PRICE__"], "weight": 30},
    {"key": "matches_criteria", "label": "回复中确认满足必须条件", "patterns": ["__CRITERIA_MET__"], "weight": 20},
    {"key": "willing", "label": "表达合作意愿",
     "patterns": ["happy to", "glad to", "would be pleased", "interested in working", "look forward to working",
                  "we can help", "we would be happy", "let's proceed", "ready to proceed", "pleased to assist"],
     "weight": 15},
    {"key": "documents", "label": "提供或愿意提供文件",
     "patterns": ["attached", "please find", "we can provide documents", "certificate of incorporation",
                  "can send the documents", "due diligence pack"], "weight": 10},
    {"key": "next_steps", "label": "询问下一步（合同/付款/会议）",
     "patterns": ["next step", "contract", "invoice", "payment", "call", "meeting", "zoom", "proceed"],
     "weight": 5},
]

OPT_OUT_PATTERNS = [
    "unsubscribe", "do not contact", "don't contact", "stop emailing", "remove me", "remove us",
    "not interested", "no longer interested", "please stop", "we do not sell", "we don't sell",
    "we do not offer", "we don't offer", "not a service we offer", "stop contacting",
]

FORBIDDEN_OUTBOUND = [
    "we agree to pay", "we will pay", "payment has been", "we accept your terms", "we confirm the purchase",
    "deal confirmed", "we will sign", "we hereby agree", "we commit to buy", "consider it sold",
    "bank transfer details", "我们同意付款", "确认购买", "我们签约",
]

OUTREACH_TEMPLATE = {
    "subject": "Enquiry: ready-made {country} companies – {supplier_name}",
    "body": (
        "Dear {supplier_name} team,\n\n"
        "I came across your website ({website}){service_hint}. We are {company_name}, a cross-border "
        "e-commerce company, and we regularly look for ready-made companies in {country} for our own "
        "legitimate operations.\n\n"
        "Could you help us with the following?\n{questions}\n"
        "If it is easier, a current list of available companies with prices would be a great start.\n\n"
        "If this is not relevant to you, just let us know and we will not write again.\n\n"
        "{signature}"
    ),
}

CLARIFY_TEMPLATE = {
    "subject": "Re: {subject}",
    "body": (
        "Dear {contact_name},\n\nThank you for your reply{ack}. To evaluate the options properly, could you "
        "also let us know:\n{questions}\n\n{signature}"
    ),
}

FOLLOWUP_TEMPLATE = {
    "subject": "Re: {subject}",
    "body": (
        "Dear {contact_name},\n\nI wanted to follow up on my earlier message about ready-made {country} "
        "companies. Are any currently available? Even a short reply with a price list would help.\n\n"
        "{signature}"
    ),
}


def default_skills() -> list[dict]:
    return [
        {
            "key": "search",
            "name": "全球资源搜索Skill",
            "description": "根据结构化采购需求生成多语言关键词，筛除非供应商来源，并按结果反馈调整关键词。",
            "content": {
                "inputs": ["采购需求 spec（国家、公司类型、条件）", "已使用关键词及其产出"],
                "outputs": ["本轮搜索关键词列表（语言、来源）", "候选网址相关度判断"],
                "rules": {
                    "templates": SEARCH_TEMPLATES,
                    "blocklist": SEARCH_BLOCKLIST,
                    "relevance_keywords": CRITERIA[0]["positive"] + ["company formation", "incorporation services",
                                                                     "company registration agent"],
                    "min_relevance_hits": 1,
                    "adaptive_min_term_freq": 2,
                    "max_queries_per_round": 6,
                },
                "decision_rules": [
                    "每个目标国家至少使用英文 + 当地语言关键词。",
                    "已使用过的关键词不再重复使用；按“新供应商产出”排序优先继续扩展高产出方向。",
                    "从高相关结果标题中提取高频词组生成新关键词（自适应）。",
                    "社交平台、政府登记处、百科、电商平台链接不作为供应商官网。",
                ],
                "sources": _sources([0, 1]),
                "boundaries": GLOBAL_BOUNDARIES[:1] + ["只访问公开可访问网页，遵守 robots.txt，不绕过验证码或登录。"],
                "exceptions": ["搜索引擎限流/失败：记录错误、该关键词标记失败，下一轮重试。",
                               "全部关键词无结果：通知员工检查需求或补充关键词模板。"],
                "test_cases": [
                    {"name": "英国任务生成英文关键词",
                     "input": {"spec": {"countries": [{"name": "United Kingdom", "langs": ["en"], "local": "UK"}],
                                        "company_types": ["Ltd"]}},
                     "expect": {"queries_contain": "shelf company", "min_queries": 3}},
                    {"name": "德国任务包含德语关键词",
                     "input": {"spec": {"countries": [{"name": "Germany", "langs": ["de", "en"], "local": "Deutschland"}],
                                        "company_types": ["GmbH"]}},
                     "expect": {"queries_contain": "Vorratsgesellschaft", "min_queries": 3}},
                    {"name": "社交平台不作为供应商",
                     "input": {"url": "https://www.facebook.com/somepage", "text": "shelf company for sale"},
                     "expect": {"relevant": False}},
                ],
                "pending_conflicts": [],
            },
        },
        {
            "key": "screening",
            "name": "现成公司筛选Skill",
            "description": "按采购条件（必须/优先/不作要求/待确认）对供应商证据逐项判定，输出符合/不符合/资料不足/风险较高。",
            "content": {
                "inputs": ["供应商事实（含证据状态）", "采购任务条件及等级"],
                "outputs": ["分类 match/no_match/insufficient/high_risk", "得分 0-100", "逐项判定及缺失项"],
                "rules": {
                    "criteria": CRITERIA,
                    "levels": LEVELS,
                    "weights": {"required": 3, "preferred": 1, "to_confirm": 0, "not_required": 0},
                    "contact_categories": ["match", "insufficient"],
                    "web_negative_is_fail": False,
                },
                "decision_rules": [
                    "供应商网站无任何现成公司/公司注册服务相关内容 → 不符合。",
                    "任一“必须满足”条件被供应商回复/文件/人工核验明确否定 → 不符合。",
                    "网站上的反向表述（web_negative_is_fail=false 时）只记为待确认并在询价中追问，不直接淘汰。",
                    "风险分级为高 → 风险较高（不自动联系，转人工复核）。",
                    "所有“必须满足”条件均有正向证据 → 符合。",
                    "其余情况 → 资料不足（自动发询价补齐）。",
                    "网站声明属于“网站声称”，不等于已核验。",
                ],
                "sources": _sources([0, 1]),
                "boundaries": GLOBAL_BOUNDARIES,
                "exceptions": ["网页无法访问：分类为资料不足并记录采集失败原因。"],
                "test_cases": [
                    {"name": "全部必须条件有证据→符合",
                     "input": {"relevant": True,
                               "levels": {"vat_registered": "required", "bank_account": "required"},
                               "facts": {"vat_registered": "yes", "bank_account": "yes"}, "risk": "low"},
                     "expect": {"category": "match"}},
                    {"name": "必须条件明确不满足→不符合",
                     "input": {"relevant": True, "levels": {"bank_account": "required"},
                               "facts": {"bank_account": "no"}, "risk": "low"},
                     "expect": {"category": "no_match"}},
                    {"name": "缺证据→资料不足",
                     "input": {"relevant": True, "levels": {"vat_registered": "required", "bank_account": "required"},
                               "facts": {"vat_registered": "yes"}, "risk": "low"},
                     "expect": {"category": "insufficient"}},
                    {"name": "高风险优先",
                     "input": {"relevant": True, "levels": {}, "facts": {}, "risk": "high"},
                     "expect": {"category": "high_risk"}},
                    {"name": "非现成公司供应商→不符合",
                     "input": {"relevant": False, "levels": {}, "facts": {}, "risk": "low"},
                     "expect": {"category": "no_match"}},
                ],
                "pending_conflicts": [],
            },
        },
        {
            "key": "due_diligence",
            "name": "供应商尽调Skill",
            "description": "根据已有事实生成需人工核验的清单及所需文件，区分网站声称/供应商声称/已提供文件/人工已核验。",
            "content": {
                "inputs": ["供应商事实及证据状态"],
                "outputs": ["待核验清单（条件、当前状态、所需文件）"],
                "rules": {
                    "documents": {
                        "inventory": "公司注册证书、公司章程、最新登记摘录",
                        "incorporation_age": "注册证书（显示成立日期）",
                        "vat_registered": "VAT 证书 / 税务局登记回执",
                        "eori": "EORI 登记确认",
                        "bank_account": "银行出具的账户证明（交割前不得要求转账）",
                        "director_continue": "董事书面同意继续任职 + 身份证明",
                        "no_ecommerce_history": "卖方书面声明 + 人工在平台侧核查（AI无法核实）",
                        "no_debt_litigation": "良好存续证明、无债务声明",
                        "tax_filing_ok": "最近年度申报回执",
                        "paid_up_capital": "实缴证明 / 银行出资证明",
                        "real_address_lease": "租赁合同及地址证明",
                    },
                    "verified_statuses": ["human_verified"],
                },
                "decision_rules": ["除 human_verified 外的所有事实均进入待核验清单。",
                                   "标记 always_human_verify 的条件即使供应商提供文件也必须人工核验。"],
                "sources": _sources([0, 1, 5]),
                "boundaries": GLOBAL_BOUNDARIES,
                "exceptions": ["供应商拒绝提供文件：记录并降低意向评分，由人工决定。"],
                "test_cases": [
                    {"name": "供应商声称VAT仍需核验",
                     "input": {"facts": {"vat_registered": "supplier_claim"}},
                     "expect": {"pending_contains": "vat_registered"}},
                    {"name": "人工核验后不再待核验",
                     "input": {"facts": {"vat_registered": "human_verified"}},
                     "expect": {"pending_not_contains": "vat_registered"}},
                ],
                "pending_conflicts": [],
            },
        },
        {
            "key": "outreach",
            "name": "商务开发和破冰Skill",
            "description": "结合供应商网站内容生成个性化首封开发信，并拦截越权表述。",
            "content": {
                "inputs": ["供应商名称/官网/服务摘录", "采购任务", "待问问题"],
                "outputs": ["邮件主题和正文（英文，LLM可用时可按当地语言）"],
                "rules": {
                    "template": OUTREACH_TEMPLATE,
                    "forbidden_phrases": FORBIDDEN_OUTBOUND,
                    "max_questions_first_mail": 4,
                    "first_mail_question_order": ["inventory", "price", "vat_registered", "bank_account",
                                                  "director_continue", "no_ecommerce_history"],
                },
                "decision_rules": ["必须提到供应商名称和其网站上的具体服务。",
                                   "只询问信息，不承诺购买、价格或付款。",
                                   "命中禁用表述的内容不得发送。"],
                "sources": _sources([2, 3]),
                "boundaries": GLOBAL_BOUNDARIES,
                "exceptions": ["无可用邮箱：转为“人工确认”动作（联系表单/电话）。"],
                "test_cases": [
                    {"name": "开发信包含供应商名称且无越权表述",
                     "input": {"supplier_name": "Acme Formations", "country": "United Kingdom",
                               "questions": ["inventory", "price"]},
                     "expect": {"body_contains": "Acme Formations", "no_forbidden": True}},
                    {"name": "越权表述被拦截",
                     "input": {"check_text": "Great, we will pay the deposit today."},
                     "expect": {"blocked": True}},
                ],
                "pending_conflicts": [],
            },
        },
        {
            "key": "inquiry",
            "name": "初步询价和基础沟通Skill",
            "description": "解析供应商回复，记录已回答内容，只追问尚未回答的问题。",
            "content": {
                "inputs": ["供应商回复正文", "问题状态（已问次数/是否已答）", "任务条件"],
                "outputs": ["已回答问题及摘录", "下一封追问的问题列表", "报价金额/币种"],
                "rules": {
                    "template": CLARIFY_TEMPLATE,
                    "max_questions_per_message": 3,
                    "max_asks_per_question": 2,
                    "ask_levels": ["required", "to_confirm", "preferred"],
                },
                "decision_rules": ["已回答的问题永不重复询问。",
                                   "同一问题最多询问 max_asks_per_question 次。",
                                   "按 必须→待确认→优先 顺序追问。",
                                   "回复中的信息一律记为“供应商声称”。"],
                "sources": _sources([1, 2]),
                "boundaries": GLOBAL_BOUNDARIES,
                "exceptions": ["无法识别回复语言或内容：保留原文，提醒人工查看，不自动回复。"],
                "test_cases": [
                    {"name": "已回答的VAT不再追问",
                     "input": {"reply": "Yes, the company is VAT registered. Price is GBP 1,500.",
                               "levels": {"vat_registered": "required", "bank_account": "required"},
                               "answered": []},
                     "expect": {"answered_contains": "vat_registered", "next_not_contains": "vat_registered",
                                "next_contains": "bank_account"}},
                    {"name": "识别报价",
                     "input": {"reply": "The price is EUR 2.900 including transfer.", "levels": {}, "answered": []},
                     "expect": {"price_found": True}},
                ],
                "pending_conflicts": [],
            },
        },
        {
            "key": "followup",
            "name": "自动跟进Skill",
            "description": "对未回复或资料不全的供应商按节奏跟进；拒绝、退订、接管后立即停止。",
            "content": {
                "inputs": ["供应商状态", "最后发出/收到时间", "已跟进次数"],
                "outputs": ["动作 followup/wait/stop 及原因"],
                "rules": {
                    "template": FOLLOWUP_TEMPLATE,
                    "schedule_days": [3, 7, 14],
                    "max_followups": 3,
                    "opt_out_patterns": OPT_OUT_PATTERNS,
                    "stop_statuses": ["human_takeover", "opted_out", "rejected", "closed"],
                },
                "decision_rules": ["已退订/拒绝/人工接管 → stop。",
                                   "供应商最后一条消息晚于我方最后一条 → wait（等待AI或人工处理回复）。",
                                   "距上次发出天数 ≥ schedule_days[已跟进次数] → followup。",
                                   "已达 max_followups → stop。"],
                "sources": _sources([1]),
                "boundaries": GLOBAL_BOUNDARIES,
                "exceptions": ["邮件退信：标记该联系方式无效，尝试其他邮箱；无其他邮箱则停止。"],
                "test_cases": [
                    {"name": "3天未回复→跟进",
                     "input": {"status": "contacted", "days_since_out": 4, "followups": 0, "replied_after": False},
                     "expect": {"action": "followup"}},
                    {"name": "人工接管→停止",
                     "input": {"status": "human_takeover", "days_since_out": 10, "followups": 0, "replied_after": False},
                     "expect": {"action": "stop"}},
                    {"name": "达到上限→停止",
                     "input": {"status": "contacted", "days_since_out": 30, "followups": 3, "replied_after": False},
                     "expect": {"action": "stop"}},
                    {"name": "退订语句识别", "input": {"reply": "Please remove me from your list."},
                     "expect": {"opt_out": True}},
                ],
                "pending_conflicts": [],
            },
        },
        {
            "key": "risk",
            "name": "风险分级Skill",
            "description": "根据网页和回复中的风险信号对供应商分级（低/中/高）。",
            "content": {
                "inputs": ["网页文本", "回复文本"],
                "outputs": ["风险等级", "命中规则及原因"],
                "rules": {"patterns": RISK_RULES},
                "decision_rules": ["命中任一 high 规则 → 高风险。", "命中 medium 规则 → 中风险。", "否则低风险。"],
                "sources": _sources([0, 4]),
                "boundaries": GLOBAL_BOUNDARIES,
                "exceptions": ["风险规则冲突（同一来源多种说法）：取最高等级并提示人工。"],
                "test_cases": [
                    {"name": "承诺审核必过→高风险", "input": {"text": "Guaranteed Amazon approval for all our companies"},
                     "expect": {"level": "high"}},
                    {"name": "正常服务→低风险", "input": {"text": "We sell UK shelf companies with VAT."},
                     "expect": {"level": "low"}},
                ],
                "pending_conflicts": [],
            },
        },
        {
            "key": "handoff",
            "name": "高意向人工接管Skill",
            "description": "综合多项信号计算意向分，达到阈值或满足组合条件时转人工，并停止AI对外沟通。",
            "content": {
                "inputs": ["回复分析结果（信号、报价、已满足条件）", "供应商筛选分类"],
                "outputs": ["意向分 0-100", "意向等级", "是否转人工及原因"],
                "rules": {
                    "signals": INTENT_SIGNALS,
                    "levels": {"high": 60, "medium": 35, "low": 10},
                    "handoff_threshold": 60,
                    "hard_combos": [["has_inventory", "provided_price"], ["provided_price", "matches_criteria"]],
                    "single_keyword_cap": 15,
                },
                "decision_rules": ["单个关键词（如 contract/payment）最多贡献 single_keyword_cap 分，不能单独触发转人工。",
                                   "意向分 ≥ handoff_threshold → 转人工。",
                                   "命中任一 hard_combos 组合 → 转人工。",
                                   "转人工后 AI 只做整理、翻译、比价、拟稿，不再发送。"],
                "sources": _sources([0, 1, 2]),
                "boundaries": GLOBAL_BOUNDARIES,
                "exceptions": ["高风险供应商达到阈值：仍转人工，但在通知中标注风险。"],
                "test_cases": [
                    {"name": "有库存+报价→转人工",
                     "input": {"reply": "We currently have 3 UK companies available. Price is GBP 1,200 each."},
                     "expect": {"handoff": True}},
                    {"name": "仅提到合同不转人工",
                     "input": {"reply": "What kind of contract do you usually use?"},
                     "expect": {"handoff": False}},
                    {"name": "拒绝不转人工", "input": {"reply": "Sorry, we do not sell companies."},
                     "expect": {"handoff": False}},
                ],
                "pending_conflicts": [],
            },
        },
    ]
