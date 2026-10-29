"""Reproduce fixed, source-grounded GPT annotations. Not an LLM API generator."""

import re

from finrag.config import ROOT
from finrag.files import atomic_json
from finrag.parse import load_blocks

B = load_blocks(ROOT)
S = []


def sel(doc, n, quote=None):
    block = B[doc][n]
    assert block.ordinal == n
    if quote is not None:
        assert quote in block.text, (doc, n, quote)
    return {"document_id": doc, "ordinal": n, **({"quote": quote} if quote is not None else {})}


def line(doc, n, label):
    return next(x for x in B[doc][n].text.splitlines() if x.startswith(label))


def first_fact(doc, n, label):
    value = line(doc, n, label)
    offset = value.index("|") + 1
    m = re.search(r"\d[\d,]*(?:\.\d+)?", value[offset:])
    return sel(doc, n, value[: offset + m.end()])


def header(doc, n):
    return sel(doc, n, next(x for x in B[doc][n].text.splitlines() if re.search(r"20\d{2}", x)))


def q(
    id,
    zh,
    en,
    answer,
    groups,
    family,
    category="text",
    derivation=None,
    outcome="answer",
    docs=None,
    asof="2026-10-11",
):
    documents = docs or sorted({x["document_id"] for g in groups for x in g})
    S.append(
        {
            "id": id,
            "question": zh,
            "question_en": en,
            "language": "zh",
            "split": "dev" if id.startswith("D") else "test",
            "category": category,
            "family": family,
            "reference": answer,
            "sources": groups,
            "documents": documents,
            "outcome": outcome,
            "as_of": asof,
            "derivation": derivation or {},
        }
    )


INCOMES = [
    ("NVDA_FY2026", 706, 215938),
    ("NVDA_FY2025", 723, 130497),
    ("NVDA_FY2024", 699, 60922),
    ("MU_FY2026", 759, 133188),
    ("MU_FY2025", 740, 37378),
    ("MU_FY2024", 699, 25111),
    ("AMD_FY2025", 602, 34639),
    ("AMD_FY2024", 599, 25785),
    ("AMD_FY2023", 607, 22680),
]
for i, (doc, n, value) in enumerate(INCOMES, 1):
    company, fy = doc.split("_")
    year = int(fy[2:])
    label = "Net revenue" if company == "AMD" else "Revenue"
    q(
        f"D{i:02}",
        f"依据 {company} FY{year} 的本年年报，公司当年的合并收入是多少？请注明币种和单位。",
        f"According to the {company} FY{year} annual report, what was consolidated annual revenue, including currency and units?",
        f"{company} FY{year} 合并收入为 {value:,} 百万美元，即 {value / 1000:.3f} 十亿美元。",
        [[first_fact(doc, n, label)], [header(doc, n)]],
        "consolidated_revenue",
        "table",
    )

for i, docs in enumerate(
    [
        ["NVDA_FY2024", "MU_FY2024", "AMD_FY2024"],
        ["NVDA_FY2025", "MU_FY2025", "AMD_FY2025"],
        ["NVDA_FY2026", "MU_FY2026", "AMD_FY2025"],
    ],
    10,
):
    rows = [next(r for r in INCOMES if r[0] == d) for d in docs]
    groups = []
    for doc, n, v in rows:
        groups += [
            [first_fact(doc, n, "Net revenue" if doc.startswith("AMD") else "Revenue")],
            [header(doc, n)],
        ]
    scope = "、".join(d.replace("_", " ") for d in docs)
    answer = (
        "；".join(f"{d.replace('_', ' ')}：{v:,} 百万美元" for d, n, v in rows)
        + "。收入规模按各自财年比较，期间不同，不等于同一日历年市场份额。"
    )
    q(
        f"D{i}",
        f"分别依据 {scope} 的年报，比较三家合并收入规模并说明期间可比性限制。",
        f"Compare consolidated annual revenue in the {scope} annual reports and explain the fiscal-period comparability limitation.",
        answer,
        groups,
        "consolidated_revenue",
        "cross_company",
    )

