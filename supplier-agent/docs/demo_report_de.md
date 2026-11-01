# 真实业务演示报告

- 生成时间（UTC）：2026-11-01 01:52:35
- 采购需求（员工输入）：找5家德国现成公司供应商，必须带VAT和企业银行账户，董事待确认，是否注册过亚马逊需确认，预算每家5000以内
- 解析结果：国家 ['Germany']，条件 `{"inventory": "required", "vat_registered": "required", "bank_account": "required", "director_continue": "to_confirm", "no_ecommerce_history": "to_confirm", "price": "required"}`，解析方式 rules
- 搜索+采集+筛选耗时：76 秒；任务统计：`{"cat_insufficient": 6, "outreach_queued": 6, "suppliers_new": 8, "outreach_manual": 2, "cat_match": 2}`

## 1. 真实搜索关键词与结果

| 关键词 | 语言 | 来源 | 状态 | 结果数 | 相关 | 新供应商 |
|---|---|---|---|---|---|---|
| Vorratsgesellschaft kaufen Deutschland | de | template | done | 7 | 7 | 6 |
| buy ready made company Germany | en | template | done | 10 | 8 | 2 |
| Vorrats-GmbH kaufen | de | template | done | 7 | 7 | 0 |
| Germany shelf company for sale | en | template | done | 10 | 10 | 0 |
| GmbH Mantel kaufen Deutschland | de | template | done | 10 | 4 | 0 |

## 2. 真实找到并建档的供应商

| # | 名称 | 域名 | 国家识别 | 符合度 | 得分 | 风险 | 邮箱 | 其他联系方式 | 网页证据数 | 事实条目 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | FORIS AG | foris.com | Germany | match | 100.0 | low | doina.roman@foris.com, info@foris.com, yvonne.riegel@foris.com, nils.weiland@foris.com | phone | 5 | 44 |
| 2 | EVOGE GmbH | evoge.de | Germany | insufficient | 80.0 | low | eichler@evoge.de, rolf.eichler@evoge.de, info@evoge.de | form, phone | 5 | 30 |
| 3 | DNotV GmbH | dnotv.de | Germany | insufficient | 80.0 | low | kontakt@dnotv.de |  | 5 | 16 |
| 4 | GmbH-UG.com | gmbh-ug.com | Germany | insufficient | 80.0 | low |  | facebook, linkedin, phone | 5 | 39 |
| 5 | Youco24 | youco24.de | Germany | insufficient | 80.0 | low | info@youco24.de | linkedin, phone | 5 | 38 |
| 6 | SiBa Wirtschaftskanzlei Berlin | siba-wirtschaftskanzlei.de | Germany | insufficient | 80.0 | low | post@siba-wirtschaftskanzlei.de, geldwaesche@senweb.berlin.de | linkedin, phone | 5 | 24 |
| 7 | Legasset Law Company | legasset.com | Germany | match | 100.0 | low | office@legasset.com, Alexandra.b@legasset.com, anna.s@legasset.com | phone, telegram, whatsapp | 5 | 43 |
| 8 | German Company | ressler-office.com | Germany | match | 100.0 | low |  |  | 5 | 37 |

### 判定原因

- **FORIS AG**（foris.com）：所有必须条件均有正向证据（未经人工核验）
- **EVOGE GmbH**（evoge.de）：缺少证据: 已注册VAT, 未以公司主体注册过电商平台（如亚马逊）
- **DNotV GmbH**（dnotv.de）：缺少证据: 已注册VAT, 未以公司主体注册过电商平台（如亚马逊）
- **GmbH-UG.com**（gmbh-ug.com）：缺少证据: 已注册VAT, 未以公司主体注册过电商平台（如亚马逊）
- **Youco24**（youco24.de）：缺少证据: 已注册VAT, 未以公司主体注册过电商平台（如亚马逊）
- **SiBa Wirtschaftskanzlei Berlin**（siba-wirtschaftskanzlei.de）：缺少证据: 已注册VAT, 未以公司主体注册过电商平台（如亚马逊）
- **Legasset Law Company**（legasset.com）：所有必须条件均有正向证据（未经人工核验）
- **German Company**（ressler-office.com）：所有必须条件均有正向证据（未经人工核验）

### 证据样例（事实 → 网页证据，可在后台点开原始HTML核对）

