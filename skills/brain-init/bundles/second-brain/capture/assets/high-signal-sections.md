# High-Signal Annual Report Sections

Purpose: locate high-value sections in long annual reports **before reading**. Use these patterns to
build a compact section map (`line_number: heading`). Grep is for navigation; extraction happens only
after bounded section reads.

## Usage Rules

1. Match headings first, not every occurrence of a keyword.
2. Keep only matching headings and line numbers in active context.
3. Read Tier 1 sections first.
4. Read Tier 2 only when material, referenced by Tier 1, or needed to answer an extraction-profile question.
5. Use Tier 3 only for specific follow-up.
6. If the converted markdown loses heading structure, fall back to the regex aliases below and manually bound the relevant ranges.

---

# US / SEC 10-K

## Tier 1 — Always Inspect

- Item 1. Business
- Business Strategy / Strategy
- Industry / Markets Served
- Customers / Major Customers / Customer Concentration
- Products / Product Lines
- Competition / Competitive Conditions
- Research and Development / R&D
- Item 7. Management's Discussion and Analysis
- Executive Overview
- Results of Operations
- Segment Results / Segment Results of Operations
- Item 8. Financial Statements and Supplementary Data
- Business Segments / Segment Information / Reportable Segments

### Grep locator

```bash
grep -n -iE \
'^(#{1,6}[[:space:]]*)?(item[[:space:]]+1\.?[[:space:]]+business|business strategy|strategy|industry|markets? served|customers?|major customers?|customer concentration|products?|product lines?|competition|competitive conditions|research and development|r&d|item[[:space:]]+7\.?|management.?s discussion and analysis|executive overview|results of operations|segment results( of operations)?|item[[:space:]]+8\.?|financial statements and supplementary data|business segments|segment information|reportable segments)[[:space:]]*$' report.md
```

## Tier 2 — Inspect When Material

- Item 1A. Risk Factors
- Supplies and Raw Materials / Raw Materials
- Backlog
- Liquidity and Capital Resources
- Cash Flows
- Capital Expenditures / CapEx
- Restructuring
- Impairment
- Goodwill and Intangible Assets
- Debt / Long-Term Debt / Credit Facilities / Borrowings
- Acquisitions / Business Combinations
- Divestitures
- Joint Ventures / Strategic Alliances
- Commitments and Contingencies
- Legal Proceedings
- Related-Party Transactions
- Pensions / Postretirement Benefits
- Income Taxes
- Subsequent Events

### Grep locator

```bash
grep -n -iE \
'^(#{1,6}[[:space:]]*)?(item[[:space:]]+1a\.?[[:space:]]+risk factors|risk factors|supplies and raw materials|raw materials|backlog|liquidity and capital resources|cash flows?|capital expenditures?|capex|restructuring|impairment|goodwill( and intangible assets)?|debt|long-term debt|credit facilities|borrowings|acquisitions?|business combinations|divestitures?|joint ventures?|strategic alliances|commitments and contingencies|legal proceedings|related-party transactions|pensions?|postretirement benefits|income taxes|subsequent events)[[:space:]]*$' report.md
```

## Tier 3 — Follow-Up Only

- Human Capital / Employees
- Cybersecurity
- Properties / Facilities
- Governance
- Executive Compensation
- Stock-Based Compensation
- Shareholders / Ownership
- ESG / Sustainability

---

# China Listed-Company Annual Reports

## Tier 1 — Always Inspect

- 管理层讨论与分析
- 报告期内公司从事的主要业务
- 主要业务 / 主营业务
- 经营模式 / 商业模式
- 行业情况 / 行业发展 / 行业地位 / 竞争格局
- 核心竞争力 / 核心竞争力分析
- 主营业务分析
- 收入与成本
- 分行业 / 分产品 / 分地区
- 主要客户 / 前五大客户 / 客户集中度
- 主要供应商 / 前五大供应商 / 供应商集中度
- 研发投入 / 研发支出 / 研发项目
- 公司未来发展的展望
- 发展战略 / 经营计划 / 发展规划
- 关键审计事项
- 分部信息
- 营业收入和营业成本