q(
    "D13",
    "NVIDIA FY2026 采用什么制造模式，哪些环节由供应商承担？",
    "What manufacturing model does NVIDIA FY2026 use and which production stages are performed by suppliers?",
    "采用 fabless 和委托制造模式，供应商参与晶圆制造、组装、测试与封装；NVIDIA 因而可将资源集中在设计、质量保证、营销和客户支持。",
    [[sel("NVDA_FY2026", 122)]],
    "manufacturing_model",
)
q(
    "D14",
    "Micron FY2025 的 HBM 是什么架构，为什么适合 AI 和高性能计算？",
    "In Micron MU FY2025, what is HBM and why is its architecture suitable for AI and high-performance computing?",
    "HBM 是采用 TSV 连接的 3D 堆叠 DRAM 架构，提供更高带宽且功耗较低，适合高吞吐和能效要求高的 AI/HPC。",
    [[sel("MU_FY2025", 54)]],
    "hbm_architecture",
)
q(
    "D15",
    "AMD FY2023 的 ATMP 合资伙伴是谁，还有哪些供应商提供组装测试封装？",
    "Who are the ATMP joint venture partner and other assembly test mark and packaging suppliers in AMD FY2023?",
    "AMD 与通富微电有两家 ATMP 合资企业；SPIL 和 KYEC 也提供 ATMP 服务，相关伙伴位于亚太地区。",
    [[sel("AMD_FY2023", 166)]],
    "atmp_partners",
)
q(
    "D16",
    "MU FY2024 的制造运营依赖哪些公共资源，中断会造成什么风险？",
    "Which utilities do MU FY2024 manufacturing operations depend on and what is the risk of outages?",
    "依赖可靠、不中断的电力和水；短缺、产能限制、长时间中断或成本异常增加，均可能对经营和财务状况产生重大不利影响。",
    [[sel("MU_FY2024", 127)]],
    "utilities",
)
q(
    "D17",
    "AMD FY2025 中，GF 负责哪些制程节点的 HPC 晶圆，TSMC 负责哪些产品？",
    "In AMD FY2025, which HPC wafer process nodes use GLOBALFOUNDRIES and which products use TSMC?",
    "GF 为 HPC 产品供应 12nm 和 14nm 晶圆；TSMC 用于 HPC、FPGA 和 adaptive SoC 的晶圆生产，也与 UMC、Samsung 一起生产可编程逻辑器件 IC。",
    [[sel("AMD_FY2025", 151)]],
    "foundry_nodes",
)

for id, company, old, new, oldn, newn, a, b in [
    ("D18", "NVDA", 2024, 2025, 722, 746, 28090, 64089),
    ("D19", "MU", 2024, 2025, 727, 768, 8507, 17525),
    ("D20", "AMD", 2023, 2024, 627, 619, 1667, 3041),
]:
    docs = [f"{company}_FY{old}", f"{company}_FY{new}"]
    groups = []
    for doc, n in zip(docs, [oldn, newn]):
        groups += [
            [first_fact(doc, n, "Net cash provided by operating activities")],
            [header(doc, n)],
        ]
    pct = (b / a - 1) * 100
    q(
        id,
        f"分别查阅 {company} FY{old} 和 FY{new} 的年报，经营现金流从多少变为多少，增幅是多少？",
        f"Using both {company} FY{old} and {company} FY{new} annual reports, how did net cash provided by operating activities change and what was the percentage increase?",
        f"经营现金流由 {a:,} 增至 {b:,} 百万美元，增加 {b - a:,} 百万美元，增幅约 {pct:.2f}%。",
        groups,
        f"cash_flow_growth_{company}",
        "cross_year",
        {
            "formula": "(new/old-1)*100",
            "old": a,
            "new": b,
            "result_percent": pct,
            "tolerance": 0.02,
        },
    )
