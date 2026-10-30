# 已保存的成功与失败案例

[项目首页](../README.zh-CN.md) · [原始脱敏JSON](../reports/public/experiments/recorded_demo.json)

以下是历史运行输出，不是刚刚现场调用，也不是经过独立核验的标准答案。引用编号/输出结构已检查；语义、数值与引用支持仍需人审。证据只提供短预览，完整原文通过SEC链接查看。

## 成功完成链路的示例

**原问：** 比较Google FY2024年报和Amazon FY2025年报披露的云业务收入，说明两者披露口径。

**公开截止日：** 2026-10-28

### n1 · supported

Alphabet FY2024年报（报告财年FY2024，期末2024-12-31）披露的Google Cloud收入为43,229百万美元，对应实际期间为截至2024年12月31日的年度（2024年1月1日至2024年12月31日）[E2][E3][E7]。同表列示2023年为33,088百万美元、2022年为26,280百万美元[E2][E3]。该金额为Google Cloud分部收入，币种为美元，单位为百万美元[E2][E3]。

### n2 · supported

Amazon FY2025年报（报告财年FY2025，期末2025-12-31）披露的AWS净销售额为128,725百万美元，对应实际期间为截至2025年12月31日的年度（2025年1月1日至2025年12月31日）[E1][E5][E6]。同表列示2024年为107,556百万美元、2023年为90,757百万美元[E1][E5]。该金额为AWS分部净销售额，币种为美元，单位为百万美元[E1][E5]。

### n3 · partial

Google口径：Alphabet将Google Cloud作为三个报告分部之一（Google Services、Google Cloud、Other Bets）[E9]。Google Cloud包括面向企业客户的基础设施与平台服务、应用及其他服务，收入主要来自Google Cloud Platform（按消费量计费及订阅，含AI基础设施、Vertex AI、Gemini for Google Cloud、网络安全、数据与分析）、Google Workspace（企业云通信与协作工具订阅）及其他企业服务[E4][E9][E13]。收入确认：消费型云服务在客户使用服务时按使用量确认，订阅型在合同期内按比例确认[E4]。列报为分部收入，与合并总收入350,018百万美元相区分[E2][E3]。Amazon口径：Amazon将AWS作为三个报告分部之一（North America、International、AWS）[E10][E15]。AWS分部由面向初创企业、企业、政府机构和学术机构的全球计算、存储、数据库及其他服务销售构成[E1][E10]。收入确认：AWS收入按单独售价分摊至各项服务，主要按客户使用量（如按需交付的计算或存储容量）在服务提供时确认；部分服务（含计算和数据库）以固定期限固定数量提供，按比例确认[E12]。列报为分部净销售额，与合并净销售额716,924百万美元相区分[E1][E5]。两者口径差异：Google Cloud为分部收入（revenues），Amazon AWS为分部净销售额（net sales）；Google Cloud包含Workspace等企业协作应用订阅，AWS描述为计算、存储、数据库及其他服务；两者均按使用量/订阅确认收入，但具体服务范围与列报科目名称不同[E4][E9][E10][E12]。

### 模型标注的缺项与限制

- n3：本次提供的证据未包含两家公司对云业务收入确认的完整会计政策全文（如Amazon对AWS各类服务的详细确认时点、Google对Workspace订阅确认的完整说明），仅包含上述摘录段落
- n3：本次提供的证据未包含两家公司分部间内部交易抵销的完整说明（Amazon仅说明报告分部间无内部收入交易[E10]；Google未在提供证据中说明分部间收入抵销细节）
- 两家公司报告财年不同：Google为FY2024（期末2024-12-31），Amazon为FY2025（期末2025-12-31），所披露云业务收入对应实际期间不同，不可直接视为同一期间比较[E1][E2]
- Google Cloud为分部收入（revenues），Amazon AWS为分部净销售额（net sales），列报科目名称不同[E1][E2]
- 金额均为美元百万美元，未进行汇率调整或跨公司口径调整
- 未进行任何财务计算或估算，仅引用原文披露数字

### 引用来源

- **[E1] AMZN_FY2025** · 报告FY2025 · 公开2026-02-06 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm)
- **[E2] GOOGL_FY2024** · 报告FY2024 · 公开2025-02-05 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm)
- **[E3] GOOGL_FY2024** · 报告FY2024 · 公开2025-02-05 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm)
- **[E4] GOOGL_FY2024** · 报告FY2024 · 公开2025-02-05 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm)
- **[E5] AMZN_FY2025** · 报告FY2025 · 公开2026-02-06 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm)
- **[E6] AMZN_FY2025** · 报告FY2025 · 公开2026-02-06 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm)
- **[E7] GOOGL_FY2024** · 报告FY2024 · 公开2025-02-05 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm)
- **[E9] GOOGL_FY2024** · 报告FY2024 · 公开2025-02-05 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm)
- **[E10] AMZN_FY2025** · 报告FY2025 · 公开2026-02-06 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm)
- **[E12] AMZN_FY2025** · 报告FY2025 · 公开2026-02-06 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm)
- **[E13] GOOGL_FY2024** · 报告FY2024 · 公开2025-02-05 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm)
- **[E15] AMZN_FY2025** · 报告FY2025 · 公开2026-02-06 · [SEC原文](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm)

此例故意比较不同报告财年，答案需说明期间和云业务口径不可直接视为一致。它证明模型请求、检索、上下文与生成链路能够完成，不证明云业务分析的所有结论正确。

## 明确失败的示例

同类问题的早一次运行返回 `error / planner_schema_invalid`。Planner缺少必填字段，泛化的“请修复JSON”反馈未解决；系统保留严格拒绝，没有静默放宽契约。随后增加字段路径与JSON schema反馈，再做成功的真实运行。失败记录与成功记录都保留，不删除失败来制造成功率。

其他可检查的负面结果包括：[need预算策略偏好短文本、模型选行漏关键会计行、任务重组候选提高但Top80下降、合成ANN强聚簇漏召回](experiments.md)。
