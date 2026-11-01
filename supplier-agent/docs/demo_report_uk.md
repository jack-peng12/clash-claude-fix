# 真实业务演示报告

- 生成时间（UTC）：2026-11-01 01:51:17
- 采购需求（员工输入）：找5家英国现成公司供应商，必须带VAT和企业银行账户，董事待确认，是否注册过亚马逊需确认，预算每家5000以内
- 解析结果：国家 ['United Kingdom']，条件 `{"inventory": "required", "vat_registered": "required", "bank_account": "required", "director_continue": "to_confirm", "no_ecommerce_history": "to_confirm", "price": "required"}`，解析方式 rules
- 搜索+采集+筛选耗时：61 秒；任务统计：`{"fetch_failed": 2, "cat_match": 5, "outreach_queued": 6, "suppliers_new": 8, "cat_insufficient": 4, "outreach_manual": 2, "outreach_already": 1}`

## 1. 真实搜索关键词与结果

| 关键词 | 语言 | 来源 | 状态 | 结果数 | 相关 | 新供应商 |
|---|---|---|---|---|---|---|
| buy ready made company United Kingdom | en | template | done | 10 | 10 | 6 |
| United Kingdom shelf company for sale | en | template | done | 10 | 10 | 2 |
| aged United Kingdom company for sale with bank account | en | template | done | 7 | 5 | 0 |
| United Kingdom shelf company VAT registered | en | template | done | 7 | 7 | 0 |

## 2. 真实找到并建档的供应商

| # | 名称 | 域名 | 国家识别 | 符合度 | 得分 | 风险 | 邮箱 | 其他联系方式 | 网页证据数 | 事实条目 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | MYCO Works | mycoworks.co.uk | United Kingdom | match | 100.0 | low | contact@mycosupport.co.uk | facebook, form, linkedin, phone | 5 | 37 |
| 2 | System Day Ltd | systemday.com | United Kingdom | insufficient | 80.0 | low | home@systemday.com | linkedin, phone | 4 | 25 |
| 3 | Hello Accountants | helloaccountants.co.uk | United Kingdom | match | 100.0 | low | info@helloaccountants.co.uk, info@lead-force.co.uk | facebook, linkedin, phone, whatsapp | 10 | 138 |
| 4 | Company Formation and UK Company Registrations | companyformationstoday.co.uk | United Kingdom | match | 100.0 | low | contact@coformuk.com | phone | 5 | 35 |
| 5 | GoFormed | goformed.co.uk | United Kingdom | match | 100.0 | low | info@goformed.co.uk | phone, whatsapp | 5 | 42 |
| 6 | ReadyMadeCompany.co | readymadecompany.co | United Kingdom | insufficient | 80.0 | low |  |  | 5 | 37 |
| 7 | BIRR Legal Services | birr.co.uk | United Kingdom | insufficient | 60.0 | low |  | facebook, phone | 4 | 12 |
| 8 | ShelfCompanies24 Sp. z o.o. | shelfcompanies24.com | United Kingdom | insufficient | 80.0 | low | info@ShelfCompanies24.com, Anna@ShelfCompanies24.com, Julia@ShelfCompanies24.com | linkedin, phone, whatsapp | 5 | 46 |

### 判定原因

- **MYCO Works**（mycoworks.co.uk）：所有必须条件均有正向证据（未经人工核验）
- **System Day Ltd**（systemday.com）：缺少证据: 已注册VAT；网站有反向表述待供应商确认: 已注册VAT
- **Hello Accountants**（helloaccountants.co.uk）：所有必须条件均有正向证据（未经人工核验）
- **Company Formation and UK Company Registrations**（companyformationstoday.co.uk）：所有必须条件均有正向证据（未经人工核验）
- **GoFormed**（goformed.co.uk）：所有必须条件均有正向证据（未经人工核验）
- **ReadyMadeCompany.co**（readymadecompany.co）：缺少证据: 收购价格
- **BIRR Legal Services**（birr.co.uk）：缺少证据: 已注册VAT, 附带企业银行账户, 董事可继续任职并配合审核
- **ShelfCompanies24 Sp. z o.o.**（shelfcompanies24.com）：缺少证据: 已注册VAT；网站有反向表述待供应商确认: 已注册VAT