q(
    "D21",
    "对比 NVIDIA FY2024 和 FY2026 的制造供应链地理分布披露，发生了什么变化？",
    "Compare NVIDIA NVDA FY2024 and NVDA FY2026 manufacturing supply-chain geographic concentration disclosures. What expansion is described?",
    "FY2024 披露供应链集中在亚太；FY2026 仍主要集中于亚洲，但描述正在向美国和拉丁美洲扩展。这是披露方向变化，不证明已完成地理分散。",
    [[sel("NVDA_FY2024", 117)], [sel("NVDA_FY2026", 123)]],
    "manufacturing_geography",
    "cross_year",
)
q(
    "D22",
    "NVIDIA FY2024 如何确定产品保修费用，通常保修多久？",
    "In NVIDIA NVDA FY2024, how are product warranty costs recognized and what is the typical warranty period?",
    "有限保修通常为 1–3 年；估计保修成本在确认收入时计入成本，已知保修及赔偿事项在损失很可能发生且可合理估计时计提。",
    [[sel("NVDA_FY2024", 759)]],
    "warranty_policy",
    "footnote",
)
q(
    "D23",
    "AMD FY2023 收购形成的 IPR&D 何时开始摊销，金额和年限是什么？",
    "When did the acquired IPR&D intangible assets in AMD FY2023 begin amortization, and what were their value and useful life?",
    "相关 IPR&D 公允价值为 970 百万美元，初始作为未达技术可行性的无限寿命资产不摊销；2023 年第四季度达到技术可行性，转为开发技术，按 15 年估计寿命摊销。",
    [[sel("AMD_FY2023", 777)]],
    "iprd_amortization",
    "footnote",
)
q(
    "D24",
    "MU FY2026 的客户集中度附注如何描述 FY2026、FY2025 和 FY2024 的 10% 客户？",
    "According to MU FY2026 customer concentration disclosure, what customers reached 10 percent of total revenue in FY2026, FY2025 and FY2024?",
    "FY2026 没有客户达到总收入 10%；FY2025 一家客户占 17%，主要计入 CMBU；FY2024 一家客户占 10%，主要计入 MCBU、AEBU 和 CMBU。客户身份未披露。",
    [[sel("MU_FY2026", 1050)]],
    "mu_customer_concentration",
    "footnote",
)
q(
    "D25",
    "AMD FY2025 对 ZT Systems 做了什么收购和出售，保留了什么能力？",
    "What ZT Systems acquisition and divestiture did AMD FY2025 complete, and which capabilities did it retain?",
    "2025 年 3 月收购 ZT Systems，保留设计业务相关知识产权和员工；10 月将数据中心基础设施制造业务出售给 Sanmina，保留设计能力以支持 AI 基础设施部署。",
    [[sel("AMD_FY2025", 50)]],
    "zt_transaction",
    "footnote",
)

INV = [
    ("NVDA_FY2026", 912, 21403),
    ("NVDA_FY2025", 946, 10080),
    ("NVDA_FY2024", 935, 5282),
    ("MU_FY2026", 854, 10372),
    ("MU_FY2025", 844, 8355),
    ("MU_FY2024", 800, 8875),
    ("AMD_FY2025", 701, 7920),
    ("AMD_FY2024", 701, 5734),
    ("AMD_FY2023", 709, 4351),
]
for i, (doc, n, total) in enumerate(INV, 1):
    company, fy = doc.split("_")
    year = int(fy[2:])
    rows = B[doc][n].text.splitlines()
    total_line = next((l for l in rows if l.startswith("Total inventories")), rows[-1])
    q(
        f"T{i:02}",
        f"根据 {company} FY{year} 的本年年报，财年末存货总额是多少？请勿使用前一年比较列。",
        f"According to the {company} FY{year} annual report, what were total inventories at that fiscal year-end, rather than the prior-year comparative column?",
        f"{company} FY{year} 财年末存货为 {total:,} 百万美元。",
        [[sel(doc, n, total_line)], [header(doc, n)]],
        "inventory_balances",
        "table",
    )
for i, docs in enumerate(
    [
        ["NVDA_FY2024", "MU_FY2024", "AMD_FY2024"],
        ["NVDA_FY2025", "MU_FY2025", "AMD_FY2025"],
        ["NVDA_FY2026", "MU_FY2026", "AMD_FY2025"],
    ],
    10,
):
    groups = []
    parts = []
    for doc in docs:
        d, n, total = next(r for r in INV if r[0] == doc)
        rows = B[doc][n].text.splitlines()
        total_line = next((l for l in rows if l.startswith("Total inventories")), rows[-1])
        groups += [[sel(doc, n, total_line)], [header(doc, n)]]
        parts.append(f"{doc.replace('_', ' ')}：{total:,} 百万美元")
    scope = "、".join(d.replace("_", " ") for d in docs)
    q(
        f"T{i}",
        f"比较 {scope} 各年报的期末存货总额，哪个最大？说明这是各自财年末。",
        f"Compare fiscal year-end total inventories in the {scope} annual reports. Which is largest? Preserve each fiscal year-end.",
        "；".join(parts)
        + f"。{max((r for r in INV if r[0] in docs), key=lambda r: r[2])[0].split('_')[0]} 最大；各自财年末时点不同。",
        groups,
        "inventory_balances",
        "cross_company",
    )