- `inventory`=yes（web_claim）← https://www.foris.com/vorratsgesellschaften/ sha256 `00afbbf77baad563` 采集于 2026-11-01 01:51 UTC：“e Gesellschaft binnen Stunden bei jedem Notar Ihrer Wahl übernehmen. Kaufpreis: ab 28.500 € inkl. Stammkapital 25.000 € Vorratsgesellschafte”
- `bank_account`=yes（web_claim）← https://www.foris.com/vorratsgesellschaften/ sha256 `00afbbf77baad563` 采集于 2026-11-01 01:51 UTC：“inkl. Stammkapital 25.000 € Vorratsgesellschaften. Sofort einsatzbereit. Unsere Vorratsgesellschaften sind sofort mit Bankkonto verfügbar, d”
- `director_continue`=yes（web_claim）← https://www.foris.com/vorratsgesellschaften/ sha256 `00afbbf77baad563` 采集于 2026-11-01 01:51 UTC：“e künftig geschäftlich auftreten soll. Dies geschieht direkt im Notartermin. Gleiches gilt für die Bestellung des neuen Geschäftsführers sow”
- `paid_up_capital`=yes（web_claim）← https://www.foris.com/vorratsgesellschaften/ sha256 `00afbbf77baad563` 采集于 2026-11-01 01:51 UTC：“t FORIS können Sie Ihre Gesellschaft binnen Stunden bei jedem Notar Ihrer Wahl übernehmen. Kaufpreis: ab 28.500 € inkl. Stammkapital 25.000 ”
- `real_address_lease`=yes（web_claim）← https://www.foris.com/vorratsgesellschaften/ sha256 `00afbbf77baad563` 采集于 2026-11-01 01:51 UTC：“lus-Paket Plug·n·Play FAQ Services für Gründungen & Unternehmen Transparenzregister ComfortPlus-Paket Steuer-Compliance Geschäftsadresse Ges”
- `price`=yes（web_claim）← https://www.foris.com/vorratsgesellschaften/ sha256 `00afbbf77baad563` 采集于 2026-11-01 01:51 UTC：“esellschaft binnen Stunden bei jedem Notar Ihrer Wahl übernehmen. Kaufpreis: ab 28.500 € inkl. Stammkapital 25.000 € Vorratsgesellschaften. ”
- `price`=yes（web_claim）← https://www.foris.com/vorratsgesellschaften/ sha256 `00afbbf77baad563` 采集于 2026-11-01 01:51 UTC：“ei jedem Notar Ihrer Wahl übernehmen. Kaufpreis: ab 28.500 € inkl. Stammkapital 25.000 € Vorratsgesellschaften. Sofort einsatzbereit. Unsere”
- `price`=yes（web_claim）← https://www.foris.com/vorratsgesellschaften/ sha256 `00afbbf77baad563` 采集于 2026-11-01 01:51 UTC：“oll und ganz auf den Start Ihres Unternehmens konzentrieren. GmbH Kaufpreis: ab 28.500 € inkl. Stammkapital 25.000 € Jetzt informieren UG Ka”

## 3. 自动建联（沙盒：真实 SMTP 发出，收件人被替换为测试邮箱）

| 消息 | 供应商 | 类型 | 原收件人 | 实际收件 | 状态 | 原因 |
|---|---|---|---|---|---|---|
| 1 | 1 | initial | info@foris.com | sandbox-5ef170@buyer.test | sent |  |
| 2 | 2 | initial | info@evoge.de | sandbox-5ef170@buyer.test | sent |  |
| 3 | 3 | initial | kontakt@dnotv.de | sandbox-5ef170@buyer.test | sent |  |
| 4 | 5 | initial | info@youco24.de | sandbox-5ef170@buyer.test | sent |  |
| 5 | 6 | initial | post@siba-wirtschaftskanzlei.de | sandbox-5ef170@buyer.test | sent |  |
| 6 | 7 | initial | office@legasset.com | sandbox-5ef170@buyer.test | sent |  |
| 8 | 1 | clarify | sandbox-5ef170@buyer.test | sandbox-5ef170@buyer.test | sent |  |
| 10 | 1 | followup | x@example.com |  | blocked | 供应商已转人工接管，AI 不得对外发送 |

### 首封开发信示例

```
Subject: Enquiry: ready-made Germany companies – FORIS AG

Dear FORIS AG team,

I came across your website (https://www.foris.com/) and noticed that you offer vorratsgesellschaften. We are Demo Cross-border Trading Co., a cross-border e-commerce company, and we regularly look for ready-made companies in Germany for our own legitimate operations.

Could you help us with the following?
1. Do you currently have ready-made (shelf) companies available? Could you share a list with incorporation dates?
2. What is the price for each available company, and what exactly is included?
3. Is the company already VAT registered (and which VAT scheme)?
4. Does the company come with an existing business bank account? Which bank?
If it is easier, a current list of available companies with prices would be a great start.

Best regards,
Procurement Team
```

## 4. 回复处理（供应商回复由演示脚本模拟，经真实 SMTP/IMAP 往返）

- 来信 #7：“Hi, thanks for reaching out. Yes, our companies are VAT registered. Let me know what else you need.” → AI 动作 **clarify_queued**，，意向分 20.0

AI 追问（只问未回答的问题）：

```
Dear FORIS AG,

Thank you for your reply and the information provided. To evaluate the options properly, could you also let us know:
1. Do you currently have ready-made (shelf) companies available? Could you share a list with incorporation dates?
2. Does the company come with an existing business bank account? Which bank?
3. What is the price for each available company, and what exactly is included?

Best regards,
Procurement Team
```

- 来信 #9：“We currently have 3 companies available, each with a business bank account. Price is GBP 2,400 per company. Happy to proceed.” → AI 动作 **handoff**，命中组合条件 has_inventory+provided_price；信号：确认有可售现成公司、提供了报价、回复中确认满足必须条件、表达合作意愿、询问下一步（合同/付款/会议），意向分 100.0

- 转人工：是；原因：命中组合条件 has_inventory+provided_price；信号：确认有可售现成公司、提供了报价、回复中确认满足必须条件、表达合作意愿、询问下一步（合同/付款/会议）；供应商状态：human_takeover
- 接管后 AI 尝试发送被拦截：是（供应商已转人工接管，AI 不得对外发送）

## 5. 本演示的真实性边界

- 真实：搜索引擎结果、供应商网站内容、网页证据文件、联系方式、筛选结果、SMTP 发送与 IMAP 读取。
- 受控：沙盒模式开启，没有任何邮件发送给真实供应商；供应商回复为脚本模拟。
- 未验证：真实供应商的真实回复、真实邮箱服务商（Gmail/Outlook/企业邮箱）的投递率与反垃圾表现。