### Grep locator

```bash
grep -n -E \
'^(#{1,6}[[:space:]]*)?(管理层讨论与分析|报告期内公司从事的主要业务|主要业务|主营业务|经营模式|商业模式|行业情况|行业发展|行业地位|竞争格局|核心竞争力(分析)?|主营业务分析|收入与成本|分行业|分产品|分地区|主要客户|前五大客户|客户集中度|主要供应商|前五大供应商|供应商集中度|研发投入|研发支出|研发项目|公司未来发展的展望|发展战略|经营计划|发展规划|关键审计事项|分部信息|营业收入和营业成本)[[:space:]]*$' report.md
```

## Tier 2 — Inspect When Material

- 主要会计数据和财务指标
- 非经常性损益
- 风险因素
- 可能面对的风险 / 风险及应对
- 现金流 / 现金流量
- 重大投资 / 对外投资
- 在建工程
- 固定资产 / 新增产能 / 产能利用率 / 生产基地
- 商誉 / 商誉减值
- 资产减值
- 应收账款
- 存货
- 短期借款 / 长期借款 / 借款
- 关联方 / 关联交易
- 政府补助
- 承诺及或有事项
- 资产负债表日后事项
- 并购 / 收购 / 重组
- 募集资金 / 募投项目

### Grep locator

```bash
grep -n -E \
'^(#{1,6}[[:space:]]*)?(主要会计数据和财务指标|非经常性损益|风险因素|可能面对的风险|风险及应对|现金流|现金流量|重大投资|对外投资|在建工程|固定资产|新增产能|产能利用率|生产基地|商誉|商誉减值|资产减值|应收账款|存货|短期借款|长期借款|借款|关联方|关联交易|政府补助|承诺及或有事项|资产负债表日后事项|并购|收购|重组|募集资金|募投项目)[[:space:]]*$' report.md
```

## Tier 3 — Follow-Up Only

- 公司治理
- 董事 / 高级管理人员
- 股东情况
- 股份变动
- 社会责任 / ESG
- 环境信息
- 员工情况
- 薪酬
- 税项

---

# Targeted Follow-Up Keywords

Use only after a Tier 1 / Tier 2 section produces a material lead that needs confirmation or broader
context. These are **not** primary-navigation patterns.

## Universal financial / operating

```regex
(?i)(revenue|sales|profit|margin|gross margin|EBITDA|cash flow|free cash flow|debt|capex|R&D|restructuring|impairment|customer|supplier|capacity|backlog|price|pricing|volume|mix|foreign exchange|FX|营业收入|营业成本|净利润|毛利率|现金流|研发|客户|供应商|产能|价格|销量|商誉|减值)
```

## Technology / growth

```regex
(?i)(new product|technology|innovation|launch|platform|electric vehicle|EV|thermal management|data center|energy storage|AI|新产品|新技术|技术创新|量产|定点|热管理|液冷|数据中心|储能|新能源)
```

## Capital allocation / corporate actions

```regex
(?i)(acquisition|divestiture|joint venture|investment|buyback|dividend|refinancing|acquired|sold|并购|收购|出售|合资|投资|回购|分红|融资|再融资)
```

---

# Expected Section Map Output

Keep the locator output compact, for example:

```text
T1  395  第三节 管理层讨论与分析
T1  396  一、报告期内公司从事的主要业务
T1  812  三、核心竞争力分析
T1 1047  2、收入与成本
T1 1218  3、研发投入
T1 1588  十一、公司未来发展的展望
T1 4205  三、关键审计事项
T2 1764  可能面对的风险
T2 5310  商誉减值
```

Then read only the bounded ranges needed for extraction.