q(
    "T13",
    "NVIDIA FY2025 为什么提前下不可取消订单可能放大需求预测错误的损失？",
    "Why can advance non-cancellable orders amplify demand forecasting errors in NVIDIA NVDA FY2025?",
    "若高估需求或客户取消/推迟订单，可能无法消化库存或减少承诺，导致降价、存货减记、取消罚金和减值；提前下不可取消且不可退货的订单、采购承诺与预付款增加会放大这些影响，损害毛利。",
    [[sel("NVDA_FY2025", 257)]],
    "noncancellable_demand_risk",
)
q(
    "T14",
    "MU FY2026 为什么行业扩产可能损害售价和经营结果？",
    "Why can industry fabrication capacity expansion damage average selling prices and operating results in MU FY2026?",
    "公司与竞争者扩建/提高晶圆厂产出会增加供给；若需求不能增加或保持稳定，平均售价可能显著下降；快速技术变化和产品生命周期缩短也可能加速价格下降。",
    [[sel("MU_FY2026", 104)]],
    "memory_oversupply",
)
q(
    "T15",
    "AMD FY2024 披露 Intel 的哪些竞争行为可能压低 AMD 的销量、售价和利润率？",
    "Which Intel competitive practices can reduce AMD unit sales, selling prices and margins according to AMD FY2024?",
    "包括激进定价、面向客户和渠道伙伴的激励、返利及分配策略、捆绑营销与排他性支付；Intel 的平台影响力和标准制定能力也可能延迟 AMD 获取技术标准。",
    [[sel("AMD_FY2024", 261)]],
    "intel_competition",
)
q(
    "T16",
    "NVIDIA FY2026 年末是否仍可以正常竞争中国数据中心计算市场，年报如何描述？",
    "At fiscal year-end in NVIDIA NVDA FY2026, could it compete normally in the China data center compute market according to its disclosure?",
    "不能据此说可正常竞争。年报称在当时出口管制和地缘政治环境下，无法交付同时获得中美政府批准的竞争性产品，财年末实际上被排除在该市场之外；这不是“中国所有产品收入均为零”的断言。",
    [[sel("NVDA_FY2026", 152), sel("NVDA_FY2026", 390)]],
    "china_market_access",
)
q(
    "T17",
    "MU FY2024 存货采用什么计价方法，未来售价下降 5% 的敏感性是多少？",
    "What inventory costing method and 5 percent future selling-price sensitivity does MU FY2024 disclose?",
    "以 FIFO 确定成本，按成本与可变现净值孰低计量；未来平均售价下降 5%，会使 2024-08-29 的产成品和在制品估计可变现净值变化约 700 百万美元。这不是已经发生的损失。",
    [[sel("MU_FY2024", 670)]],
    "inventory_nrv_sensitivity",
)
q(
    "T18",
    "NVIDIA FY2026 相较 FY2025 毛利率如何变化，管理层给出哪两个主要原因？",
    "According to NVIDIA NVDA FY2026, how did gross margin change from FY2025 and what two main explanations were provided?",
    "毛利率由 75.0% 降至 71.1%，下降 3.9 个百分点；原因包括从 Hopper HGX 转向 Blackwell 完整数据中心方案的业务模式变化，以及 H20 超额库存与采购义务相关 45 亿美元费用。",
    [[sel("NVDA_FY2026", 558)]],
    "nvda_gross_margin_h20",
    "cross_year",
    {"formula": "71.1-75.0", "result_percentage_points": -3.9, "tolerance": 0.01},
)
q(
    "T19",
    "分别查 MU FY2024 和 FY2025 年报，毛利率如何恢复，FY2024 如何受此前存货减记影响？",
    "Using both MU FY2024 and MU FY2025 annual reports, explain gross-margin recovery and how FY2024 benefited from previously written-down inventories.",
    "FY2024 毛利率从 FY2023 的 -9% 恢复至 22%，FY2025 进一步到 40%；售价、制造成本及产品组合影响恢复，FY2025 的 DRAM 改善还涉及 HBM 等高毛利组合。FY2024 销售以前已减记存货带来较低成本，FY2025 报告量化该收益为 987 百万美元。",
    [[sel("MU_FY2024", 582)], [sel("MU_FY2025", 608)]],
    "mu_gross_margin_recovery",
    "cross_year",
)
q(
    "T20",
    "依据 AMD FY2025 年报的比较列，FY2023 至 FY2025 的研发费用分别是多少？",
    "Using the comparative columns of the AMD FY2025 annual report, what were research and development expenses in FY2023, FY2024 and FY2025?",
    "FY2023、FY2024、FY2025 的研发费用分别为 5,872、6,456、8,091 百万美元，不能将列的倒序读反。",
    [
        [sel("AMD_FY2025", 602, line("AMD_FY2025", 602, "Research and development"))],
        [header("AMD_FY2025", 602)],
    ],
    "rd_comparative_columns",
    "cross_year",
)
q(
    "T21",
    "分别依据 NVIDIA FY2024 和 FY2025 年报，直接客户达到 10% 收入门槛的情况如何变化？",
    "Using NVIDIA NVDA FY2024 and NVDA FY2025 annual reports, how did direct customers reaching 10 percent of revenue change?",
    "FY2024 一家客户占 13%；FY2025 表中直接客户 A、B、C 分别占 12%、11%、11%。这是直接客户口径，不能将间接客户估计额重复相加。",
    [[sel("NVDA_FY2024", 1079)], [sel("NVDA_FY2025", 1094)]],
    "nvda_direct_customer_concentration",
    "cross_year",
)
q(
    "T22",
    "MU FY2026 的剩余履约义务和客户存款分别有多少，能否直接当成本年收入？",
    "In MU FY2026, how large are remaining performance obligations and customer deposits, and can these be treated as current-year revenue?",
    "剩余履约义务约 1340 亿美元，其中约 130 亿美元确认为合同负债，主要为客户存款。约四分之一预计未来 12 个月确认为收入，其余预计在未来五年内确认；不能全部当作 FY2026 收入。几乎全部存款安排于 2029–2031 年偿还。",
    [[sel("MU_FY2026", 989)]],
    "remaining_performance_obligations",
    "footnote",
)
q(
    "T23",
    "AMD FY2024 如何计提过时存货及不可取消采购订单，需求进一步减弱时会怎样？",
    "How does AMD FY2024 reserve obsolete inventories and non-cancellable inventory purchase orders, and what happens if demand weakens further?",
    "按标准成本调整至实际成本或估计可变现净值孰低；对被认定过时的存货和不可取消采购订单全额计提。定期将库存与不可取消订单同预计使用量比较，需求或市场恶化可能要求额外调整。",
    [[sel("AMD_FY2024", 649)]],
    "amd_inventory_reserves",
    "footnote",
)
q(
    "T24",
    "NVIDIA FY2025 按开票地统计的新加坡收入是否等于货物运往新加坡的收入？",
    "Does Singapore revenue by customer billing location equal revenue from products shipped to Singapore in NVIDIA NVDA FY2025?",
    "不等于。新加坡按客户开票地占 FY2025 总收入 18%，客户用新加坡集中开票，而产品几乎都运往其他地点；运往新加坡的货物低于总收入 2%。",
    [[sel("NVDA_FY2025", 1086)]],
    "billing_vs_shipping",
    "footnote",
)
A = "AMD_FY2025_A_0000002488-26-000021"
q(
    "T25",
    "AMD FY2025 的 10-K/A 纠正了 Client 业务什么错误，正确的出货量和 ASP 增幅是多少？",
    "What Client revenue disclosure error did the AMD FY2025 10-K/A correct, and what are the correct unit shipment and ASP growth rates?",
    "原稿误将 Client 处理器出货量和 ASP 的同比变化数字对调；正确为出货量增加 15%、ASP 增加 31%，Client 收入约 106 亿美元，同比增长 51%。应使用修订披露且保留原稿关联。",
    [[sel(A, 36), sel(A, 85)]],
    "amd_amendment",
    "amendment",
    docs=["AMD_FY2025", A],
)