### 证据样例（事实 → 网页证据，可在后台点开原始HTML核对）

- `inventory`=yes（web_claim）← https://mycoworks.co.uk/ready-made-companies sha256 `faa81e4176a6d003` 采集于 2026-11-01 01:50 UTC：“within 3 months from the date on which it starts trading again or receives an income. Can I get a bank account with the shelf company? Yes, ”
- `bank_account`=yes（web_claim）← https://mycoworks.co.uk/ready-made-companies sha256 `faa81e4176a6d003` 采集于 2026-11-01 01:50 UTC：“is no longer dormant within 3 months from the date on which it starts trading again or receives an income. Can I get a bank account with the”
- `director_continue`=yes（web_claim）← https://mycoworks.co.uk/ready-made-companies sha256 `faa81e4176a6d003` 采集于 2026-11-01 01:50 UTC：“dress Services Make the perfect first impression with a prestigious virtual business address. Registered Office Address Director Service Add”
- `no_ecommerce_history`=yes（web_claim）← https://mycoworks.co.uk/ready-made-companies sha256 `faa81e4176a6d003` 采集于 2026-11-01 01:50 UTC：“s via Companies House. Is it safe to buy a Ready Made Company? Yes! When you buy a ready made company you are getting a dormant UK company w”
- `trading_history`=no（web_claim）← https://mycoworks.co.uk/ready-made-companies sha256 `faa81e4176a6d003` 采集于 2026-11-01 01:50 UTC：“s via Companies House. Is it safe to buy a Ready Made Company? Yes! When you buy a ready made company you are getting a dormant UK company w”
- `no_debt_litigation`=yes（web_claim）← https://mycoworks.co.uk/ready-made-companies sha256 `faa81e4176a6d003` 采集于 2026-11-01 01:50 UTC：“dormant UK company with no trading history, so you can rest assured that the company is financially clean and there are no outstanding burde”
- `tax_filing_ok`=yes（web_claim）← https://mycoworks.co.uk/ready-made-companies sha256 `faa81e4176a6d003` 采集于 2026-11-01 01:50 UTC：“- 1 Year Registered Office Address and Service Addresses for your company (Renews at £59.99 +VAT on an annual basis) - Confirmation Statemen”
- `real_address_lease`=yes（web_claim）← https://mycoworks.co.uk/ready-made-companies sha256 `faa81e4176a6d003` 采集于 2026-11-01 01:50 UTC：“Client Log In Enquire × Address Services Address Services Make the perfect first impression with a prestigious virtual business address. Reg”

### 采集失败记录（如实记录）

- https://www.companyformationstoday.co.uk/readymade+companies.html：HTTP 404

## 3. 自动建联（沙盒：真实 SMTP 发出，收件人被替换为测试邮箱）

| 消息 | 供应商 | 类型 | 原收件人 | 实际收件 | 状态 | 原因 |
|---|---|---|---|---|---|---|
| 1 | 1 | initial | contact@mycosupport.co.uk | sandbox-8aff1b@buyer.test | sent |  |
| 2 | 2 | initial | home@systemday.com | sandbox-8aff1b@buyer.test | sent |  |
| 3 | 3 | initial | info@helloaccountants.co.uk | sandbox-8aff1b@buyer.test | sent |  |
| 4 | 4 | initial | contact@coformuk.com | sandbox-8aff1b@buyer.test | sent |  |
| 5 | 5 | initial | info@goformed.co.uk | sandbox-8aff1b@buyer.test | sent |  |
| 6 | 8 | initial | info@shelfcompanies24.com | sandbox-8aff1b@buyer.test | sent |  |
| 8 | 1 | clarify | sandbox-8aff1b@buyer.test | sandbox-8aff1b@buyer.test | sent |  |
| 10 | 1 | followup | x@example.com |  | blocked | 供应商已转人工接管，AI 不得对外发送 |

### 首封开发信示例

```
Subject: Enquiry: ready-made the United Kingdom companies – MYCO Works

Dear MYCO Works team,

I came across your website (https://mycoworks.co.uk/) and noticed that you offer ready-made companies. We are Demo Cross-border Trading Co., a cross-border e-commerce company, and we regularly look for ready-made companies in the United Kingdom for our own legitimate operations.

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
Dear MYCO Works,

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