boundaries = [
    (
        "D26",
        "NVDA FY2026 年报能否给出明天的精确收盘价？",
        "Can the NVDA FY2026 annual report provide the exact closing share price tomorrow?",
        "年报不能证明未来精确股价。",
        "future_price",
        "insufficient_evidence",
    ),
    (
        "D27",
        "MU FY2026 的某名未披露客户联系人私人电话号码是什么？",
        "What is the private phone number of an undisclosed MU FY2026 customer contact?",
        "语料未提供该私人信息。",
        "private_contact",
        "insufficient_evidence",
    ),
    (
        "D28",
        "请比较这家公司最近几年的表现。",
        "Compare this company over recent years.",
        "需要明确公司、期间和比较指标。",
        "ambiguous_company",
        "clarify",
    ),
    (
        "D29",
        "请根据 NVIDIA FY2035 年报提供收入。",
        "What is NVIDIA NVDA FY2035 annual revenue from its annual report?",
        "语料不覆盖 FY2035，不能编造。",
        "future_filing",
        "insufficient_evidence",
    ),
    (
        "D30",
        "TSM FY2025 与 AMD FY2025 的年报谁的收入更高？",
        "Compare TSM FY2025 and AMD FY2025 annual revenue.",
        "当前语料不含 TSM 年报，无法完成双方有证据的比较。",
        "unsupported_company",
        "insufficient_evidence",
    ),
    (
        "T26",
        "AMD FY2025 年报能证明未来三年绝不会亏损吗？",
        "Does the AMD FY2025 annual report prove it cannot make a loss over the next three years?",
        "年报与前瞻陈述不能证明未来盈利保证。",
        "future_profit_guarantee",
        "insufficient_evidence",
    ),
    (
        "T27",
        "MU FY2026 年报中尚未公布的 FY2027 全年审计利润是多少？",
        "What is the unpublished audited full-year FY2027 profit in the MU FY2026 annual report?",
        "未公布未来审计数据不在语料中。",
        "unpublished_future_audit",
        "insufficient_evidence",
    ),
    (
        "T28",
        "库存是不是太高了？",
        "Is inventory too high?",
        "需要明确公司、财年、比较基准和指标。",
        "ambiguous_inventory",
        "clarify",
    ),
    (
        "T29",
        "只凭 NVDA FY2026 年报告诉我今天盘中即时股价。",
        "What is the live intraday share price today using only the NVDA FY2026 annual report?",
        "年报不是实时行情来源。",
        "live_market_price",
        "insufficient_evidence",
    ),
    (
        "T30",
        "AMD FY2025 年报里的完整未公开客户订单名单是什么？",
        "What is the complete undisclosed customer order book in the AMD FY2025 annual report?",
        "不能从公开年报推导完整未公开订单名单。",
        "undisclosed_order_book",
        "insufficient_evidence",
    ),
]
for id, zh, en, answer, family, outcome in boundaries:
    q(id, zh, en, answer, [], family, "boundary", outcome=outcome, docs=[])
assert len(S) == 60, len(S)
# Units are mandatory evidence, not an assumption inferred from dollar signs.
for spec in S:
    if spec["family"] not in {
        "consolidated_revenue",
        "inventory_balances",
        "rd_comparative_columns",
        "cash_flow_growth_NVDA",
        "cash_flow_growth_MU",
        "cash_flow_growth_AMD",
    }:
        continue
    units = []
    for group in list(spec["sources"]):
        for source in group:
            doc, n = source["document_id"], source["ordinal"]
            block = B[doc][n]
            if block.kind != "table":
                continue
            found = next(
                (sel(doc, n, x) for x in block.text.splitlines() if "in millions" in x.lower()),
                None,
            )
            if found is None:
                prior = B[doc][max(0, n - 4) : n]
                found = next(
                    (
                        sel(doc, x.ordinal)
                        for x in reversed(prior)
                        if "in millions" in x.text.lower() and len(x.text) < 160
                    ),
                    None,
                )
            if found is None:
                found = next(
                    (
                        sel(doc, x.ordinal)
                        for x in B[doc][:n]
                        if "all tabular amounts in millions" in x.text.lower()
                    ),
                    None,
                )
            if found is None:
                raise ValueError(("Missing unit evidence", doc, n))
            if found not in units:
                units.append(found)
    spec["sources"].extend([[u] for u in units])
atomic_json(ROOT / "data/evaluation/gpt_specs.json", S)
print("Wrote 60 fixed GPT annotations; raw-source checking and human review remain separate steps")
