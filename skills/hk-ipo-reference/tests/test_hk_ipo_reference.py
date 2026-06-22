import datetime as dt
import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HkIpoReferenceTests(unittest.TestCase):
    def test_agent_metadata_matches_current_skill_surface(self):
        text = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("港股打新复盘", text)
        self.assertIn("融资核价", text)
        self.assertIn("P0 证据包", text)
        self.assertIn("回测复盘", text)
        self.assertIn("2026-led", text)
        self.assertIn("stability", text)
        self.assertIn("pre-close leakage", text)
        self.assertIn("$hk-ipo-reference", text)
        self.assertIn("P0 evidence pack", text)
        self.assertIn("financing rules", text)
        self.assertIn("current recommendation", text)
        match = re.search(r'short_description:\s*"([^"]+)"', text)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(len(match.group(1)), 25)
        self.assertLessEqual(len(match.group(1)), 64)

    def test_skill_frontmatter_mentions_current_triggers(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        self.assertIn("financing pricing checklists", frontmatter)
        self.assertIn("financing efficiency audits", frontmatter)
        self.assertIn("prospectus deep-dive priorities", frontmatter)
        self.assertIn("borderline-observation upgrade checks", frontmatter)
        self.assertIn("same-window capital conflict audits", frontmatter)
        self.assertIn("pre-close future-data leakage audits", frontmatter)
        self.assertIn("backtest stability and overfitting audits", frontmatter)
        self.assertIn("expert-readiness gates", frontmatter)
        self.assertIn("招股书深挖", frontmatter)
        self.assertIn("临界观察复核", frontmatter)
        self.assertIn("同窗口资金冲突", frontmatter)
        self.assertIn("融资资金效率", frontmatter)
        self.assertIn("未来数据泄露", frontmatter)
        self.assertIn("过拟合审查", frontmatter)
        self.assertIn("专家就绪审计", frontmatter)

    def test_report_quality_audit_passes_current_report_guardrails(self):
        audit = load_script("audit_report_quality.py")
        report = """
# 港股打新参考报告

生成时间：2026-06-22 10:00
默认资金：现金 HKD 55.00 万；融资倍数 10x；不主动限制票数

**一句话结论**
真正限制不是票数，而是同一笔现金在重叠锁定窗口内不能重复使用。

## 建议申购
### 示例科技（01234.HK）
**融资判断**
- 乙组仅列入候选，至少两个独立需求/额度热度信号且成本可接受后才执行。

## 可选观察
暂无。

## 暂不参与
暂无。

## 临界观察复核清单
暂无。

## 招股书深挖优先队列
暂无。

## 融资核价清单
乙组不可直接执行；至少两个独立需求/额度热度信号且成本可接受后再核价。

## 融资锁单时间表
原则：融资锁单只能使用券商融资截止前可见信息；配售结果、暗盘和首日表现只能用于复盘。

## 默认资金排期建议
暂无。

## 同窗口取舍复核
不得使用一手中签率、配售结果、暗盘或首日涨跌；必要时替换默认排期。

## 资金锁定检查
暂无。

## 上市表现复盘
暂无。

## 数据缺口与下一步
暂无。
"""
        payload = audit.build_payload(report, report_type="current")
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertTrue(payload["summary"]["passed"])

    def test_report_quality_audit_flags_expert_guardrail_failures(self):
        audit = load_script("audit_report_quality.py")
        report = """
# 港股打新参考报告
默认资金：现金 HKD 55.00 万；融资倍数 10x；不主动限制票数
**一句话结论**
## 当前新股
| 股票 | 说明 |
| 示例科技 | 至少确认两个强热度信号后乙组 |
| 状态 | 今日暗盘 |
## 上市表现复盘
"""
        payload = audit.build_payload(report, report_type="current")
        codes = {item["code"] for item in payload["findings"]}
        self.assertIn("raw_current_ipo_dump", codes)
        self.assertIn("old_margin_gate_language", codes)
        self.assertIn("post_close_status_in_recommendation_bucket", codes)
        self.assertIn("missing_current_sections", codes)
        self.assertFalse(payload["summary"]["passed"])

    def test_report_quality_audit_warns_possible_future_data_leakage(self):
        audit = load_script("audit_report_quality.py")
        report = """
# 港股打新参考报告
默认资金：现金 HKD 55.00 万；融资倍数 10x；不主动限制票数
**一句话结论**
## 建议申购
- 推荐依据：一手中签率 10%。
## 可选观察
## 暂不参与
## 临界观察复核清单
## 招股书深挖优先队列
## 融资核价清单
## 融资锁单时间表
## 默认资金排期建议
## 同窗口取舍复核
不得使用一手中签率、配售结果、暗盘或首日涨跌。
## 资金锁定检查
## 上市表现复盘
## 数据缺口与下一步
"""
        payload = audit.build_payload(report, report_type="current")
        warnings = [item for item in payload["findings"] if item["severity"] == "warning"]
        self.assertTrue(any(item["code"] == "possible_future_data_leakage" for item in warnings))

    def test_report_quality_audit_accepts_backtest_misattribution_heading(self):
        audit = load_script("audit_report_quality.py")
        report = """
# 2026 年港股打新回测
本轮策略以 2026 年单年样本为主。旧年份只适合做压力测试。
一手期望毛利为复盘口径，不能泄露进申购前模型。

## 资金窗口压力测试
口径：默认现金 HKD 55 万；同一锁定窗口现金不可重复使用。

## 排期排序敏感性
排序只使用事前可见字段。

## 历史孖展覆盖审查
覆盖率低于 70% 时只能作为数据缺口审查。

## 热度闸门复盘代理
暂无。

## 当前年份专家审查
2026 为主评估年份。

## 评分分层校准
暂无。

## 错判归因
暂无。
"""
        payload = audit.build_payload(report, report_type="backtest")
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertTrue(payload["summary"]["passed"])

    def test_report_quality_audit_accepts_multi_year_backtest_guardrails(self):
        audit = load_script("audit_report_quality.py")
        report = """
# 2026、2025、2024 港股打新多年份回测
主评估年份：2026；旧年份只作为低权重压力测试，不直接推翻当前市场有效信号；主结论以单年回测为准。
近因权重：2026=1.00, 2025=0.15, 2024=0.02
有效权重：2026=1.00, 2025=0.15, 2024=0.02

## 年度表现
包含一手期望和融资成本语境。

## 近因加权表现
暂无。

## 融资分层近因加权
暂无。

## 跨周期融资压力审查
压力结论：乙组候选跨周期不稳定；不应默认执行乙组。

## 专家审查结论
2026 单年审查：主评估年份当前策略不弱于原策略；近因加权只是旁证。
"""
        payload = audit.build_payload(report, report_type="backtest")
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertTrue(payload["summary"]["passed"])

    def test_report_quality_audit_flags_missing_multi_year_financing_review(self):
        audit = load_script("audit_report_quality.py")
        report = """
# 2026、2025、2024 港股打新多年份回测
主评估年份：2026；旧年份只作为低权重压力测试。
近因权重：2026=1.00
有效权重：2026=1.00

## 年度表现
暂无。

## 近因加权表现
暂无。

## 融资分层近因加权
暂无。

## 专家审查结论
暂无。
"""
        payload = audit.build_payload(report, report_type="backtest")
        codes = {item["code"] for item in payload["findings"]}
        self.assertIn("missing_multi_year_sections", codes)
        self.assertFalse(payload["summary"]["passed"])

    def test_report_quality_audit_warns_unverified_chinese_names_in_backtests(self):
        audit = load_script("audit_report_quality.py")
        annual_report = """
# 2026 年港股打新回测
本轮策略以 2026 年单年样本为主。旧年份只适合做压力测试。
一手期望毛利为复盘口径，不能泄露进申购前模型。

## 资金窗口压力测试
口径：默认现金 HKD 55 万；同一锁定窗口现金不可重复使用；平均一手期望和一手期望覆盖均需展示。

## 排期排序敏感性
排序只使用事前可见字段。

## 历史孖展覆盖审查
覆盖率低于 70% 时只能作为数据缺口审查。

## 热度闸门复盘代理
暂无。

## 当前年份专家审查
2026 为主评估年份。代码00100.HK（中文名待核实）

## 评分分层校准
暂无。

## 错判归因
暂无。
"""
        annual_payload = audit.build_payload(annual_report, report_type="backtest")
        annual_codes = {item["code"] for item in annual_payload["findings"]}
        self.assertIn("unverified_chinese_names", annual_codes)

        multi_year_report = """
# 2026、2025、2024 港股打新多年份回测
主评估年份：2026；旧年份只作为低权重压力测试，不直接推翻当前市场有效信号；主结论以单年回测为准。
近因权重：2026=1.00, 2025=0.15, 2024=0.02
有效权重：2026=1.00, 2025=0.15, 2024=0.02

## 年度表现
包含一手期望和融资成本语境。代码00100.HK（中文名待核实）

## 近因加权表现
暂无。

## 融资分层近因加权
暂无。

## 跨周期融资压力审查
压力结论：乙组候选跨周期不稳定；不应默认执行乙组。

## 专家审查结论
2026 单年审查：主评估年份当前策略不弱于原策略；近因加权只是旁证。
"""
        multi_payload = audit.build_payload(multi_year_report, report_type="backtest")
        multi_codes = {item["code"] for item in multi_payload["findings"]}
        self.assertIn("unverified_chinese_names", multi_codes)

    def test_backtest_stability_audit_flags_remaining_expert_gaps(self):
        audit = load_script("audit_backtest_stability.py")
        payload = {
            "year": 2026,
            "records": [{}, {}, {}],
            "data_quality": {"total": 3, "detail_ok_count": 3, "industry_count": 3},
            "summary": {
                "by_action": {
                    "建议申购": {
                        "count": 2,
                        "positive_rate": 0.9,
                        "strong_rate": 0.6,
                        "avg_first_day_pct": 60.0,
                        "avg_expected_one_lot_pnl_hkd": 120.0,
                    },
                    "可选观察": {
                        "count": 1,
                        "avg_first_day_pct": 30.0,
                        "avg_expected_one_lot_pnl_hkd": 30.0,
                    },
                    "暂不参与": {"count": 1},
                }
            },
            "legacy_summary": {
                "by_action": {
                    "建议申购": {
                        "count": 1,
                        "avg_first_day_pct": 50.0,
                        "avg_expected_one_lot_pnl_hkd": 90.0,
                    }
                }
            },
            "score_band_summary": {
                "78+": {
                    "count": 10,
                    "strong_rate": 0.50,
                    "avg_expected_one_lot_pnl_hkd": 80.0,
                    "median_first_day_pct": 45.0,
                    "median_expected_one_lot_pnl_hkd": 40.0,
                    "return_proxy_sample_count": 10,
                },
                "72-77": {
                    "count": 10,
                    "strong_rate": 0.60,
                    "avg_expected_one_lot_pnl_hkd": 120.0,
                    "median_first_day_pct": 20.0,
                    "median_expected_one_lot_pnl_hkd": 100.0,
                    "return_proxy_sample_count": 10,
                },
            },
            "margin_history_coverage": {
                "b_group_candidate_count": 10,
                "coverage_rate": 0.0,
            },
            "capital_schedule": {
                "conflict_skipped_count": 2,
                "selected_avg_expected_one_lot_pnl_hkd": 50.0,
                "conflict_avg_expected_one_lot_pnl_hkd": 130.0,
                "selected_strong_rate": 0.5,
                "conflict_strong_rate": 0.7,
            },
        }
        result = audit.audit_payload(payload, primary_year=2026, min_primary_samples=1)
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(result["summary"]["errors"], 0)
        self.assertTrue(result["summary"]["passed"])
        self.assertIn("current_strategy_not_worse_than_legacy", codes)
        self.assertIn("score_band_non_monotonic", codes)
        self.assertIn("score_band_financing_efficiency_divergence", codes)
        self.assertIn("margin_history_coverage_low", codes)
        self.assertIn("capital_window_opportunity_cost_high", codes)
        margin_finding = next(item for item in result["findings"] if item["code"] == "margin_history_coverage_low")
        self.assertIn("--priority-levels P0", margin_finding["recommendation"])
        markdown = audit.render_markdown(result)
        self.assertIn("港股打新回测稳定性审查", markdown)
        self.assertIn("不建议继续机械调阈值", markdown)

    def test_backtest_stability_audit_separates_utility_schedule_residual_gap(self):
        audit = load_script("audit_backtest_stability.py")
        payload = {
            "year": 2026,
            "records": [{} for _ in range(30)],
            "data_quality": {"total": 30, "detail_ok_count": 30, "industry_count": 30},
            "summary": {
                "by_action": {
                    "建议申购": {
                        "count": 12,
                        "positive_rate": 0.9,
                        "strong_rate": 0.6,
                        "avg_first_day_pct": 60.0,
                        "avg_expected_one_lot_pnl_hkd": 120.0,
                    },
                    "可选观察": {"count": 16, "avg_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 60.0},
                    "暂不参与": {"count": 5},
                }
            },
            "legacy_summary": {
                "by_action": {"建议申购": {"count": 10, "avg_first_day_pct": 50.0, "avg_expected_one_lot_pnl_hkd": 90.0}}
            },
            "score_band_summary": {
                "78+": {"count": 10, "strong_rate": 0.70, "avg_expected_one_lot_pnl_hkd": 180.0},
                "72-77": {"count": 10, "strong_rate": 0.50, "avg_expected_one_lot_pnl_hkd": 100.0},
            },
            "margin_history_coverage": {
                "b_group_candidate_count": 0,
                "coverage_rate": None,
            },
            "capital_schedule": {
                "priority_strategy": "utility_score_entry",
                "conflict_skipped_count": 2,
                "selected_avg_expected_one_lot_pnl_hkd": 100.0,
                "conflict_avg_expected_one_lot_pnl_hkd": 200.0,
                "selected_strong_rate": 0.5,
                "conflict_strong_rate": 0.7,
            },
        }
        result = audit.audit_payload(payload, primary_year=2026, min_primary_samples=30)
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("capital_window_residual_data_gap", codes)
        self.assertNotIn("capital_window_opportunity_cost_high", codes)
        capital_finding = next(item for item in result["findings"] if item["code"] == "capital_window_residual_data_gap")
        self.assertIn("prepare_conflict_research_template.py --priority-levels P0", capital_finding["recommendation"])
        self.assertEqual(result["metrics"]["capital_priority_strategy"], "utility_score_entry")

    def test_backtest_stability_audit_rejects_worse_current_strategy(self):
        audit = load_script("audit_backtest_stability.py")
        payload = {
            "year": 2026,
            "records": [{} for _ in range(30)],
            "data_quality": {"total": 30, "detail_ok_count": 30, "industry_count": 30},
            "summary": {
                "by_action": {
                    "建议申购": {
                        "count": 10,
                        "avg_first_day_pct": 10.0,
                        "avg_expected_one_lot_pnl_hkd": 20.0,
                    },
                    "可选观察": {
                        "count": 20,
                        "avg_first_day_pct": 40.0,
                        "avg_expected_one_lot_pnl_hkd": 100.0,
                    },
                    "暂不参与": {"count": 5},
                }
            },
            "legacy_summary": {
                "by_action": {
                    "建议申购": {
                        "count": 10,
                        "avg_first_day_pct": 40.0,
                        "avg_expected_one_lot_pnl_hkd": 120.0,
                    }
                }
            },
            "score_band_summary": {
                "78+": {"count": 10, "strong_rate": 0.70, "avg_expected_one_lot_pnl_hkd": 150.0},
                "72-77": {"count": 10, "strong_rate": 0.50, "avg_expected_one_lot_pnl_hkd": 100.0},
            },
            "margin_history_coverage": {
                "b_group_candidate_count": 0,
                "coverage_rate": None,
            },
            "capital_schedule": {
                "conflict_skipped_count": 0,
                "selected_avg_expected_one_lot_pnl_hkd": 100.0,
                "conflict_avg_expected_one_lot_pnl_hkd": None,
            },
        }
        result = audit.audit_payload(payload, primary_year=2026, min_primary_samples=30)
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("current_strategy_materially_worse", codes)
        self.assertIn("recommendation_bucket_not_separated", codes)
        self.assertFalse(result["summary"]["passed"])

    def test_backtest_stability_audit_flags_concentrated_miss_attribution(self):
        audit = load_script("audit_backtest_stability.py")
        payload = {
            "year": 2026,
            "records": [{} for _ in range(30)],
            "data_quality": {"total": 30, "detail_ok_count": 30, "industry_count": 30},
            "summary": {
                "by_action": {
                    "建议申购": {
                        "count": 12,
                        "positive_rate": 0.9,
                        "strong_rate": 0.7,
                        "avg_first_day_pct": 80.0,
                        "avg_expected_one_lot_pnl_hkd": 180.0,
                    },
                    "可选观察": {
                        "count": 16,
                        "avg_first_day_pct": 30.0,
                        "avg_expected_one_lot_pnl_hkd": 60.0,
                    },
                    "暂不参与": {"count": 5},
                }
            },
            "legacy_summary": {
                "by_action": {
                    "建议申购": {
                        "count": 10,
                        "avg_first_day_pct": 70.0,
                        "avg_expected_one_lot_pnl_hkd": 150.0,
                    }
                }
            },
            "score_band_summary": {
                "78+": {"count": 10, "strong_rate": 0.70, "avg_expected_one_lot_pnl_hkd": 180.0},
                "72-77": {"count": 10, "strong_rate": 0.50, "avg_expected_one_lot_pnl_hkd": 100.0},
            },
            "margin_history_coverage": {
                "b_group_candidate_count": 0,
                "coverage_rate": None,
            },
            "capital_schedule": {
                "conflict_skipped_count": 0,
                "selected_avg_expected_one_lot_pnl_hkd": 120.0,
                "conflict_avg_expected_one_lot_pnl_hkd": 80.0,
            },
            "miss_attribution_summary": {
                "false_positive_count": 4,
                "false_negative_count": 5,
                "dominant_false_positive": {
                    "reason": "乙组候选未被证明可执行，需强制融资截止前二次锁单",
                    "count": 3,
                    "share": 0.75,
                    "examples": ["示例科技（01234.HK）"],
                },
                "dominant_false_negative": {
                    "reason": "最终强热度，说明事前孖展/额度时间序列应触发升级复核",
                    "count": 2,
                    "share": 0.40,
                    "examples": ["观察科技（05678.HK）"],
                },
                "false_positive_recommendation": "优先补融资截止前孖展/额度/利率历史。",
                "false_negative_recommendation": "把该类样本纳入临界观察和 T-1/T-0 升级复核。",
            },
        }
        result = audit.audit_payload(payload, primary_year=2026, min_primary_samples=30)
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("false_positive_attribution_concentrated", codes)
        self.assertIn("false_negative_attribution_concentrated", codes)
        fp_finding = next(item for item in result["findings"] if item["code"] == "false_positive_attribution_concentrated")
        self.assertIn("prepare_execution_risk_template.py --priority-levels P0", fp_finding["recommendation"])
        markdown = audit.render_markdown(result)
        self.assertIn("建议申购错判数", markdown)
        self.assertIn("漏掉强收益数", markdown)
        self.assertIn("prepare_borderline_upgrade_template.py", markdown)
        self.assertIn("--priority-levels P0", markdown)

    def test_backtest_stability_audit_flags_score_band_financing_efficiency_divergence(self):
        audit = load_script("audit_backtest_stability.py")
        payload = {
            "year": 2026,
            "records": [{} for _ in range(30)],
            "data_quality": {"total": 30, "detail_ok_count": 30, "industry_count": 30},
            "summary": {
                "by_action": {
                    "建议申购": {"count": 12, "avg_first_day_pct": 60.0, "avg_expected_one_lot_pnl_hkd": 120.0},
                    "可选观察": {"count": 16, "avg_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 60.0},
                    "暂不参与": {"count": 5},
                }
            },
            "legacy_summary": {
                "by_action": {"建议申购": {"count": 10, "avg_first_day_pct": 50.0, "avg_expected_one_lot_pnl_hkd": 100.0}}
            },
            "score_band_summary": {
                "78+": {
                    "count": 12,
                    "strong_rate": 0.70,
                    "avg_expected_one_lot_pnl_hkd": 90.0,
                    "median_first_day_pct": 55.0,
                    "median_expected_one_lot_pnl_hkd": 40.0,
                    "return_proxy_sample_count": 12,
                },
                "72-77": {
                    "count": 12,
                    "strong_rate": 0.60,
                    "avg_expected_one_lot_pnl_hkd": 120.0,
                    "median_first_day_pct": 25.0,
                    "median_expected_one_lot_pnl_hkd": 100.0,
                    "return_proxy_sample_count": 12,
                },
            },
            "margin_history_coverage": {"b_group_candidate_count": 0, "coverage_rate": None},
            "capital_schedule": {"conflict_skipped_count": 0},
        }
        result = audit.audit_payload(payload, primary_year=2026, min_primary_samples=30)
        finding = next(
            item for item in result["findings"] if item["code"] == "score_band_financing_efficiency_divergence"
        )
        self.assertIn("配售/融资效率", finding["message"])
        self.assertIn("median_one_lot", finding["evidence"])
        self.assertIn("不要用首日涨幅中位数直接放大乙组", finding["recommendation"])

    def test_backtest_stability_audit_points_capital_efficiency_misses_to_execution_template(self):
        audit = load_script("audit_backtest_stability.py")
        payload = {
            "year": 2026,
            "records": [{} for _ in range(30)],
            "data_quality": {"total": 30, "detail_ok_count": 30, "industry_count": 30},
            "summary": {
                "by_action": {
                    "建议申购": {"count": 10, "avg_first_day_pct": 50.0, "avg_expected_one_lot_pnl_hkd": 120.0},
                    "可选观察": {"count": 15},
                    "暂不参与": {"count": 5},
                }
            },
            "legacy_summary": {
                "by_action": {"建议申购": {"count": 10, "avg_first_day_pct": 45.0, "avg_expected_one_lot_pnl_hkd": 100.0}}
            },
            "score_band_summary": {
                "78+": {"count": 10, "strong_rate": 0.70, "avg_expected_one_lot_pnl_hkd": 180.0},
                "72-77": {"count": 10, "strong_rate": 0.50, "avg_expected_one_lot_pnl_hkd": 100.0},
            },
            "margin_history_coverage": {"b_group_candidate_count": 0, "coverage_rate": None},
            "capital_schedule": {"conflict_skipped_count": 0},
            "miss_attribution_summary": {
                "false_positive_count": 5,
                "false_negative_count": 0,
                "dominant_false_positive": {
                    "reason": "一手期望不正，资金效率不足",
                    "count": 5,
                    "share": 1.0,
                },
                "false_positive_recommendation": "把一手期望、融资息费和资金窗口作为复盘/锁单检查，不要只优化首日涨幅。",
            },
        }
        result = audit.audit_payload(payload, primary_year=2026, min_primary_samples=30)
        finding = next(item for item in result["findings"] if item["code"] == "false_positive_attribution_concentrated")
        self.assertIn("prepare_execution_risk_template.py", finding["recommendation"])
        self.assertIn("--scenario-json", finding["recommendation"])

    def test_backtest_next_action_plan_maps_stability_findings_to_commands(self):
        planner = load_script("plan_backtest_next_actions.py")
        stability = {
            "primary_year": 2026,
            "summary": {"verdict": "通过但需继续补数据/人工审查：不建议继续机械调阈值。"},
            "findings": [
                {
                    "code": "current_strategy_not_worse_than_legacy",
                    "severity": "info",
                    "message": "当前策略在主评估年份未弱于原策略。",
                },
                {
                    "code": "margin_history_coverage_low",
                    "severity": "warning",
                    "message": "乙组候选缺少足够历史孖展。",
                    "evidence": "b_group=23, coverage=0.0%",
                },
                {
                    "code": "false_positive_attribution_concentrated",
                    "severity": "warning",
                    "message": "建议申购错判集中。",
                    "evidence": "top=一手期望不正",
                },
                {
                    "code": "false_negative_attribution_concentrated",
                    "severity": "warning",
                    "message": "漏掉强收益集中。",
                    "evidence": "top=临界观察升级",
                },
                {
                    "code": "capital_window_residual_data_gap",
                    "severity": "warning",
                    "message": "同窗口残余数据缺口。",
                },
                {
                    "code": "score_band_non_monotonic",
                    "severity": "warning",
                    "message": "分数不单调。",
                },
                {
                    "code": "score_band_financing_efficiency_divergence",
                    "severity": "warning",
                    "message": "高分段首日中位数更强但一手期望中位数更弱。",
                    "evidence": "78+ median_first=+55.00%, median_one_lot=HKD 40",
                },
                {
                    "code": "skip_bucket_sample_small",
                    "severity": "warning",
                    "message": "暂不参与样本太少。",
                },
            ],
        }
        payload = planner.build_payload(
            stability,
            backtest_json="/tmp/backtest-2026.json",
            backtest_report="/tmp/backtest-2026.md",
        )
        commands = "\n".join(item["command"] for item in payload["actions"])
        self.assertIn("prepare_margin_history_template.py --backtest-json /tmp/backtest-2026.json --priority-levels P0", commands)
        self.assertIn("prepare_execution_risk_template.py --input-json /tmp/backtest-2026.json", commands)
        self.assertIn("prepare_borderline_upgrade_template.py --input-json /tmp/backtest-2026.json --priority-levels P0", commands)
        self.assertIn("prepare_conflict_research_template.py --input-json /tmp/backtest-2026.json --priority-levels P0", commands)
        self.assertEqual(payload["iteration_gate"]["status"], "先补 P0 证据")
        self.assertFalse(payload["iteration_gate"]["threshold_tuning_allowed"])
        self.assertTrue(payload["iteration_gate"]["evidence_collection_required"])
        priorities = [item["priority"] for item in payload["actions"]]
        self.assertEqual(priorities[:3], ["P0", "P0", "P0"])
        self.assertEqual(
            [item["domain"] for item in payload["actions"][:3]],
            ["乙组执行验证", "建议申购执行风险", "临界观察升级"],
        )
        workflows = payload["evidence_workflows"]
        self.assertEqual(
            [item["domain"] for item in workflows],
            ["乙组执行验证", "建议申购执行风险", "临界观察升级", "同窗口资金取舍"],
        )
        workflow_text = "\n".join(
            "\n".join(
                [
                    item["create_command"],
                    item["normalize_command"],
                    item.get("readiness_command") or "",
                    item["review_command"],
                    item["success_criteria"],
                ]
            )
            for item in workflows
        )
        self.assertIn("normalize_margin_history.py --input margin-history-2026-p0.csv", workflow_text)
        self.assertIn("normalize_margin_history.py --input margin-history-2026-p0.csv --markdown", workflow_text)
        self.assertIn("backtest_margin_gate.py --backtest-json /tmp/backtest-2026.json", workflow_text)
        self.assertIn("prepare_execution_risk_template.py --input-json /tmp/backtest-2026.json --priority-levels P0", workflow_text)
        self.assertIn("normalize_conflict_research_input.py --input execution-risk-2026.csv", workflow_text)
        self.assertIn("normalize_conflict_research_input.py --input execution-risk-2026.csv --markdown", workflow_text)
        self.assertIn("prepare_borderline_upgrade_template.py --input-json /tmp/backtest-2026.json --priority-levels P0", workflow_text)
        self.assertIn("normalize_conflict_research_input.py --input borderline-upgrade-2026-p0.csv", workflow_text)
        self.assertIn("prepare_conflict_research_template.py --input-json /tmp/backtest-2026.json --priority-levels P0", workflow_text)
        self.assertIn("normalize_conflict_research_input.py --input conflict-research-2026-p0.csv", workflow_text)
        self.assertIn("audit_financing_efficiency.py --input-json /tmp/backtest-2026.json", workflow_text)
        self.assertIn("--include scenario", workflow_text)
        self.assertIn("P0 可复核或明确缺数据后才扩展 P1", workflow_text)
        self.assertIn("P0 排期边界样本", workflow_text)
        self.assertIn("不得降低建议阈值", workflow_text)
        markdown = planner.render_markdown(payload)
        self.assertIn("港股打新回测下一步动作计划", markdown)
        self.assertIn("## 证据闭环", markdown)
        self.assertIn("生成 CSV", markdown)
        self.assertIn("audit_preclose_leakage.py", markdown)
        self.assertIn("最终超购", markdown)
        self.assertIn("允许继续机械调阈值：否", markdown)
        self.assertIn("融资/配售效率校准", markdown)

    def test_p0_evidence_pack_summarizes_domains_and_overlap_without_review_leakage(self):
        pack = load_script("prepare_p0_evidence_pack.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "高分乙组",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "first_day_change_pct": 123.0,
                    "oversubscription_rate": 9999.0,
                    "one_lot_success_rate_pct": 1.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": ["估值待核实"],
                        "financing": {"tier": "乙组候选"},
                    },
                },
                {
                    "code": "02222.HK",
                    "name": "边际甲组",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "first_day_change_pct": -50.0,
                    "oversubscription_rate": 1.0,
                    "recommendation": {
                        "score": 79,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "甲组候选"},
                    },
                },
                {
                    "code": "03333.HK",
                    "name": "临界观察",
                    "industry": "生物科技",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 5_000.0,
                    "first_day_change_pct": 200.0,
                    "oversubscription_rate": 8888.0,
                    "recommendation": {
                        "score": 69,
                        "action": "可选观察",
                        "evidence": ["低入场费"],
                        "risks": [],
                        "financing": {"tier": "现金参与"},
                    },
                },
            ],
        }
        result = pack.build_payload(
            payload,
            backtest_json="/tmp/backtest-2026.json",
            cash_hkd=100_000,
            brokers_arg="",
        )
        domains = {item["domain"]: item for item in result["domains"]}
        self.assertEqual(domains["margin_history"]["stock_count"], 1)
        self.assertEqual(domains["execution_risk"]["stock_count"], 1)
        self.assertEqual(domains["borderline_upgrade"]["stock_count"], 1)
        self.assertEqual(domains["capital_conflict"]["stock_count"], 2)
        self.assertEqual(result["summary"]["p0_unique_stock_count"], 3)
        self.assertEqual(result["summary"]["p0_total_stock_mentions"], 5)
        self.assertEqual(result["summary"]["consolidated_row_count"], 3)
        self.assertEqual(result["summary"]["consolidation_reduction"], 2)
        overlap = next(item for item in result["overlaps"] if item["stock"].startswith("高分乙组"))
        self.assertIn("乙组执行验证", overlap["domain_labels"])
        self.assertIn("建议申购执行风险", overlap["domain_labels"])
        self.assertIn("同窗口资金取舍", overlap["domain_labels"])
        consolidated = next(row for row in result["consolidated_rows"] if row["stock"].startswith("高分乙组"))
        self.assertEqual(consolidated["domain_count"], 3)
        self.assertIn("乙组执行验证", consolidated["domains"])
        self.assertIn("建议申购执行风险", consolidated["domains"])
        self.assertIn("同窗口资金取舍", consolidated["domains"])
        self.assertIn("observed_at", consolidated["required_checks"])
        self.assertIn("情景配售率", consolidated["required_checks"])
        consolidated_csv = pack.render_consolidated_csv(result["consolidated_rows"])
        self.assertIn("domains", consolidated_csv)
        self.assertIn("scenario_allotment_rate_pct", consolidated_csv)
        self.assertIn("高分乙组", consolidated_csv)
        self.assertNotIn("123.0", consolidated_csv)
        self.assertNotIn("9999", consolidated_csv)
        self.assertNotIn("one_lot_success", consolidated_csv)
        markdown = pack.render_markdown(result)
        self.assertIn("港股打新 P0 证据包", markdown)
        self.assertIn("合并补采工作表：3 行，较领域内提及减少 2 行", markdown)
        self.assertIn("prepare_margin_history_template.py", markdown)
        self.assertIn("normalize_margin_history.py --input margin-history-2026-p0.csv --markdown", markdown)
        self.assertIn("prepare_conflict_research_template.py", markdown)
        self.assertIn("允许继续机械调阈值：否", markdown)
        self.assertNotIn("123.0", markdown)
        self.assertNotIn("9999", markdown)

    def test_p0_evidence_pack_commands_quote_paths_and_preserve_brokers(self):
        pack = load_script("prepare_p0_evidence_pack.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "高分乙组",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ],
        }
        result = pack.build_payload(
            payload,
            backtest_json="/tmp/hk ipo/backtest 2026.json",
            cash_hkd=100_000,
            brokers_arg="富途,辉立",
        )
        domains = {item["domain"]: item for item in result["domains"]}
        margin_command = domains["margin_history"]["create_command"]
        execution_command = domains["execution_risk"]["create_command"]
        review_command = domains["margin_history"]["review_command"]
        self.assertIn("--backtest-json '/tmp/hk ipo/backtest 2026.json'", margin_command)
        self.assertIn("--brokers '富途,辉立'", margin_command)
        self.assertIn("--cash-hkd 100000", execution_command)
        self.assertIn("--input-json '/tmp/hk ipo/backtest 2026.json'", execution_command)
        self.assertIn("--backtest-json '/tmp/hk ipo/backtest 2026.json'", review_command)

    def test_split_p0_consolidated_input_routes_rows_to_domain_normalizers(self):
        splitter = load_script("split_p0_consolidated_input.py")
        readiness = load_script("audit_expert_readiness.py")
        margin_history = load_script("normalize_margin_history.py")
        conflict_input = load_script("normalize_conflict_research_input.py")
        rows = [
            {
                "code": "01111.HK",
                "stock": "高分乙组（01111.HK）",
                "domains": "乙组执行验证、建议申购执行风险、同窗口资金取舍",
                "domain_count": "3",
                "score": "82",
                "action": "建议申购",
                "financing_tier": "乙组候选",
                "entry_fee_hkd": "100000",
                "closing_date": "2026-06-01",
                "refund_date": "2026-06-05",
                "priority_reasons": "缺申购前孖展热度",
                "required_checks": "observed_at、broker_cutoff_at、情景配售率",
                "collection_note": "合并P0补采工作表",
            },
            {
                "code": "03333.HK",
                "stock": "临界观察",
                "domains": "临界观察升级",
                "domain_count": "1",
                "score": "69",
                "action": "可选观察",
                "financing_tier": "现金参与",
                "entry_fee_hkd": "5000",
                "closing_date": "2026-06-01",
                "refund_date": "2026-06-05",
                "priority_reasons": "69-71临界高分",
                "required_checks": "observed_at、broker_cutoff_at、情景配售率",
            },
        ]
        margin_rows = splitter.split_rows(rows, domain="margin_history")
        self.assertEqual(len(margin_rows), 1)
        self.assertEqual(margin_rows[0]["stock_name"], "高分乙组")
        self.assertEqual(margin_rows[0]["collection_priority"], "P0")
        margin_csv = splitter.render_csv(margin_rows, domain="margin_history")
        self.assertIn("stock_name", margin_csv)
        self.assertIn("preclose_confirmed", margin_csv)
        normalized_margin = margin_history.normalize_rows(margin_rows)
        self.assertEqual(len(normalized_margin["stocks"]), 1)
        self.assertEqual(margin_history.stock_status(normalized_margin["stocks"][0]), "待填回")
        with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8") as tmp:
            tmp.write(margin_csv)
            tmp.flush()
            readiness_payload = readiness.load_p0_readiness_payload("margin_history", tmp.name)
        self.assertEqual(len(readiness_payload["stocks"]), 1)

        execution_rows = splitter.split_rows(rows, domain="execution_risk")
        self.assertEqual(len(execution_rows), 1)
        self.assertEqual(execution_rows[0]["stock"], "高分乙组")
        self.assertEqual(execution_rows[0]["group_id"], "execution_risk")
        execution_csv = splitter.render_csv(execution_rows, domain="execution_risk")
        self.assertIn("scenario_allotment_rate_pct", execution_csv)
        normalized_execution = conflict_input.normalize_rows(execution_rows)
        self.assertEqual(normalized_execution["summary"]["stock_count"], 1)
        self.assertEqual(normalized_execution["summary"]["pending_input_stock_count"], 1)

        borderline_rows = splitter.split_rows(rows, domain="borderline_upgrade")
        self.assertEqual(len(borderline_rows), 1)
        self.assertEqual(borderline_rows[0]["stock"], "临界观察")

    def test_filled_consolidated_p0_sheet_can_close_expert_gate(self):
        pack = load_script("prepare_p0_evidence_pack.py")
        splitter = load_script("split_p0_consolidated_input.py")
        readiness = load_script("audit_expert_readiness.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "高分乙组",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ],
        }
        pack_payload = pack.build_payload(payload, backtest_json="/tmp/backtest-2026.json")
        self.assertEqual(pack_payload["summary"]["p0_total_stock_mentions"], 2)
        filled = dict(pack_payload["consolidated_rows"][0])
        filled.update(
            {
                "observed_at": "2026-05-31 10:00",
                "source_published_at": "2026-05-31 10:05",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "80",
                "margin_amount_hkd": "1200000000",
                "quota_status": "多家券商额度紧张，富途额度接近用完",
                "financing_rate_pct": "2.5",
                "fees_hkd": "100",
                "financing_days": "6",
                "scenario_first_day_pct": "20",
                "scenario_allotment_rate_pct": "0.8",
                "max_credible_allotment_rate_pct": "1.2",
                "prospectus_url": "https://example.com/prospectus.pdf",
                "valuation_note": "估值较同业折让",
                "peer_comparable_note": "同业需求较强",
                "cornerstone_lockup_note": "基石质量较好且禁售明确",
                "demand_validation": "多券商孖展领先且尾日加速",
                "source": "https://example.com/preclose-margin",
                "excerpt": "2026-05-31 10:00 富途孖展认购额12亿，约80倍；多家券商热度一致，额度紧张，年化利率2.5%。",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            consolidated_path = tmpdir_path / "p0-consolidated.csv"
            consolidated_path.write_text(pack.render_consolidated_csv([filled]), encoding="utf-8")
            margin_path = tmpdir_path / "margin.csv"
            execution_path = tmpdir_path / "execution.csv"
            margin_path.write_text(
                splitter.render_csv(splitter.split_rows([filled], domain="margin_history"), domain="margin_history"),
                encoding="utf-8",
            )
            execution_path.write_text(
                splitter.render_csv(splitter.split_rows([filled], domain="execution_risk"), domain="execution_risk"),
                encoding="utf-8",
            )
            result = readiness.build_payload(
                payload,
                backtest_json="/tmp/backtest-2026.json",
                primary_year=2026,
                stability_payload={
                    "primary_year": 2026,
                    "summary": {"errors": 0, "warnings": 0, "verdict": "通过。"},
                    "findings": [
                        {
                            "code": "current_strategy_not_worse_than_legacy",
                            "severity": "info",
                            "message": "当前策略在主评估年份未弱于原策略。",
                        }
                    ],
                },
                p0_readiness_payloads={
                    "margin_history": readiness.load_p0_readiness_payload("margin_history", str(margin_path)),
                    "execution_risk": readiness.load_p0_readiness_payload("execution_risk", str(execution_path)),
                },
            )
        self.assertEqual(result["summary"]["p0_open_stock_mentions"], 0)
        self.assertEqual(result["summary"]["p0_review_ready_stock_mentions"], 2)
        self.assertEqual(result["status"], "expert_ready")

    def test_contaminated_consolidated_p0_sheet_does_not_close_expert_gate(self):
        pack = load_script("prepare_p0_evidence_pack.py")
        splitter = load_script("split_p0_consolidated_input.py")
        readiness = load_script("audit_expert_readiness.py")
        margin_history = load_script("normalize_margin_history.py")
        conflict_input = load_script("normalize_conflict_research_input.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "高分乙组",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ],
        }
        filled = dict(pack.build_payload(payload, backtest_json="/tmp/backtest-2026.json")["consolidated_rows"][0])
        filled.update(
            {
                "observed_at": "2026-05-31 10:00",
                "source_published_at": "2026-05-31 10:05",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "80",
                "margin_amount_hkd": "1200000000",
                "quota_status": "额度紧张",
                "financing_rate_pct": "2.5",
                "fees_hkd": "100",
                "financing_days": "6",
                "scenario_first_day_pct": "20",
                "scenario_allotment_rate_pct": "0.8",
                "max_credible_allotment_rate_pct": "1.2",
                "prospectus_url": "https://example.com/prospectus.pdf",
                "source": "https://example.com/post-close-review",
                "excerpt": "首日上涨50%，一手中签率20%，暗盘表现强。",
            }
        )
        margin_rows = splitter.split_rows([filled], domain="margin_history")
        execution_rows = splitter.split_rows([filled], domain="execution_risk")
        normalized_margin = margin_history.normalize_rows(margin_rows)
        normalized_execution = conflict_input.normalize_rows(execution_rows)
        self.assertEqual(margin_history.stock_status(normalized_margin["stocks"][0]), "证据污染")
        self.assertEqual(normalized_execution["summary"]["evidence_contaminated_stock_count"], 1)
        result = readiness.build_payload(
            payload,
            backtest_json="/tmp/backtest-2026.json",
            primary_year=2026,
            stability_payload={
                "primary_year": 2026,
                "summary": {"errors": 0, "warnings": 0, "verdict": "通过。"},
                "findings": [
                    {
                        "code": "current_strategy_not_worse_than_legacy",
                        "severity": "info",
                        "message": "当前策略在主评估年份未弱于原策略。",
                    }
                ],
            },
            p0_readiness_payloads={
                "margin_history": normalized_margin,
                "execution_risk": normalized_execution,
            },
        )
        self.assertEqual(result["status"], "needs_p0_or_review")
        self.assertEqual(result["summary"]["p0_open_stock_mentions"], 2)
        self.assertEqual(result["summary"]["p0_review_ready_stock_mentions"], 0)

    def test_expert_readiness_p0_backlog_is_not_truncated_by_default(self):
        readiness = load_script("audit_expert_readiness.py")
        rows = [
            {
                "code": f"{11000 + index}.HK",
                "stock": f"待补股票{index}",
                "domains": "乙组执行验证",
                "domain_count": "1",
                "score": str(80 - index),
                "required_checks": "observed_at、broker_cutoff_at、source",
            }
            for index in range(25)
        ]
        backlog = readiness.build_p0_backlog(
            {"consolidated_rows": rows},
            readiness_payloads={},
            accept_data_gaps=False,
        )
        self.assertEqual(len(backlog), 25)
        self.assertEqual(backlog[0]["stock"], "待补股票0")
        self.assertEqual(backlog[-1]["stock"], "待补股票24")
        self.assertIn("未提供填回审查", backlog[0]["statuses"].values())

    def test_prepare_p0_research_queries_builds_preclose_task_list(self):
        queries = load_script("prepare_p0_research_queries.py")
        payload = {
            "primary_year": 2026,
            "status": "needs_p0_or_review",
            "p0_backlog": [
                {
                    "stock": "高分乙组",
                    "code": "01111.HK",
                    "score": "82",
                    "action": "建议申购",
                    "financing_tier": "乙组候选",
                    "entry_fee_hkd": "100000",
                    "domain_count": 3,
                    "open_domain_count": 2,
                    "open_domains": ["乙组执行验证", "建议申购执行风险"],
                    "priority_reasons": "缺申购前孖展热度、事前高分乙组候选",
                    "next_action": "优先补融资热度和情景配售率",
                    "missing_fields": [
                        "pending_input",
                        "scenario_allotment_rate_pct",
                        "prospectus_or_source",
                    ],
                },
                {
                    "stock": "临界观察",
                    "code": "03333.HK",
                    "score": "69",
                    "open_domains": ["临界观察升级"],
                    "missing_fields": ["prospectus_or_source"],
                },
            ],
        }
        result = queries.build_tasks(payload)
        self.assertEqual(result["backlog_stock_count"], 2)
        self.assertGreaterEqual(result["task_count"], 5)
        stock_group = next(item for item in result["stock_groups"] if item["stock"] == "高分乙组")
        self.assertEqual(
            stock_group["core_requirements"],
            ["孖展热度/融资成本", "申购前情景涨幅/配售率", "招股书/估值/基石摘要"],
        )
        self.assertEqual(stock_group["auxiliary_query_types"], ["public_sentiment_auxiliary"])
        generic_margin = next(item for item in result["tasks"] if item["query_type"] == "broker_margin_heat")
        futu_margin = next(item for item in result["tasks"] if item["query_type"] == "broker_margin_富途")
        self.assertEqual(generic_margin["broker"], "")
        self.assertEqual(futu_margin["broker"], "富途")
        for field in ["preclose_confirmed", "fees_hkd", "financing_days", "excerpt"]:
            self.assertIn(field, generic_margin["capture_fields"])
            self.assertIn(field, futu_margin["capture_fields"])
        for query_type in ["preclose_return_scenario", "hkex_prospectus_deep_dive", "public_sentiment_auxiliary"]:
            row = next(item for item in result["tasks"] if item["query_type"] == query_type)
            for field in ["observed_at", "source_published_at", "preclose_confirmed", "broker_cutoff_at", "source", "excerpt"]:
                self.assertIn(field, row["capture_fields"])
        query_text = "\n".join(item["query"] for item in result["tasks"])
        self.assertIn("高分乙组 01111.HK", query_text)
        self.assertIn("手续费", query_text)
        self.assertIn("计息天数", query_text)
        self.assertIn("招股书 HKEX", query_text)
        for forbidden in ["首日", "暗盘", "一手中签率", "配售结果"]:
            self.assertNotIn(forbidden, query_text)
            self.assertIn(forbidden, result["excluded_post_close_terms"])
        csv_text = queries.render_csv(result["tasks"])
        self.assertIn("query_type", csv_text)
        self.assertIn("priority_reasons", csv_text)
        self.assertIn("next_action", csv_text)
        self.assertIn("缺申购前孖展热度", csv_text)
        self.assertIn("乙组候选", csv_text)
        self.assertIn("observed_at", csv_text)
        self.assertIn("source_published_at", csv_text)
        self.assertIn("broker_cutoff_at", csv_text)
        self.assertIn("search_attempted_at", csv_text)
        self.assertIn("unavailable_reason", csv_text)
        self.assertIn("collection_note", csv_text)
        markdown = queries.render_markdown(result)
        self.assertIn("P0 公开资料检索清单", markdown)
        self.assertIn("按股最小闭环清单", markdown)
        self.assertIn("孖展热度/融资成本、申购前情景涨幅/配售率、招股书/估值/基石摘要", markdown)
        self.assertIn("公开舆情辅助", markdown)
        self.assertIn("申购截止前证据", markdown)
        self.assertIn("source_published_at", markdown)
        self.assertIn("优先原因", markdown)
        self.assertIn("缺申购前孖展热度", markdown)
        self.assertIn("normalize_p0_research_ledger.py", markdown)
        limited = queries.build_tasks(payload, limit=1)
        self.assertEqual(limited["backlog_stock_count"], 1)

    def test_normalize_p0_research_ledger_reviews_filled_evidence(self):
        queries = load_script("prepare_p0_research_queries.py")
        ledger = load_script("normalize_p0_research_ledger.py")
        payload = {
            "primary_year": 2026,
            "status": "needs_p0_or_review",
            "p0_backlog": [
                {
                    "stock": "高分乙组",
                    "code": "01111.HK",
                    "score": "82",
                    "open_domains": ["乙组执行验证", "建议申购执行风险"],
                    "missing_fields": ["pending_input", "scenario_allotment_rate_pct"],
                }
            ],
        }
        tasks = queries.build_tasks(payload)["tasks"]
        blank = ledger.build_payload(tasks)
        self.assertEqual(blank["ledger_summary"]["task_count"], len(tasks))
        self.assertEqual(blank["ledger_summary"]["filled_task_count"], 0)
        self.assertEqual(blank["summary"]["pending_input_stock_count"], 1)

        filled = [dict(row) for row in tasks]
        filled[0].update(
            {
                "observed_at": "2026-05-31 10:00",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "80",
                "margin_amount_hkd": "1200000000",
                "quota_status": "额度紧张",
                "financing_rate_pct": "2.5",
                "fees_hkd": "100",
                "financing_days": "6",
                "source": "https://example.com/preclose-margin",
                "excerpt": "2026-05-31 10:00 富途孖展认购额12亿，约80倍，额度紧张。",
            }
        )
        partial = ledger.build_payload(filled)
        self.assertEqual(partial["ledger_summary"]["filled_task_count"], 1)
        self.assertEqual(partial["summary"]["review_ready_stock_count"], 0)
        self.assertEqual(partial["summary"]["missing_data_stock_count"], 1)
        partial_stock = partial["groups"][0]["stocks"][0]
        self.assertEqual(partial_stock["research_status"], "缺数据")
        self.assertIn("scenario_first_day_pct", partial_stock["missing_fields"])
        self.assertIn("prospectus_or_source", partial_stock["missing_fields"])
        self.assertFalse(partial["ledger_summary"]["ready_for_p0_split"])

        scenario_row = next(row for row in filled if row["query_type"] == "preclose_return_scenario")
        scenario_row.update(
            {
                "observed_at": "2026-05-31 10:15",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "scenario_first_day_pct": "20",
                "scenario_allotment_rate_pct": "0.8",
                "max_credible_allotment_rate_pct": "1.2",
                "source": "https://example.com/preclose-scenario",
                "excerpt": "申购截止前情景假设：首日涨幅20%，配售率0.8%。",
            }
        )
        prospectus_row = next(row for row in filled if row["query_type"] == "hkex_prospectus_deep_dive")
        prospectus_row.update(
            {
                "observed_at": "2026-05-31 10:20",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "prospectus_url": "https://example.com/prospectus.pdf",
                "valuation_note": "估值较同业折让",
                "source": "https://example.com/prospectus.pdf",
                "excerpt": "招股书披露估值较同业折让，基石禁售明确。",
            }
        )
        complete = ledger.build_payload(filled)
        self.assertEqual(complete["ledger_summary"]["filled_task_count"], 3)
        self.assertEqual(complete["summary"]["review_ready_stock_count"], 1)
        self.assertTrue(complete["ledger_summary"]["ready_for_p0_split"])
        markdown = ledger.render_markdown(complete)
        self.assertIn("P0 公开检索证据台账质量审查", markdown)
        self.assertIn("可复核", markdown)

        contaminated = [dict(row) for row in tasks]
        contaminated[0].update(
            {
                "observed_at": "2026-05-31 10:00",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "source": "https://example.com/post-close",
                "excerpt": "首日上涨50%，一手中签率20%。",
            }
        )
        rejected = ledger.build_payload(contaminated)
        self.assertEqual(rejected["summary"]["evidence_contaminated_row_count"], 1)

    def test_p0_research_ledger_marks_attempted_unavailable_gap_without_accepting_postclose_notes(self):
        queries = load_script("prepare_p0_research_queries.py")
        ledger = load_script("normalize_p0_research_ledger.py")
        payload = {
            "primary_year": 2026,
            "status": "needs_p0_or_review",
            "p0_backlog": [
                {
                    "stock": "资料缺口",
                    "code": "01111.HK",
                    "score": "82",
                    "open_domains": ["乙组执行验证", "建议申购执行风险"],
                    "missing_fields": ["pending_input"],
                }
            ],
        }
        tasks = queries.build_tasks(payload)["tasks"]
        attempted = [dict(row) for row in tasks]
        attempted[0].update(
            {
                "search_attempted_at": "2026-06-22 10:00",
                "search_source": "HKEX、AASTOCKS、公开券商页面",
                "unavailable_reason": "未找到公开保存的申购截止前孖展额度记录",
                "search_note": "检索公开页面后，仅找到申购前孖展超购和预计最终超购情景，未找到可核验配售率情景，未填入上市后结果。",
            }
        )
        reviewed = ledger.build_payload(attempted)
        self.assertEqual(reviewed["summary"]["attempted_data_gap_stock_count"], 1)
        self.assertEqual(reviewed["summary"]["review_ready_stock_count"], 0)
        self.assertTrue(reviewed["ledger_summary"]["ready_for_p0_split"])
        stock = reviewed["groups"][0]["stocks"][0]
        self.assertEqual(stock["research_status"], "已尝试缺口")
        self.assertNotIn("记录时间缺失", ledger.render_markdown(reviewed))

        contaminated = [dict(row) for row in attempted]
        contaminated[0]["search_note"] = "只找到首日上涨和一手中签率资料。"
        rejected = ledger.build_payload(contaminated)
        self.assertEqual(rejected["summary"]["attempted_data_gap_stock_count"], 0)
        self.assertEqual(rejected["summary"]["evidence_contaminated_stock_count"], 1)

    def test_preclose_first_day_scenario_is_not_treated_as_post_close_leakage(self):
        margin_history = load_script("normalize_margin_history.py")
        scenario = margin_history.evidence_contamination_review(
            {
                "excerpt": "2026-05-31 10:00 申购热度高，情景首日涨幅20%，情景配售率0.8%。",
                "source": "https://example.com/preclose-scenario",
            }
        )
        self.assertTrue(scenario["evidence_eligible"])
        preclose_heat = margin_history.evidence_contamination_review(
            {
                "excerpt": "截至上午11时48分，孖展资金约3042亿，约2764倍超购，预计最终约5000倍。",
                "source": "https://example.com/preclose-margin",
            }
        )
        self.assertTrue(preclose_heat["evidence_eligible"])
        projected_final = margin_history.evidence_contamination_review(
            {
                "excerpt": "申购前情景讨论：若孖展继续加速，预计最终超购可能接近5000倍。",
                "source": "https://example.com/preclose-scenario",
            }
        )
        self.assertTrue(projected_final["evidence_eligible"])
        preclose_grey_forecast = margin_history.evidence_contamination_review(
            {
                "excerpt": "申购前情景预测：暗盤開盤預計即有8%-12%的漲幅，首日收盤預期約+17.9%。",
                "source": "https://example.com/preclose-grey-forecast",
            }
        )
        self.assertTrue(preclose_grey_forecast["evidence_eligible"])
        merged_preclose_context = margin_history.evidence_contamination_review(
            {
                "excerpt": "截至融资截止前，孖展申购额22.2亿港元，超额认购4.2倍；申购前情景预测暗盤开盘8%-12%，首日收盘预期+17.9%。",
                "source": "https://example.com/preclose-merged",
            }
        )
        self.assertTrue(merged_preclose_context["evidence_eligible"])
        subscription_first_day_margin = margin_history.evidence_contamination_review(
            {
                "excerpt": "截至2026年5月20日傍晚，招股首日孖展认购约21亿港元，公开发售集资约1.38亿，超购约14.2倍。",
                "quota_status": "首日已有多券商孖展，额度先到先得。",
                "source": "https://example.com/subscription-first-day-margin",
            }
        )
        self.assertTrue(subscription_first_day_margin["evidence_eligible"])
        actual = margin_history.evidence_contamination_review(
            {
                "excerpt": "首日上涨50%，一手中签率20%，暗盘表现强。",
                "source": "https://example.com/post-close-review",
            }
        )
        self.assertFalse(actual["evidence_eligible"])
        traditional_actual = margin_history.evidence_contamination_review(
            {
                "excerpt": "暗盤表現強，香港公開發售獲79.54倍超額認購，一手中籤率18%。",
                "source": "https://example.com/post-close-review-tc",
            }
        )
        self.assertFalse(traditional_actual["evidence_eligible"])
        guardrail_note = margin_history.evidence_contamination_review(
            {
                "search_note": "最终认购倍数和分配结果只作复盘标签；本行仅填入招股期内已发布的预测型涨幅证据。",
            }
        )
        self.assertTrue(guardrail_note["evidence_eligible"])
        negative_guardrail_note = margin_history.evidence_contamination_review(
            {
                "demand_validation": "这是融资截止前的预测证据，不是上市表现。",
            }
        )
        self.assertTrue(negative_guardrail_note["evidence_eligible"])
        unavailable_guardrail_note = margin_history.evidence_contamination_review(
            {
                "unavailable_reason": "公开可访问讨论多为上市后或最终超购结果复述，无法作为申购前舆情主证据。",
                "search_note": "已找到上市后或招股结束后讨论；只作复盘线索，不用于申购前模型。",
            }
        )
        self.assertTrue(unavailable_guardrail_note["evidence_eligible"])
        numeric_guardrail_note = margin_history.evidence_contamination_review(
            {
                "search_note": "一手中签率20%只作复盘标签。",
            }
        )
        self.assertFalse(numeric_guardrail_note["evidence_eligible"])
        final_result = margin_history.evidence_contamination_review(
            {
                "excerpt": "香港公开发售获3559.68倍超额认购，一手中签率20%。",
                "source": "https://example.com/allotment-result",
            }
        )
        self.assertFalse(final_result["evidence_eligible"])
        final_oversub_only = margin_history.evidence_contamination_review(
            {
                "excerpt": "最终超购5000倍。",
                "source": "https://example.com/final-oversubscription",
            }
        )
        self.assertFalse(final_oversub_only["evidence_eligible"])

    def test_merge_p0_research_ledger_fills_consolidated_without_leakage(self):
        queries = load_script("prepare_p0_research_queries.py")
        merger = load_script("merge_p0_research_ledger.py")
        payload = {
            "primary_year": 2026,
            "status": "needs_p0_or_review",
            "p0_backlog": [
                {
                    "stock": "高分乙组",
                    "code": "01111.HK",
                    "score": "82",
                    "open_domains": ["乙组执行验证", "建议申购执行风险"],
                    "missing_fields": ["pending_input", "scenario_allotment_rate_pct"],
                },
                {
                    "stock": "污染样本",
                    "code": "02222.HK",
                    "score": "80",
                    "open_domains": ["乙组执行验证"],
                    "missing_fields": ["pending_input"],
                },
            ],
        }
        tasks = queries.build_tasks(payload)["tasks"]
        clean_row = next(row for row in tasks if row["stock"] == "高分乙组")
        clean_row.update(
            {
                "observed_at": "2026-05-31 10:00",
                "source_published_at": "2026-05-31 10:05",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "80",
                "margin_amount_hkd": "1200000000",
                "quota_status": "额度紧张",
                "financing_rate_pct": "2.5",
                "source": "https://example.com/preclose-margin",
                "excerpt": "2026-05-31 10:00 富途孖展认购额12亿，约80倍，额度紧张。",
            }
        )
        contaminated_row = next(row for row in tasks if row["stock"] == "污染样本")
        contaminated_row.update(
            {
                "observed_at": "2026-05-31 10:00",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "source": "https://example.com/post-close",
                "excerpt": "首日上涨50%，一手中签率20%。",
            }
        )
        consolidated = [
            {
                "code": "01111.HK",
                "stock": "高分乙组",
                "domains": "乙组执行验证、建议申购执行风险",
                "domain_count": "2",
                "score": "82",
                "source": "manual-source",
            },
            {
                "code": "02222.HK",
                "stock": "污染样本",
                "domains": "乙组执行验证",
                "domain_count": "1",
                "score": "80",
            },
        ]
        result = merger.merge_rows(consolidated, tasks)
        self.assertEqual(result["summary"]["eligible_row_count"], 1)
        self.assertEqual(result["summary"]["evidence_contaminated_row_count"], 1)
        self.assertEqual(result["summary"]["merged_stock_count"], 1)
        merged = result["rows"][0]
        self.assertEqual(merged["source"], "manual-source")
        self.assertEqual(merged["source_published_at"], "2026-05-31 10:05")
        self.assertEqual(merged["preclose_confirmed"], "是")
        self.assertEqual(merged["margin_multiple"], "80")
        self.assertIn("富途孖展认购额12亿", merged["excerpt"])
        self.assertIn("P0公开检索台账合并", merged["collection_note"])
        polluted = result["rows"][1]
        self.assertNotIn("首日", polluted.get("excerpt", ""))
        csv_text = merger.render_csv(result["rows"])
        self.assertIn("高分乙组", csv_text)
        self.assertNotIn("一手中签率", csv_text)

    def test_merge_p0_research_ledger_preserves_attempted_unavailable_gap(self):
        queries = load_script("prepare_p0_research_queries.py")
        merger = load_script("merge_p0_research_ledger.py")
        payload = {
            "primary_year": 2026,
            "status": "needs_p0_or_review",
            "p0_backlog": [
                {
                    "stock": "资料缺口",
                    "code": "01111.HK",
                    "score": "82",
                    "open_domains": ["乙组执行验证"],
                    "missing_fields": ["pending_input"],
                }
            ],
        }
        tasks = queries.build_tasks(payload)["tasks"]
        tasks[0].update(
            {
                "search_attempted_at": "2026-06-22 10:00",
                "search_source": "HKEX、AASTOCKS、公开券商页面",
                "unavailable_reason": "未找到公开保存的申购截止前孖展额度记录",
                "search_note": "公开检索未找到融资截止前孖展数据。",
            }
        )
        result = merger.merge_rows(
            [{"code": "01111.HK", "stock": "资料缺口", "domains": "乙组执行验证", "domain_count": "1", "score": "82"}],
            tasks,
        )
        self.assertEqual(result["summary"]["eligible_row_count"], 0)
        self.assertEqual(result["summary"]["attempted_gap_row_count"], 1)
        self.assertEqual(result["summary"]["merged_stock_count"], 1)
        self.assertEqual(result["rows"][0]["unavailable_reason"], "未找到公开保存的申购截止前孖展额度记录")
        self.assertIn("已尝试缺口", result["rows"][0]["collection_note"])

    def test_merge_p0_research_ledger_counts_blank_rows_separately(self):
        queries = load_script("prepare_p0_research_queries.py")
        merger = load_script("merge_p0_research_ledger.py")
        payload = {
            "primary_year": 2026,
            "status": "needs_p0_or_review",
            "p0_backlog": [
                {
                    "stock": "高分乙组",
                    "code": "01111.HK",
                    "score": "82",
                    "open_domains": ["乙组执行验证"],
                    "missing_fields": ["pending_input"],
                }
            ],
        }
        tasks = queries.build_tasks(payload)["tasks"]
        consolidated = [
            {
                "code": "01111.HK",
                "stock": "高分乙组",
                "domains": "乙组执行验证",
                "domain_count": "1",
                "score": "82",
            }
        ]
        result = merger.merge_rows(consolidated, tasks)
        self.assertEqual(result["summary"]["blank_row_count"], len(tasks))
        self.assertEqual(result["summary"]["timing_invalid_row_count"], 0)
        self.assertEqual(result["summary"]["eligible_row_count"], 0)
        markdown = merger.render_markdown(result)
        self.assertIn(f"空白：{len(tasks)}", markdown)
        self.assertIn("时间无效：0", markdown)

    def test_run_p0_evidence_pipeline_writes_split_files_and_gate(self):
        pack = load_script("prepare_p0_evidence_pack.py")
        queries = load_script("prepare_p0_research_queries.py")
        pipeline = load_script("run_p0_evidence_pipeline.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "高分乙组",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ],
        }
        pack_payload = pack.build_payload(payload, backtest_json="/tmp/backtest-2026.json")
        expert_ready = {
            "primary_year": 2026,
            "status": "needs_p0_or_review",
            "p0_backlog": [
                {
                    "stock": "高分乙组",
                    "code": "01111.HK",
                    "score": "82",
                    "open_domains": ["乙组执行验证", "建议申购执行风险"],
                    "missing_fields": ["pending_input"],
                }
            ],
        }
        tasks = queries.build_tasks(expert_ready)["tasks"]
        tasks[0].update(
            {
                "observed_at": "2026-05-31 10:00",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "80",
                "margin_amount_hkd": "1200000000",
                "quota_status": "额度紧张",
                "financing_rate_pct": "2.5",
                "fees_hkd": "100",
                "financing_days": "6",
                "source": "https://example.com/preclose-margin",
                "excerpt": "2026-05-31 10:00 富途孖展认购额12亿，约80倍，额度紧张。",
            }
        )
        tasks[4].update(
            {
                "observed_at": "2026-05-31 10:00",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "scenario_first_day_pct": "20",
                "scenario_allotment_rate_pct": "0.8",
                "max_credible_allotment_rate_pct": "1.2",
                "source": "https://example.com/preclose-scenario",
                "excerpt": "2026-05-31 10:00 申购热度高，情景首日涨幅20%，情景配售率0.8%。",
            }
        )
        tasks[5].update(
            {
                "observed_at": "2026-05-31 10:00",
                "preclose_confirmed": "是",
                "broker_cutoff_at": "2026-06-01 12:00",
                "prospectus_url": "https://example.com/prospectus.pdf",
                "valuation_note": "估值较同业折让",
                "source": "https://example.com/prospectus.pdf",
                "excerpt": "招股书显示估值较同业折让，基石禁售明确。",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            consolidated_path = tmpdir_path / "p0-consolidated.csv"
            ledger_path = tmpdir_path / "ledger.csv"
            backtest_path = tmpdir_path / "backtest.json"
            stability_path = tmpdir_path / "stability.json"
            output_dir = tmpdir_path / "out"
            consolidated_path.write_text(pack.render_consolidated_csv(pack_payload["consolidated_rows"]), encoding="utf-8")
            ledger_path.write_text(queries.render_csv(tasks), encoding="utf-8")
            backtest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            stability_path.write_text(
                json.dumps(
                    {
                        "primary_year": 2026,
                        "summary": {"errors": 0, "warnings": 0, "verdict": "通过。"},
                        "findings": [
                            {
                                "code": "current_strategy_not_worse_than_legacy",
                                "severity": "info",
                                "message": "当前策略在主评估年份未弱于原策略。",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = pipeline.run_pipeline(
                consolidated_path=str(consolidated_path),
                ledger_path=str(ledger_path),
                output_dir=str(output_dir),
                backtest_json=str(backtest_path),
                stability_json=str(stability_path),
                primary_year=2026,
            )
            merged_exists = Path(result["paths"]["merged_consolidated"]).exists()
            margin_split_exists = Path(result["paths"]["split_paths"]["margin_history"]).exists()
            expert_json = json.loads(Path(result["paths"]["expert_readiness_json"]).read_text(encoding="utf-8"))
            expert_command = expert_json["commands"]["expert_readiness_json"]
        self.assertGreater(result["merge_summary"]["merged_stock_count"], 0)
        self.assertTrue(merged_exists)
        self.assertTrue(margin_split_exists)
        self.assertEqual(result["expert_status"], "expert_ready")
        self.assertEqual(result["expert_summary"]["p0_open_stock_mentions"], 0)
        self.assertIn(f"--p0-readiness-json margin_history={result['paths']['split_paths']['margin_history']}", expert_command)
        self.assertIn(f"--p0-readiness-json execution_risk={result['paths']['split_paths']['execution_risk']}", expert_command)
        self.assertIn(f"--stability-json {stability_path}", expert_command)
        markdown = pipeline.render_markdown(result)
        self.assertIn("P0 证据闭环流水线", markdown)
        self.assertIn("专家闸门", markdown)

    def test_run_p0_evidence_pipeline_accepts_only_attempted_data_gaps(self):
        pack = load_script("prepare_p0_evidence_pack.py")
        queries = load_script("prepare_p0_research_queries.py")
        pipeline = load_script("run_p0_evidence_pipeline.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "资料缺口",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ],
        }
        pack_payload = pack.build_payload(payload, backtest_json="/tmp/backtest-2026.json")
        tasks = queries.build_tasks(
            {
                "primary_year": 2026,
                "status": "needs_p0_or_review",
                "p0_backlog": [
                    {
                        "stock": "资料缺口",
                        "code": "01111.HK",
                        "score": "82",
                        "open_domains": ["乙组执行验证", "建议申购执行风险"],
                        "missing_fields": ["pending_input"],
                    }
                ],
            }
        )["tasks"]
        tasks[0].update(
            {
                "search_attempted_at": "2026-06-22 10:00",
                "search_source": "HKEX、AASTOCKS、公开券商页面",
                "unavailable_reason": "未找到公开保存的申购截止前孖展额度记录",
                "search_note": "公开检索未找到融资截止前孖展数据。",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            consolidated_path = tmpdir_path / "p0-consolidated.csv"
            ledger_path = tmpdir_path / "ledger.csv"
            backtest_path = tmpdir_path / "backtest.json"
            stability_path = tmpdir_path / "stability.json"
            consolidated_path.write_text(pack.render_consolidated_csv(pack_payload["consolidated_rows"]), encoding="utf-8")
            ledger_path.write_text(queries.render_csv(tasks), encoding="utf-8")
            backtest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            stability_path.write_text(
                json.dumps(
                    {
                        "primary_year": 2026,
                        "summary": {"errors": 0, "warnings": 0, "verdict": "通过。"},
                        "findings": [
                            {
                                "code": "current_strategy_not_worse_than_legacy",
                                "severity": "info",
                                "message": "当前策略在主评估年份未弱于原策略。",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            blocked = pipeline.run_pipeline(
                consolidated_path=str(consolidated_path),
                ledger_path=str(ledger_path),
                output_dir=str(tmpdir_path / "blocked"),
                backtest_json=str(backtest_path),
                stability_json=str(stability_path),
                primary_year=2026,
            )
            accepted = pipeline.run_pipeline(
                consolidated_path=str(consolidated_path),
                ledger_path=str(ledger_path),
                output_dir=str(tmpdir_path / "accepted"),
                backtest_json=str(backtest_path),
                stability_json=str(stability_path),
                primary_year=2026,
                accept_p0_data_gaps=True,
            )
        self.assertEqual(blocked["expert_status"], "needs_p0_or_review")
        self.assertGreater(blocked["expert_summary"]["p0_open_stock_mentions"], 0)
        self.assertEqual(accepted["expert_status"], "expert_ready")
        self.assertEqual(accepted["expert_summary"]["p0_open_stock_mentions"], 0)
        self.assertGreaterEqual(accepted["expert_summary"]["p0_accepted_gap_stock_mentions"], 2)

    def test_expert_readiness_audit_blocks_when_p0_evidence_or_stability_warnings_remain(self):
        readiness = load_script("audit_expert_readiness.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "高分乙组",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "first_day_change_pct": 123.0,
                    "oversubscription_rate": 9999.0,
                    "one_lot_success_rate_pct": 1.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": ["估值待核实"],
                        "financing": {"tier": "乙组候选"},
                    },
                },
                {
                    "code": "03333.HK",
                    "name": "临界观察",
                    "industry": "生物科技",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 5_000.0,
                    "first_day_change_pct": 200.0,
                    "oversubscription_rate": 8888.0,
                    "recommendation": {
                        "score": 69,
                        "action": "可选观察",
                        "evidence": ["低入场费"],
                        "risks": [],
                        "financing": {"tier": "现金参与"},
                    },
                },
            ],
        }
        stability = {
            "primary_year": 2026,
            "summary": {"errors": 0, "warnings": 2, "verdict": "通过但需继续补数据/人工审查。"},
            "findings": [
                {
                    "code": "current_strategy_not_worse_than_legacy",
                    "severity": "info",
                    "message": "当前策略在主评估年份未弱于原策略。",
                },
                {
                    "code": "margin_history_coverage_low",
                    "severity": "warning",
                    "message": "乙组候选缺少历史孖展数据。",
                    "recommendation": "运行 prepare_margin_history_template.py --priority-levels P0。",
                },
                {
                    "code": "false_positive_attribution_concentrated",
                    "severity": "warning",
                    "message": "建议申购错判集中。",
                    "recommendation": "运行 prepare_execution_risk_template.py --priority-levels P0。",
                },
            ],
        }
        result = readiness.build_payload(
            payload,
            backtest_json="/tmp/backtest-2026.json",
            primary_year=2026,
            stability_payload=stability,
            cash_hkd=100_000,
            brokers_arg="",
        )
        self.assertEqual(result["status"], "needs_p0_or_review")
        self.assertFalse(result["summary"]["expert_satisfied"])
        self.assertGreater(result["summary"]["p0_unique_stock_count"], 0)
        self.assertFalse(result["summary"]["threshold_tuning_allowed"])
        self.assertGreater(result["summary"]["p0_backlog_stock_count"], 0)
        self.assertEqual(result["p0_backlog"][0]["stock"], "高分乙组")
        self.assertEqual(result["p0_backlog"][0]["action"], "建议申购")
        self.assertEqual(result["p0_backlog"][0]["financing_tier"], "乙组候选")
        self.assertGreaterEqual(result["p0_backlog"][0]["open_domain_count"], 2)
        self.assertIn("乙组执行验证", result["p0_backlog"][0]["open_domains"])
        self.assertIn("observed_at", result["p0_backlog"][0]["missing_fields"])
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("p0_evidence_open", codes)
        self.assertIn("stability_warnings_open", codes)
        self.assertIn("expert_readiness_json", result["commands"])
        self.assertIn("p0_evidence_pipeline", result["commands"])
        self.assertIn("p0_research_next_batch_csv", result["commands"])
        self.assertIn("p0_next_batch_evidence_pipeline", result["commands"])
        self.assertNotIn("--limit", result["commands"]["p0_research_ledger_csv"])
        self.assertIn("--limit 5 --csv > p0-research-queries-next-5-2026.csv", result["commands"]["p0_research_next_batch_csv"])
        self.assertIn("--ledger p0-research-queries-next-5-2026.csv", result["commands"]["p0_next_batch_evidence_pipeline"])
        self.assertIn("--output-dir p0-evidence-run-next-5-2026", result["commands"]["p0_next_batch_evidence_pipeline"])
        markdown = readiness.render_markdown(result)
        self.assertIn("港股打新专家就绪审计", markdown)
        self.assertIn("P0 下一批补证据清单", markdown)
        self.assertIn("高分乙组", markdown)
        self.assertIn("先用合并表拆分 CSV", markdown)
        self.assertIn("prepare_p0_research_queries.py", markdown)
        self.assertIn("P0 下一批台账 CSV", markdown)
        self.assertIn("P0 下一批证据流水线", markdown)
        self.assertIn("--json > expert-readiness-2026.json", markdown)
        self.assertIn("run_p0_evidence_pipeline.py", markdown)
        self.assertIn("P0 backlog 股票", markdown)
        self.assertIn("| 专家满意 | 否 |", markdown)
        self.assertIn("不能宣称没有优化空间", markdown)
        self.assertIn("P0 证据包", markdown)
        self.assertIn("prepare_margin_history_template.py", markdown)
        self.assertNotIn("123.0", markdown)
        self.assertNotIn("9999", markdown)

    def test_expert_readiness_json_command_preserves_runtime_evidence_inputs(self):
        readiness = load_script("audit_expert_readiness.py")
        result = readiness.build_payload(
            {"year": 2026, "records": []},
            backtest_json="/tmp/backtest 2026.json",
            primary_year=2026,
            stability_payload={
                "primary_year": 2026,
                "summary": {"errors": 0, "warnings": 0, "verdict": "通过。"},
                "findings": [],
            },
            report_text="# 2026 回测\n",
            p0_readiness_args=["margin_history=/tmp/港股 P0/margin.csv"],
            accept_p0_data_gaps=True,
            cash_hkd=100_000,
            brokers_arg="富途,辉立",
            min_primary_samples=20,
            stability_json_path="/tmp/stability 2026.json",
            report_path="/tmp/report 2026.md",
            margin_heat_json_paths=["/tmp/孖展 heat.json"],
        )
        command = result["commands"]["expert_readiness_json"]
        self.assertIn("--backtest-json '/tmp/backtest 2026.json'", command)
        self.assertIn("--stability-json '/tmp/stability 2026.json'", command)
        self.assertIn("--report '/tmp/report 2026.md'", command)
        self.assertIn("--margin-heat-json '/tmp/孖展 heat.json'", command)
        self.assertIn("--p0-readiness-json 'margin_history=/tmp/港股 P0/margin.csv'", command)
        self.assertIn("--accept-p0-data-gaps", command)
        self.assertIn("--cash-hkd 100000", command)
        self.assertIn("--brokers '富途,辉立'", command)
        self.assertIn("--min-primary-samples 20", command)
        self.assertTrue(command.endswith("> expert-readiness-2026.json"))
        self.assertIn("--cash-hkd 100000", result["commands"]["p0_evidence_pack"])
        self.assertIn("--brokers '富途,辉立'", result["commands"]["p0_consolidated_csv"])
        self.assertIn("--cash-hkd 100000", result["commands"]["p0_evidence_pipeline"])
        self.assertIn("--brokers '富途,辉立'", result["commands"]["p0_evidence_pipeline"])
        self.assertIn("--cash-hkd 100000", result["commands"]["preclose_leakage"])
        self.assertIn("--min-primary-samples 20", result["commands"]["backtest_stability"])
        self.assertIn("--input '/tmp/report 2026.md'", result["commands"]["report_quality"])

    def test_expert_readiness_audit_allows_forward_test_when_no_open_items(self):
        readiness = load_script("audit_expert_readiness.py")
        stability = {
            "primary_year": 2026,
            "summary": {"errors": 0, "warnings": 0, "verdict": "通过。"},
            "findings": [
                {
                    "code": "current_strategy_not_worse_than_legacy",
                    "severity": "info",
                    "message": "当前策略在主评估年份未弱于原策略。",
                }
            ],
        }
        result = readiness.build_payload(
            {"year": 2026, "records": []},
            backtest_json="/tmp/backtest-2026.json",
            primary_year=2026,
            stability_payload=stability,
        )
        self.assertEqual(result["status"], "expert_ready")
        self.assertTrue(result["summary"]["expert_satisfied"])
        self.assertEqual(result["summary"]["p0_unique_stock_count"], 0)
        self.assertTrue(result["summary"]["threshold_tuning_allowed"])
        markdown = readiness.render_markdown(result)
        self.assertIn("可进入前向测试", markdown)
        self.assertIn("| 专家满意 | 是 |", markdown)

    def test_expert_readiness_audit_closes_p0_after_review_ready_payloads(self):
        readiness = load_script("audit_expert_readiness.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "高分乙组",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ],
        }
        stability = {
            "primary_year": 2026,
            "summary": {"errors": 0, "warnings": 0, "verdict": "通过。"},
            "findings": [
                {
                    "code": "current_strategy_not_worse_than_legacy",
                    "severity": "info",
                    "message": "当前策略在主评估年份未弱于原策略。",
                }
            ],
        }
        margin_ready = {
            "stocks": [
                {
                    "stock_name": "高分乙组",
                    "code": "01111",
                    "summary": {
                        "timing_valid_row_count": 1,
                        "evidence_contaminated_row_count": 0,
                        "execution_gate": "满足",
                    },
                    "history_rows": [
                        {
                            "input_pending": False,
                            "timing_confirmed": True,
                            "evidence_eligible": True,
                        }
                    ],
                }
            ]
        }
        generic_ready = {
            "summary": {
                "review_ready_stock_count": 1,
                "pending_input_stock_count": 0,
                "missing_data_stock_count": 0,
                "timing_invalid_stock_count": 0,
                "evidence_contaminated_stock_count": 0,
            }
        }
        result = readiness.build_payload(
            payload,
            backtest_json="/tmp/backtest-2026.json",
            primary_year=2026,
            stability_payload=stability,
            p0_readiness_payloads={
                "margin_history": margin_ready,
                "execution_risk": generic_ready,
            },
        )
        self.assertEqual(result["summary"]["p0_open_stock_mentions"], 0)
        self.assertGreaterEqual(result["summary"]["p0_review_ready_stock_mentions"], 2)
        self.assertEqual(result["status"], "expert_ready")
        markdown = readiness.render_markdown(result)
        self.assertIn("| 专家满意 | 是 |", markdown)
        self.assertIn("| 乙组执行验证 | 1 | 0 | 1 | 0 | 已闭环 |", markdown)

    def test_expert_readiness_audit_requires_explicit_gap_acceptance(self):
        readiness = load_script("audit_expert_readiness.py")
        closure = readiness.p0_closure_for_domain(
            "execution_risk",
            expected_count=1,
            readiness_payload={
                "summary": {
                    "review_ready_stock_count": 0,
                    "pending_input_stock_count": 0,
                    "missing_data_stock_count": 1,
                    "timing_invalid_stock_count": 0,
                    "evidence_contaminated_stock_count": 0,
                }
            },
            accept_data_gaps=False,
        )
        self.assertEqual(closure["open_stock_count"], 1)
        self.assertEqual(closure["accepted_gap_stock_count"], 0)
        accepted = readiness.p0_closure_for_domain(
            "execution_risk",
            expected_count=1,
            readiness_payload={
                "summary": {
                    "review_ready_stock_count": 0,
                    "pending_input_stock_count": 0,
                    "missing_data_stock_count": 1,
                    "timing_invalid_stock_count": 0,
                    "evidence_contaminated_stock_count": 0,
                    "attempted_data_gap_stock_count": 0,
                }
            },
            accept_data_gaps=True,
        )
        self.assertEqual(accepted["open_stock_count"], 1)
        self.assertEqual(accepted["accepted_gap_stock_count"], 0)
        attempted = readiness.p0_closure_for_domain(
            "execution_risk",
            expected_count=1,
            readiness_payload={
                "summary": {
                    "review_ready_stock_count": 0,
                    "pending_input_stock_count": 0,
                    "missing_data_stock_count": 0,
                    "timing_invalid_stock_count": 0,
                    "evidence_contaminated_stock_count": 0,
                    "attempted_data_gap_stock_count": 1,
                }
            },
            accept_data_gaps=True,
        )
        self.assertEqual(attempted["open_stock_count"], 0)
        self.assertEqual(attempted["accepted_gap_stock_count"], 1)
        pending = readiness.p0_closure_for_domain(
            "execution_risk",
            expected_count=1,
            readiness_payload={
                "summary": {
                    "review_ready_stock_count": 0,
                    "pending_input_stock_count": 1,
                    "missing_data_stock_count": 0,
                    "timing_invalid_stock_count": 0,
                    "evidence_contaminated_stock_count": 0,
                }
            },
            accept_data_gaps=True,
        )
        self.assertEqual(pending["open_stock_count"], 1)
        self.assertEqual(pending["accepted_gap_stock_count"], 0)

    def test_backtest_next_action_plan_allows_forward_test_only_without_blockers(self):
        planner = load_script("plan_backtest_next_actions.py")
        payload = planner.build_payload(
            {
                "primary_year": 2026,
                "summary": {"verdict": "通过"},
                "findings": [
                    {
                        "code": "current_strategy_not_worse_than_legacy",
                        "severity": "info",
                        "message": "当前策略在主评估年份未弱于原策略。",
                    }
                ],
            },
            backtest_json="/tmp/backtest-2026.json",
            backtest_report="/tmp/backtest-2026.md",
        )
        self.assertEqual(payload["action_count"], 0)
        self.assertEqual(payload["iteration_gate"]["status"], "可进入下一轮前向测试")
        self.assertTrue(payload["iteration_gate"]["threshold_tuning_allowed"])
        markdown = planner.render_markdown(payload)
        self.assertIn("允许继续机械调阈值：是", markdown)

    def test_backtest_next_action_plan_routes_score_band_efficiency_gap_to_execution_review(self):
        planner = load_script("plan_backtest_next_actions.py")
        payload = planner.build_payload(
            {
                "primary_year": 2026,
                "summary": {"verdict": "通过但需人工复核"},
                "findings": [
                    {
                        "code": "score_band_financing_efficiency_divergence",
                        "severity": "warning",
                        "message": "高分段首日中位数更强但一手期望中位数更弱。",
                        "evidence": "78+ median_first=+55.00%, median_one_lot=HKD 40",
                    }
                ],
            },
            backtest_json="/tmp/backtest-2026.json",
            backtest_report="/tmp/backtest-2026.md",
        )
        self.assertFalse(payload["iteration_gate"]["threshold_tuning_allowed"])
        self.assertEqual(payload["evidence_workflows"][0]["domain"], "建议申购执行风险")
        self.assertIn("prepare_execution_risk_template.py", payload["actions"][0]["command"])
        markdown = planner.render_markdown(payload)
        self.assertIn("融资/配售效率校准", markdown)
        self.assertIn("允许继续机械调阈值：否", markdown)

    def test_capital_conflict_audit_separates_preclose_and_review_metrics(self):
        audit = load_script("audit_capital_conflicts.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "name": "示例科技",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 3000.0,
                    "first_day_change_pct": 80.0,
                    "one_lot_success_rate_pct": 5.0,
                    "recommendation": {
                        "score": 80,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                },
                {
                    "code": "05678.HK",
                    "name": "样本智能",
                    "closing_date": "2026-06-02",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 2000.0,
                    "first_day_change_pct": -5.0,
                    "one_lot_success_rate_pct": 10.0,
                    "recommendation": {
                        "score": 79,
                        "action": "建议申购",
                        "evidence": ["低入场费"],
                        "risks": ["估值待核实"],
                        "financing": {"tier": "乙组候选"},
                    },
                },
                {
                    "code": "09999.HK",
                    "name": "现金股份",
                    "closing_date": "2026-06-02",
                    "refund_date": "2026-06-04",
                    "entry_fee_hkd": 1500.0,
                    "first_day_change_pct": 20.0,
                    "one_lot_success_rate_pct": 20.0,
                    "recommendation": {
                        "score": 74,
                        "action": "建议申购",
                        "evidence": ["可查招股资料"],
                        "risks": [],
                        "financing": {"tier": "甲组候选"},
                    },
                },
            ],
        }
        result = audit.build_payload(payload, cash_hkd=100_000)
        self.assertEqual(result["summary"]["conflict_group_count"], 1)
        group = result["conflict_groups"][0]
        self.assertEqual(group["stock_count"], 3)
        self.assertEqual(group["preclose_priority"][0]["stock"], "示例科技（01234.HK）")
        self.assertIn("T-1/T-0孖展倍数/金额", group["preclose_priority"][0]["preclose_checklist"])
        self.assertIsNotNone(group["preclose_priority"][0]["review_only"]["expected_one_lot_pnl_hkd"])
        markdown = audit.render_markdown(result)
        self.assertIn("同窗口资金冲突审查", markdown)
        self.assertIn("不得用于当时排期", markdown)
        self.assertIn("首日涨跌、一手期望、最终超购和一手中签率只作为复盘指标", markdown)

    def test_capital_conflict_audit_can_include_observation_candidates(self):
        audit = load_script("audit_capital_conflicts.py")
        payload = {
            "records": [
                {
                    "code": "01234.HK",
                    "name": "示例科技",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-03",
                    "entry_fee_hkd": 3000.0,
                    "recommendation": {
                        "score": 80,
                        "action": "建议申购",
                        "financing": {"tier": "甲组候选"},
                    },
                },
                {
                    "code": "05678.HK",
                    "name": "观察股份",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-03",
                    "entry_fee_hkd": 2000.0,
                    "recommendation": {
                        "score": 66,
                        "action": "可选观察",
                        "financing": {"tier": "现金参与"},
                    },
                },
            ]
        }
        without_observation = audit.build_payload(payload, cash_hkd=10_000, include_observation=False)
        with_observation = audit.build_payload(payload, cash_hkd=10_000, include_observation=True)
        self.assertEqual(without_observation["summary"]["candidate_count"], 1)
        self.assertEqual(with_observation["summary"]["candidate_count"], 2)

    def test_conflict_research_template_outputs_residual_data_collection_fields(self):
        template = load_script("prepare_conflict_research_template.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "name": "乙组科技",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 50_000.0,
                    "first_day_change_pct": 80.0,
                    "one_lot_success_rate_pct": 5.0,
                    "recommendation": {
                        "score": 80,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                },
                {
                    "code": "05678.HK",
                    "name": "甲组智能",
                    "closing_date": "2026-06-02",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 50_000.0,
                    "first_day_change_pct": -5.0,
                    "one_lot_success_rate_pct": 10.0,
                    "recommendation": {
                        "score": 79,
                        "action": "建议申购",
                        "evidence": ["低入场费"],
                        "risks": ["估值待核实"],
                        "financing": {"tier": "甲组候选"},
                    },
                },
            ],
        }
        rows = template.build_rows(
            payload,
            cash_hkd=80_000,
            include_observation=False,
            brokers=["富途"],
        )
        self.assertEqual(len(rows), 2)
        b_row = next(row for row in rows if row["stock"].startswith("乙组科技"))
        self.assertEqual(b_row["conflict_role"], "默认排入")
        self.assertEqual(b_row["collection_priority"], "P0")
        self.assertIn("与P0边际跳过样本窗口重叠", b_row["priority_reasons"])
        self.assertIn("融资截止前孖展热度", b_row["required_checks"])
        self.assertIn("融资效率情景", b_row["required_checks"])
        self.assertIn("估值", b_row["deep_dive_focus"])
        self.assertIn("残余同窗口冲突组", b_row["collection_note"])
        skipped_row = next(row for row in rows if row["stock"].startswith("甲组智能"))
        self.assertEqual(skipped_row["conflict_role"], "边际跳过")
        self.assertEqual(skipped_row["collection_priority"], "P0")
        csv_text = template.render_csv(rows)
        self.assertIn("conflict_role", csv_text)
        self.assertIn("collection_priority", csv_text)
        self.assertIn("priority_reasons", csv_text)
        self.assertIn("broker_cutoff_at", csv_text)
        self.assertIn("scenario_allotment_rate_pct", csv_text)
        markdown = template.render_markdown(rows, year=2026)
        self.assertIn("同窗口残余冲突补采清单", markdown)
        self.assertIn("| P0 |", markdown)
        self.assertIn("禁止", markdown)
        self.assertIn("最终超购", markdown)

    def test_conflict_research_template_prioritizes_p0_schedule_frontier(self):
        template = load_script("prepare_conflict_research_template.py")
        records = []
        for code, name, score in [
            ("01111.HK", "排入科技", 80),
            ("02222.HK", "边际智能", 79),
            ("03333.HK", "普通甲组", 72),
            ("04444.HK", "低分甲组", 70),
        ]:
            records.append(
                {
                    "code": code,
                    "name": name,
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 100_000.0,
                    "first_day_change_pct": 200.0,
                    "one_lot_success_rate_pct": 1.0,
                    "recommendation": {
                        "score": score,
                        "action": "建议申购",
                        "evidence": ["强保荐人"],
                        "risks": [],
                        "financing": {"tier": "甲组候选"},
                    },
                }
            )
        payload = {"year": 2026, "records": records}
        p0_rows = template.build_rows(
            payload,
            cash_hkd=100_000,
            include_observation=False,
            brokers=[""],
            priority_levels={"P0"},
        )
        self.assertEqual([row["stock"] for row in p0_rows], ["排入科技（01111.HK）", "边际智能（02222.HK）"])
        self.assertEqual([row["conflict_role"] for row in p0_rows], ["默认排入", "边际跳过"])
        self.assertTrue(all(row["collection_priority"] == "P0" for row in p0_rows))

        all_rows = template.build_rows(payload, cash_hkd=100_000, include_observation=False, brokers=[""])
        priorities = {row["stock"]: row["collection_priority"] for row in all_rows}
        self.assertEqual(priorities["普通甲组（03333.HK）"], "P1")
        self.assertEqual(priorities["低分甲组（04444.HK）"], "P2")
        csv_text = template.render_csv(p0_rows)
        self.assertNotIn("200.0", csv_text)
        self.assertNotIn("one_lot_success", csv_text)

    def test_conflict_research_input_normalizes_preclose_rows_and_blocks_future_evidence(self):
        normalizer = load_script("normalize_conflict_research_input.py")
        rows = [
            {
                "group_id": "1",
                "stock": "乙组科技",
                "code": "01234.HK",
                "action": "建议申购",
                "financing_tier": "乙组候选",
                "window": "2026-06-01→2026-06-05",
                "broker": "富途",
                "observed_at": "2026-06-01 09:30",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "150",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
                "fees_hkd": "100",
                "financing_days": "5",
                "scenario_first_day_pct": "20",
                "scenario_allotment_rate_pct": "0.8",
                "prospectus_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0601/sample.pdf",
                "source": "富途融资页",
                "excerpt": "富途孖展150倍，额度紧张，年化3.8%。",
            },
            {
                "group_id": "1",
                "stock": "污染科技",
                "code": "05678.HK",
                "action": "建议申购",
                "financing_tier": "乙组候选",
                "broker": "富途",
                "observed_at": "2026-06-01 09:30",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "200",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
                "fees_hkd": "100",
                "financing_days": "5",
                "scenario_first_day_pct": "20",
                "scenario_allotment_rate_pct": "0.8",
                "prospectus_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0601/sample2.pdf",
                "source": "https://www.aastocks.com/sc/stocks/market/ipo/listedipo.aspx",
                "excerpt": "最终超购5000倍，一手中签率2%，首日大涨。",
            },
        ]
        payload = normalizer.normalize_rows(rows)
        self.assertEqual(payload["summary"]["row_count"], 2)
        self.assertEqual(payload["summary"]["eligible_decision_row_count"], 1)
        self.assertEqual(payload["summary"]["evidence_contaminated_row_count"], 1)
        self.assertEqual(payload["summary"]["review_ready_stock_count"], 1)
        self.assertEqual(payload["summary"]["evidence_contaminated_stock_count"], 1)

        stocks = payload["groups"][0]["stocks"]
        clean_stock = next(item for item in stocks if item["stock"] == "乙组科技")
        self.assertEqual(clean_stock["research_status"], "可复核")
        self.assertEqual(clean_stock["missing_fields"], [])
        self.assertTrue(clean_stock["rows"][0]["preclose_confirmed_inferred"])
        polluted_stock = next(item for item in stocks if item["stock"] == "污染科技")
        self.assertEqual(polluted_stock["research_status"], "证据污染")
        self.assertFalse(polluted_stock["rows"][0]["evidence_eligible"])

        self.assertEqual(len(payload["items_by_stock"]), 1)
        heat_summary = payload["items_by_stock"][0]["summary"]
        self.assertEqual(heat_summary["execution_gate"], "满足")
        self.assertIn("额度紧张或截止提前", heat_summary["strong_signals"])
        self.assertNotIn("最终超购", json.dumps(payload["items_by_stock"], ensure_ascii=False))
        markdown = normalizer.render_markdown(payload)
        self.assertIn("补采资料填回质量审查", markdown)
        self.assertIn("可复核股票：1", markdown)
        self.assertIn("证据污染：1", markdown)
        self.assertIn("乙组科技", markdown)
        self.assertIn("污染科技", markdown)
        self.assertIn("只有 `可复核` 股票", markdown)

    def test_conflict_research_input_marks_blank_templates_as_pending_not_timing_invalid(self):
        normalizer = load_script("normalize_conflict_research_input.py")
        rows = [
            {
                "group_id": "execution-risk",
                "stock": "待填科技",
                "code": "01234.HK",
                "action": "建议申购",
                "financing_tier": "乙组候选",
                "score": "79",
                "required_checks": "融资利率/手续费/计息天数、情景配售率/可信上限",
                "broker": "富途",
                "observed_at": "",
                "broker_cutoff_at": "",
                "margin_multiple": "",
                "quota_status": "",
                "financing_rate_pct": "",
                "fees_hkd": "",
                "financing_days": "",
                "scenario_first_day_pct": "",
                "scenario_allotment_rate_pct": "",
                "prospectus_url": "https://www1.hkexnews.hk/sample.pdf",
                "source": "",
                "excerpt": "",
                "collection_note": "模板自动生成，等待填回。",
            }
        ]
        payload = normalizer.normalize_rows(rows)
        stock = payload["groups"][0]["stocks"][0]
        self.assertEqual(stock["research_status"], "待填回")
        self.assertEqual(stock["missing_fields"], ["pending_input"])
        self.assertEqual(payload["summary"]["pending_input_stock_count"], 1)
        self.assertEqual(payload["summary"]["timing_invalid_stock_count"], 0)
        markdown = normalizer.render_markdown(payload)
        self.assertIn("待填回：1", markdown)
        self.assertIn("模板占位", markdown)
        self.assertIn("等待填回，尚未校验时间", markdown)

    def test_conflict_research_input_rejects_after_cutoff_rows(self):
        normalizer = load_script("normalize_conflict_research_input.py")
        rows = [
            {
                "group_id": "2",
                "stock": "时间无效科技",
                "code": "09999.HK",
                "action": "建议申购",
                "financing_tier": "乙组候选",
                "broker": "富途",
                "observed_at": "2026-06-01 13:30",
                "broker_cutoff_at": "2026-06-01 12:00",
                "preclose_confirmed": "是",
                "margin_multiple": "180",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
                "fees_hkd": "100",
                "financing_days": "5",
                "scenario_first_day_pct": "20",
                "scenario_allotment_rate_pct": "0.8",
                "prospectus_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0601/sample3.pdf",
            }
        ]
        payload = normalizer.normalize_rows(rows)
        stock = payload["groups"][0]["stocks"][0]
        self.assertEqual(stock["research_status"], "时间无效")
        self.assertEqual(payload["summary"]["eligible_decision_row_count"], 0)
        self.assertEqual(payload["summary"]["margin_heat_seed_stock_count"], 0)
        self.assertIn("记录时间晚于券商融资截止", stock["rows"][0]["timing_risks"])

    def test_borderline_upgrade_template_outputs_preclose_collection_rows(self):
        template = load_script("prepare_borderline_upgrade_template.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "name": "临界科技",
                    "industry": "生物科技",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 3600.0,
                    "first_day_change_pct": 123.45,
                    "oversubscription_rate": 9999.0,
                    "one_lot_success_rate_pct": 1.23,
                    "documents": {"prospectus_url": "https://www1.hkexnews.hk/sample.pdf"},
                    "recommendation": {
                        "score": 66,
                        "action": "可选观察",
                        "evidence": ["强保荐", "低入场费"],
                        "risks": ["估值待核实"],
                        "financing": {"tier": "现金参与"},
                    },
                },
                {
                    "code": "05678.HK",
                    "name": "低分观察",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "recommendation": {"score": 60, "action": "可选观察", "financing": {"tier": "现金参与"}},
                },
                {
                    "code": "09999.HK",
                    "name": "已建议科技",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "recommendation": {"score": 80, "action": "建议申购", "financing": {"tier": "乙组候选"}},
                },
            ],
        }
        rows = template.build_rows(payload, min_score=65, brokers=["富途"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["stock"], "临界科技")
        self.assertEqual(row["action"], "可选观察")
        self.assertEqual(row["collection_priority"], "P1")
        self.assertIn("65-68观察补采", row["priority_reasons"])
        self.assertIn("融资截止前孖展热度", row["required_checks"])
        self.assertIn("管线/商业化", row["deep_dive_focus"])
        self.assertIn("乙组仍需单独核价", row["upgrade_condition"])

        csv_text = template.render_csv(rows)
        self.assertIn("collection_priority", csv_text)
        self.assertIn("priority_reasons", csv_text)
        self.assertIn("upgrade_condition", csv_text)
        self.assertNotIn("123.45", csv_text)
        self.assertNotIn("9999", csv_text)
        markdown = template.render_markdown(rows, year=2026, min_score=65)
        self.assertIn("临界观察升级补采清单", markdown)
        self.assertIn("| P1 |", markdown)
        self.assertIn("禁止", markdown)
        self.assertIn("最终超购", markdown)

    def test_borderline_upgrade_template_prioritizes_p0_primary_year_candidates(self):
        template = load_script("prepare_borderline_upgrade_template.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01111.HK",
                    "name": "高临界科技",
                    "industry": "新一代信息技术",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 5000.0,
                    "first_day_change_pct": -50.0,
                    "oversubscription_rate": 1.0,
                    "recommendation": {
                        "score": 71,
                        "action": "可选观察",
                        "evidence": ["稀缺/科技行业", "强保荐人", "低入场费"],
                        "financing": {"tier": "现金参与"},
                    },
                },
                {
                    "code": "02222.HK",
                    "name": "中临界医药－Ｂ",
                    "industry": "生物科技- 制药",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 5500.0,
                    "first_day_change_pct": 200.0,
                    "oversubscription_rate": 9999.0,
                    "recommendation": {
                        "score": 69,
                        "action": "可选观察",
                        "evidence": ["B/P不直接跳过：低入场费且有质量信号"],
                        "financing": {"tier": "现金参与"},
                    },
                },
                {
                    "code": "03333.HK",
                    "name": "普通观察",
                    "industry": "包装食品",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 4300.0,
                    "recommendation": {
                        "score": 66,
                        "action": "可选观察",
                        "evidence": ["低入场费"],
                        "financing": {"tier": "现金参与"},
                    },
                },
                {
                    "code": "04444.HK",
                    "name": "低分观察",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "recommendation": {
                        "score": 60,
                        "action": "可选观察",
                        "financing": {"tier": "现金参与"},
                    },
                },
            ],
        }
        rows = template.build_rows(payload, min_score=65, brokers=[""], priority_levels={"P0"})
        self.assertEqual([row["stock"] for row in rows], ["高临界科技", "中临界医药－Ｂ"])
        self.assertTrue(all(row["collection_priority"] == "P0" for row in rows))
        self.assertIn("稀缺/科技/医药或防守题材需验证热度", rows[0]["priority_reasons"])
        self.assertIn("B/P或医药票需确认管线和融资热度", rows[1]["priority_reasons"])

        all_rows = template.build_rows(payload, min_score=65, include_all_observation=True, brokers=[""])
        priorities = {row["stock"]: row["collection_priority"] for row in all_rows}
        self.assertEqual(priorities["普通观察"], "P1")
        self.assertEqual(priorities["低分观察"], "P2")
        csv_text = template.render_csv(rows)
        self.assertNotIn("-50.0", csv_text)
        self.assertNotIn("9999", csv_text)

    def test_borderline_upgrade_template_rows_can_feed_conflict_normalizer(self):
        template = load_script("prepare_borderline_upgrade_template.py")
        normalizer = load_script("normalize_conflict_research_input.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "name": "临界科技",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 3600.0,
                    "documents": {"prospectus_url": "https://www1.hkexnews.hk/sample.pdf"},
                    "recommendation": {
                        "score": 66,
                        "action": "可选观察",
                        "financing": {"tier": "现金参与"},
                    },
                }
            ],
        }
        row = template.build_rows(payload, min_score=65, brokers=["富途"])[0]
        row.update(
            {
                "observed_at": "2026-06-01 09:30",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "150",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
                "fees_hkd": "100",
                "financing_days": "5",
                "scenario_first_day_pct": "20",
                "scenario_allotment_rate_pct": "0.8",
                "source": "富途融资页",
                "excerpt": "富途孖展150倍，额度紧张，年化3.8%。",
            }
        )
        normalized = normalizer.normalize_rows([row])
        stock = normalized["groups"][0]["stocks"][0]
        self.assertEqual(stock["research_status"], "可复核")
        self.assertEqual(stock["missing_fields"], [])
        self.assertEqual(normalized["summary"]["eligible_decision_row_count"], 1)
        self.assertEqual(normalized["summary"]["margin_heat_seed_stock_count"], 1)

    def test_execution_risk_template_outputs_preclose_fields_without_review_leakage(self):
        template = load_script("prepare_execution_risk_template.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "name": "硬科技样本",
                    "industry": "半导体产品及设备",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 10_000.0,
                    "first_day_change_pct": -30.0,
                    "one_lot_success_rate_pct": 100.0,
                    "oversubscription_rate": 1.0,
                    "documents": {"prospectus_url": "https://www1.hkexnews.hk/sample.pdf"},
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "evidence": ["硬科技稀缺", "强保荐"],
                        "risks": ["估值待核实"],
                        "financing": {"tier": "乙组候选"},
                    },
                },
                {
                    "code": "05678.HK",
                    "name": "观察样本",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "recommendation": {"score": 68, "action": "可选观察", "financing": {"tier": "现金参与"}},
                },
            ],
        }
        rows = template.build_rows(payload, include="high-risk", brokers=["富途"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["stock"], "硬科技样本")
        self.assertEqual(row["action"], "建议申购")
        self.assertEqual(row["application_plan_hkd"], 5_500_000.0)
        self.assertEqual(row["collection_priority"], "P0")
        self.assertIn("78+高分段融资效率重点样本", row["priority_reasons"])
        self.assertIn("情景配售率/可信上限", row["required_checks"])
        self.assertIn("硬科技", row["deep_dive_focus"])

        csv_text = template.render_csv(rows)
        self.assertIn("collection_priority", csv_text)
        self.assertIn("priority_reasons", csv_text)
        self.assertIn("scenario_allotment_rate_pct", csv_text)
        self.assertNotIn("-30", csv_text)
        self.assertNotIn("100.0", csv_text)
        self.assertNotIn("oversubscription", csv_text)
        markdown = template.render_markdown(rows, year=2026, include="high-risk")
        self.assertIn("建议申购执行风险补采清单", markdown)
        self.assertIn("禁止", markdown)
        self.assertIn("最终一手中签率", markdown)

    def test_execution_risk_template_prioritizes_p0_score_band_financing_samples(self):
        template = load_script("prepare_execution_risk_template.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "name": "高分乙组",
                    "industry": "半导体",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 5000.0,
                    "recommendation": {"score": 79, "action": "建议申购", "financing": {"tier": "乙组候选"}},
                },
                {
                    "code": "05678.HK",
                    "name": "甲组样本",
                    "industry": "消费",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 5000.0,
                    "recommendation": {"score": 74, "action": "建议申购", "financing": {"tier": "甲组候选"}},
                },
                {
                    "code": "09999.HK",
                    "name": "现金样本",
                    "industry": "消费",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 5000.0,
                    "recommendation": {"score": 72, "action": "建议申购", "financing": {"tier": "现金参与"}},
                },
            ],
        }
        all_rows = template.build_rows(payload, include="all", brokers=[""])
        self.assertEqual([row["stock"] for row in all_rows], ["高分乙组", "甲组样本", "现金样本"])
        self.assertEqual([row["collection_priority"] for row in all_rows], ["P0", "P1", "P1"])
        p0_rows = template.build_rows(payload, include="all", brokers=[""], priority_levels={"P0"})
        self.assertEqual(len(p0_rows), 1)
        self.assertEqual(p0_rows[0]["stock"], "高分乙组")
        self.assertIn("乙组候选需证明可执行", p0_rows[0]["priority_reasons"])
        markdown = template.render_markdown(p0_rows, year=2026, include="all")
        self.assertIn("| P0 | 高分乙组", markdown)
        self.assertIn("优先原因", markdown)

    def test_execution_risk_template_feeds_per_stock_financing_scenarios(self):
        template = load_script("prepare_execution_risk_template.py")
        normalizer = load_script("normalize_conflict_research_input.py")
        audit = load_script("audit_financing_efficiency.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "name": "硬科技样本",
                    "industry": "半导体产品及设备",
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 10_000.0,
                    "recommendation": {
                        "score": 82,
                        "action": "建议申购",
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ],
        }
        row = template.build_rows(payload, include="high-risk", brokers=["富途"])[0]
        row.update(
            {
                "observed_at": "2026-06-01 09:30",
                "broker_cutoff_at": "2026-06-01 12:00",
                "margin_multiple": "150",
                "quota_status": "额度紧张",
                "financing_rate_pct": "20",
                "fees_hkd": "1000",
                "financing_days": "7",
                "scenario_first_day_pct": "10",
                "scenario_allotment_rate_pct": "0.1",
                "max_credible_allotment_rate_pct": "0.2",
                "source": "富途融资页",
                "excerpt": "富途孖展150倍，额度紧张，年化20%。",
            }
        )
        scenario_payload = normalizer.normalize_rows([row])
        result = audit.build_payload(
            payload,
            include="recommended",
            scenario_first_day_pct=80.0,
            scenario_allotment_rate_pct=5.0,
            financing_rate_pct=1.0,
            fees_hkd=0.0,
            scenario_payload=scenario_payload,
            margin_heat_payload=scenario_payload,
        )
        self.assertEqual(result["assumptions"]["scenario_override_count"], 1)
        item = result["items"][0]
        self.assertTrue(item["scenario_override_applied"])
        self.assertEqual(item["scenario_allotment_rate_pct"], 0.1)
        self.assertEqual(item["max_credible_allotment_rate_pct"], 0.2)
        self.assertEqual(item["status"], "不通过")
        self.assertIn("情景期望扣成本不正", item["flags"])

    def test_preclose_leakage_audit_passes_future_field_mutation(self):
        audit = load_script("audit_preclose_leakage.py")
        payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "name": "示例科技",
                    "industry": "半导体产品及设备",
                    "sponsor": "中国国际金融香港证券有限公司",
                    "hk_public_offer_shares_raw": "1000000",
                    "source_urls": {"aastocks_detail": "https://example.invalid/detail"},
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 3000.0,
                    "first_day_change_pct": -50.0,
                    "oversubscription_rate": 1.0,
                    "one_lot_success_rate_pct": 100.0,
                },
                {
                    "code": "05678.HK",
                    "name": "样本智能",
                    "industry": "先进硬件及软件",
                    "sponsor": "中国国际金融香港证券有限公司",
                    "hk_public_offer_shares_raw": "1000000",
                    "source_urls": {"aastocks_detail": "https://example.invalid/detail2"},
                    "closing_date": "2026-06-02",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 4000.0,
                    "first_day_change_pct": 200.0,
                    "oversubscription_rate": 9999.0,
                    "one_lot_success_rate_pct": 0.5,
                },
            ],
        }
        result = audit.audit_payload(payload, cash_hkd=100_000)
        self.assertTrue(result["summary"]["passed"])
        self.assertEqual(result["summary"]["score_changed_count"], 0)
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("preclose_future_field_invariance_ok", codes)
        markdown = audit.render_markdown(result)
        self.assertIn("申购前数据泄露审计", markdown)
        self.assertIn("未发现申购前评分/排期使用最终结果字段", markdown)

    def test_preclose_leakage_audit_flags_future_terms_in_stored_recommendation(self):
        audit = load_script("audit_preclose_leakage.py")
        payload = {
            "records": [
                {
                    "code": "01234.HK",
                    "name": "示例科技",
                    "industry": "半导体产品及设备",
                    "sponsor": "中国国际金融香港证券有限公司",
                    "hk_public_offer_shares_raw": "1000000",
                    "source_urls": {"aastocks_detail": "https://example.invalid/detail"},
                    "closing_date": "2026-06-01",
                    "refund_date": "2026-06-05",
                    "entry_fee_hkd": 3000.0,
                    "recommendation": {
                        "score": 90,
                        "action": "建议申购",
                        "evidence": ["一手中签率低，首日强"],
                        "risks": [],
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ]
        }
        result = audit.audit_payload(payload)
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("stored_recommendation_future_terms", codes)
        self.assertFalse(result["summary"]["passed"])

    def test_aastocks_upcoming_parser(self):
        fetch = load_script("fetch_current_ipos.py")
        html = """
        <table><thead><tr><td>公司名称/代号</td></tr></thead><tbody>
        <tr>
          <td></td>
          <td><a href="/sc/stocks/market/ipo/upcomingipo/company-summary?symbol=01234#info">示例科技</a><br/><span>01234.HK</span></td>
          <td>半导体设备</td>
          <td>7.20</td>
          <td>500</td>
          <td>3,636.31</td>
          <td>2026/06/24</td>
          <td>2026/06/25</td>
          <td>2026/06/26</td>
        </tr>
        </tbody></table>
        """
        records = fetch.parse_aastocks_upcoming(html, "https://www.aastocks.com")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["code"], "01234.HK")
        self.assertEqual(records[0]["name"], "示例科技")
        self.assertEqual(records[0]["entry_fee_hkd"], 3636.31)
        self.assertEqual(records[0]["listing_date"], "2026-06-26")

    def test_aastocks_parser_separates_status_words_from_stock_name(self):
        fetch = load_script("fetch_current_ipos.py")
        html = """
        <table><tbody>
        <tr>
          <td></td>
          <td><a href="/sc/stocks/market/ipo/upcomingipo/company-summary?symbol=06067#info">星源材质今日暗盘</a><br/><span>06067.HK</span></td>
          <td>先进材料</td>
          <td>7.20</td>
          <td>500</td>
          <td>3,636.31</td>
          <td>2026/06/20</td>
          <td>2026/06/22</td>
          <td>2026/06/23</td>
        </tr>
        </tbody></table>
        """
        records = fetch.parse_aastocks_upcoming(html, "https://www.aastocks.com")
        self.assertEqual(records[0]["name"], "星源材质")
        self.assertEqual(records[0]["status"], "今日暗盘")
        self.assertEqual(fetch.clean_stock_name("星源材质今日暗盘 06067.HK"), "星源材质")

    def test_hkex_parser(self):
        fetch = load_script("fetch_current_ipos.py")
        html = """
        <table><tbody><tr>
          <td style="text-align:center;">1234</td>
          <td>示例科技股份有限公司</td>
          <td><a href="https://www1.hkexnews.hk/a.pdf">下载</a></td>
          <td><a href="https://www1.hkexnews.hk/p.pdf">下载</a></td>
          <td>&nbsp;</td>
        </tr></tbody></table>
        """
        records = fetch.parse_hkex_listing_rows(html, "https://www2.hkexnews.hk", "主板")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["code"], "01234.HK")
        self.assertEqual(records[0]["documents"]["prospectus_url"], "https://www1.hkexnews.hk/p.pdf")

    def test_hkex_listing_report_parser_supports_xlsx_links(self):
        report = load_script("fetch_hkex_listing_reports.py")
        html = """
        <div><span>New Listing Report - 2025</span>
        <a href="/-/media/HKEXnews/Homepage/New-Listings/New-Listing-Information/New-Listing-Report/Main/NLR2025_Eng.xlsx">Download</a></div>
        <div><span>New Listing Report - 2025</span>
        <a href="/-/media/HKEXnews/Homepage/New-Listings/New-Listing-Information/New-Listing-Report/GEM/e_newlistings2025.xlsx">Download</a></div>
        """
        links = report.parse_report_links(html)
        self.assertIn(("Main", 2025), links)
        self.assertIn(("GEM", 2025), links)
        self.assertTrue(links[("Main", 2025)].endswith("NLR2025_Eng.xlsx"))

    def test_hkex_main_listing_report_rows(self):
        report = load_script("fetch_hkex_listing_reports.py")
        rows = [
            ["Year 2025"],
            [None, "Stock Code", "Company Name", "Date of Prospectus", "Date of Listing", "Sponsor(s)", "Reporting Accountants", "Valuer(s)", "Funds Raised (HK$)", "IPO Subscription Price (HK$)"],
            [1, "01234", "Example Technology Limited", 45657, 45666, "China International Capital Corporation", "KPMG", "N/A", 123456789, 7.2],
            [None, '"', '"', '"', '"', '"', '"', '"', 100, 7.2],
        ]
        records = report.parse_main_rows(rows, year=2025, source_url="https://www2.hkexnews.hk/report.xlsx")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["code"], "01234.HK")
        self.assertEqual(records[0]["listing_date"], "2025-01-09")
        self.assertEqual(records[0]["sponsor"], "China International Capital Corporation")
        self.assertEqual(records[0]["offer_price_hkd"], 7.2)
        self.assertNotIn("valuer", records[0])

    def test_sentiment_normalization(self):
        sentiment = load_script("normalize_sentiment_input.py")
        result = sentiment.normalize_text(
            "小红书：这只半导体新股热度高，估值合理，值得申。\n"
            "雪球：担心融资贵和破发，估值还是要看招股书。",
            stock_name="示例科技",
            code="01234",
        )
        self.assertEqual(result["summary"]["total_snippets"], 2)
        self.assertIn(result["summary"]["tilt"], {"分歧", "略正面", "略负面", "中性/信息不足"})
        self.assertGreaterEqual(len(result["signals"]["risk_keywords"]), 1)

    def test_margin_heat_normalization(self):
        margin = load_script("normalize_margin_input.py")
        result = margin.normalize_text(
            "富途：示例科技孖展认购 180倍，额度紧张，年化利率 3.8%。\n"
            "辉立：尾日追单明显，融资额度提前截止。",
            stock_name="示例科技",
            code="01234",
        )
        self.assertEqual(result["summary"]["execution_gate"], "满足")
        self.assertIn("多券商热度一致", result["summary"]["strong_signals"])
        self.assertNotIn("融资成本可接受", result["summary"]["strong_signals"])
        self.assertIn("融资成本可接受", result["summary"]["cost_signals"])
        self.assertEqual(result["summary"]["cost_status"], "可接受")
        self.assertGreaterEqual(result["summary"]["independent_heat_signal_count"], 3)
        self.assertIn("多券商一致", result["summary"]["heat_signal_groups"])

    def test_margin_heat_requires_two_heat_signals_not_only_low_cost(self):
        margin = load_script("normalize_margin_input.py")
        result = margin.normalize_text(
            "富途：示例科技孖展认购 180倍，年化利率 3.8%。",
            stock_name="示例科技",
            code="01234",
        )
        self.assertEqual(result["summary"]["execution_gate"], "不满足")
        self.assertEqual(result["summary"]["strong_signal_count"], 1)
        self.assertEqual(result["summary"]["cost_status"], "可接受")
        self.assertIn("融资成本可接受", result["summary"]["cost_signals"])

    def test_margin_heat_parses_bare_rate_with_rate_context(self):
        margin = load_script("normalize_margin_input.py")
        result = margin.normalize_text(
            "富途：示例科技孖展认购 180倍，年化利率 3.8。",
            stock_name="示例科技",
            code="01234",
        )
        self.assertEqual(result["summary"]["min_financing_rate_pct"], 3.8)
        self.assertEqual(result["summary"]["cost_status"], "可接受")
        self.assertIn("融资成本可接受", result["summary"]["cost_signals"])

    def test_margin_heat_does_not_parse_bare_number_without_rate_context(self):
        margin = load_script("normalize_margin_input.py")
        result = margin.normalize_text(
            "富途：示例科技孖展认购 180倍，额度 3.8 亿。",
            stock_name="示例科技",
            code="01234",
        )
        self.assertIsNone(result["summary"]["min_financing_rate_pct"])
        self.assertEqual(result["summary"]["cost_status"], "未提供")

    def test_margin_heat_counts_same_margin_dimension_once(self):
        margin = load_script("normalize_margin_input.py")
        result = margin.normalize_text(
            "富途：示例科技孖展认购 180倍，孖展金额 80亿，年化利率 3.8%。",
            stock_name="示例科技",
            code="01234",
        )
        self.assertEqual(result["summary"]["execution_gate"], "不满足")
        self.assertIn("孖展倍数显著领先", result["summary"]["strong_signals"])
        self.assertIn("孖展金额高", result["summary"]["strong_signals"])
        self.assertEqual(result["summary"]["heat_signal_groups"], ["孖展规模"])
        self.assertEqual(result["summary"]["independent_heat_signal_count"], 1)

    def test_margin_heat_parses_raw_hkd_margin_amount(self):
        margin = load_script("normalize_margin_input.py")
        result = margin.normalize_text(
            "富途：示例科技孖展金额 HKD 8,000,000,000，年化利率 3.8%。",
            stock_name="示例科技",
            code="01234",
        )
        self.assertEqual(result["items"][0]["margin_amount_hkd"], 8_000_000_000.0)
        self.assertIn("孖展金额高", result["summary"]["strong_signals"])
        self.assertEqual(result["summary"]["heat_signal_groups"], ["孖展规模"])

    def test_margin_heat_rejects_weak_or_expensive_financing(self):
        margin = load_script("normalize_margin_input.py")
        result = margin.normalize_text(
            "富途：示例科技孖展认购 5倍，额度很松，融资贵，年化利率 10.5%。",
            stock_name="示例科技",
            code="01234",
        )
        self.assertEqual(result["summary"]["execution_gate"], "不满足")
        self.assertIn("需求偏弱或热度不足", result["summary"]["risk_flags"])
        self.assertIn("融资成本偏高", result["summary"]["risk_flags"])

    def test_margin_gate_backtest_classifies_execution(self):
        gate = load_script("backtest_margin_gate.py")
        backtest_payload = {
            "year": 2026,
            "strong_threshold_pct": 20.0,
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "listing_date": "2026-06-01",
                    "first_day_change_pct": 30.0,
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                },
                {
                    "code": "05678.HK",
                    "canonical_code": "05678",
                    "name": "样本智能",
                    "listing_date": "2026-06-02",
                    "first_day_change_pct": -5.0,
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                },
                {
                    "code": "09999.HK",
                    "canonical_code": "09999",
                    "name": "观察股份",
                    "listing_date": "2026-06-03",
                    "first_day_change_pct": 50.0,
                    "recommendation": {"financing": {"tier": "现金参与"}},
                },
            ],
        }
        heat_payload = gate.normalize_heat_payloads(
            [
                {
                    "stock_name": "示例科技",
                    "code": "01234",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["多券商热度一致", "额度紧张或截止提前"],
                        "cost_signals": ["融资成本可接受"],
                        "cost_status": "可接受",
                        "risk_flags": [],
                    },
                },
                {
                    "stock_name": "观察股份",
                    "code": "09999",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["多券商热度一致", "最后阶段需求加速"],
                        "cost_signals": ["融资成本可接受"],
                        "cost_status": "可接受",
                        "risk_flags": [],
                    },
                },
            ]
        )
        payload = gate.build_payload(backtest_payload=backtest_payload, heat_payload=heat_payload)
        self.assertEqual(payload["summaries"]["乙组闸门满足"]["count"], 1)
        self.assertEqual(payload["summaries"]["乙组缺热度数据"]["count"], 1)
        self.assertEqual(payload["summaries"]["非乙组但闸门满足"]["count"], 1)
        self.assertEqual(payload["b_group_heat_covered_count"], 1)
        self.assertEqual(payload["b_group_missing_heat_count"], 1)
        self.assertAlmostEqual(payload["b_group_heat_coverage"], 0.5)
        self.assertEqual(payload["covered_count"], 1)
        self.assertEqual(payload["missing_count"], 1)
        self.assertAlmostEqual(payload["coverage_rate"], 0.5)
        self.assertEqual(payload["gate_met_count"], 1)
        self.assertIn("热度覆盖不足", payload["coverage_verdict"])
        markdown = gate.render_markdown(payload)
        self.assertIn("## 覆盖率审查", markdown)
        self.assertIn("缺热度数据乙组候选", markdown)
        expert_section = markdown.split("## 专家审查结论", 1)[1]
        self.assertIn("热度覆盖率低于 70%", expert_section)
        self.assertNotIn("已能用历史融资热度数据区分乙组候选和乙组可执行队列", expert_section)

    def test_margin_gate_backtest_rechecks_legacy_heat_payload(self):
        gate = load_script("backtest_margin_gate.py")
        backtest_payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "listing_date": "2026-06-01",
                    "first_day_change_pct": 30.0,
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                }
            ],
        }
        legacy_heat_payload = gate.normalize_heat_payloads(
            [
                {
                    "stock_name": "示例科技",
                    "code": "01234",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["孖展倍数显著领先", "融资成本可接受"],
                        "risk_flags": [],
                    },
                }
            ]
        )
        payload = gate.build_payload(backtest_payload=backtest_payload, heat_payload=legacy_heat_payload)
        self.assertEqual(payload["summaries"]["乙组闸门满足"]["count"], 0)
        self.assertEqual(payload["summaries"]["乙组闸门不满足"]["count"], 1)

    def test_margin_gate_backtest_rejects_duplicate_margin_scale_signals(self):
        gate = load_script("backtest_margin_gate.py")
        backtest_payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "listing_date": "2026-06-01",
                    "first_day_change_pct": 30.0,
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                }
            ],
        }
        heat_payload = gate.normalize_heat_payloads(
            [
                {
                    "stock_name": "示例科技",
                    "code": "01234",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["孖展倍数显著领先", "孖展金额高"],
                        "cost_signals": ["融资成本可接受"],
                        "cost_status": "可接受",
                        "risk_flags": [],
                    },
                }
            ]
        )
        payload = gate.build_payload(backtest_payload=backtest_payload, heat_payload=heat_payload)
        self.assertEqual(payload["summaries"]["乙组闸门满足"]["count"], 0)
        self.assertEqual(payload["summaries"]["乙组闸门不满足"]["count"], 1)

    def test_margin_gate_backtest_excludes_invalid_timing_from_coverage(self):
        gate = load_script("backtest_margin_gate.py")
        backtest_payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "listing_date": "2026-06-01",
                    "first_day_change_pct": 30.0,
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                }
            ],
        }
        heat_payload = gate.normalize_heat_payloads(
            [
                {
                    "stock_name": "示例科技",
                    "code": "01234",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["多券商热度一致", "额度紧张或截止提前"],
                        "cost_signals": ["融资成本可接受"],
                        "cost_status": "可接受",
                        "risk_flags": [],
                        "timing_valid_row_count": 0,
                        "timing_invalid_row_count": 1,
                        "timing_confidence": "未确认",
                    },
                }
            ]
        )
        payload = gate.build_payload(backtest_payload=backtest_payload, heat_payload=heat_payload)
        self.assertEqual(payload["summaries"]["乙组闸门满足"]["count"], 0)
        self.assertEqual(payload["summaries"]["乙组时间无效"]["count"], 1)
        self.assertEqual(payload["b_group_heat_covered_count"], 0)
        self.assertEqual(payload["b_group_invalid_timing_count"], 1)
        self.assertAlmostEqual(payload["b_group_heat_coverage"], 0.0)
        self.assertEqual(payload["covered_count"], 0)
        self.assertEqual(payload["invalid_timing_count"], 1)
        self.assertAlmostEqual(payload["coverage_rate"], 0.0)
        markdown = gate.render_markdown(payload)
        self.assertIn("时间无效乙组候选", markdown)
        self.assertIn("不得计入有效覆盖率", markdown)

    def test_margin_history_template_lists_missing_b_group_candidates(self):
        template = load_script("prepare_margin_history_template.py")
        self.assertEqual(
            template.stock_name({"code": "00100.HK", "name": "MINIMAX-W"}),
            "稀宇科技",
        )
        backtest_payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "listing_date": "2026-06-01",
                    "closing_date": "2026-05-28",
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                },
                {
                    "code": "05678.HK",
                    "canonical_code": "05678",
                    "name": "现金股份",
                    "listing_date": "2026-06-02",
                    "closing_date": "2026-05-29",
                    "recommendation": {"financing": {"tier": "现金参与"}},
                },
            ],
        }
        rows = template.build_rows(backtest_payload=backtest_payload, brokers=["富途", "辉立"])
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["broker"] for row in rows}, {"富途", "辉立"})
        self.assertTrue(all(row["stock_name"] == "示例科技" for row in rows))
        csv_text = template.render_csv(rows)
        self.assertIn("preclose_confirmed", csv_text)
        self.assertIn("source_published_at", csv_text)
        self.assertIn("broker_cutoff_at", csv_text)
        self.assertIn("margin_multiple", csv_text)
        self.assertIn("collection_priority", csv_text)
        markdown = template.render_markdown(rows, year=2026)
        self.assertIn("乙组候选历史孖展补采清单", markdown)
        self.assertIn("source_published_at", markdown)
        self.assertIn("broker_cutoff_at", markdown)
        self.assertIn("优先级", markdown)
        self.assertIn("精确到分钟", markdown)
        self.assertIn("最终超购、一手中签率、暗盘和首日表现不能填作热度依据", markdown)

    def test_margin_history_template_prioritizes_preclose_b_group_collection(self):
        template = load_script("prepare_margin_history_template.py")
        backtest_payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "高分科技",
                    "listing_date": "2026-06-01",
                    "closing_date": "2026-05-28",
                    "entry_fee_hkd": 3_000.0,
                    "first_day_change_pct": -50.0,
                    "oversubscription_rate": 10.0,
                    "one_lot_success_rate_pct": 90.0,
                    "recommendation": {"score": 79, "financing": {"tier": "乙组候选"}},
                },
                {
                    "code": "05678.HK",
                    "canonical_code": "05678",
                    "name": "低分科技",
                    "listing_date": "2026-06-02",
                    "closing_date": "2026-05-29",
                    "entry_fee_hkd": 3000.0,
                    "first_day_change_pct": 200.0,
                    "oversubscription_rate": 5000.0,
                    "one_lot_success_rate_pct": 1.0,
                    "recommendation": {"score": 60, "financing": {"tier": "乙组候选"}},
                },
            ],
        }
        all_rows = template.build_rows(backtest_payload=backtest_payload, brokers=[""])
        self.assertEqual({row["collection_priority"] for row in all_rows}, {"P0", "P2"})
        p0_rows = template.build_rows(
            backtest_payload=backtest_payload,
            brokers=[""],
            priority_levels={"P0"},
        )
        self.assertEqual(len(p0_rows), 1)
        self.assertEqual(p0_rows[0]["stock_name"], "高分科技")
        self.assertLess(p0_rows[0]["entry_fee_hkd"], 4_000)
        self.assertIn("事前高分乙组候选", p0_rows[0]["priority_reasons"])
        csv_text = template.render_csv(p0_rows)
        self.assertNotIn("-50", csv_text)
        self.assertNotIn("5000", csv_text)
        self.assertNotIn("one_lot_success", csv_text)

    def test_margin_history_template_respects_existing_strict_gate(self):
        gate = load_script("backtest_margin_gate.py")
        template = load_script("prepare_margin_history_template.py")
        backtest_payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "listing_date": "2026-06-01",
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                },
                {
                    "code": "05678.HK",
                    "canonical_code": "05678",
                    "name": "样本智能",
                    "listing_date": "2026-06-02",
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                },
            ],
        }
        heat_payload = gate.normalize_heat_payloads(
            [
                {
                    "stock_name": "示例科技",
                    "code": "01234",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["多券商热度一致", "额度紧张或截止提前"],
                        "cost_signals": ["融资成本可接受"],
                        "cost_status": "可接受",
                        "risk_flags": [],
                    },
                },
                {
                    "stock_name": "样本智能",
                    "code": "05678",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["孖展倍数显著领先", "融资成本可接受"],
                        "risk_flags": [],
                    },
                },
            ]
        )
        rows = template.build_rows(
            backtest_payload=backtest_payload,
            heat_payload=heat_payload,
            brokers=[""],
            include="missing-or-not-met",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stock_name"], "样本智能")
        self.assertIn("不满足严格闸门", rows[0]["collection_note"])

    def test_margin_history_template_flags_invalid_timing_records(self):
        gate = load_script("backtest_margin_gate.py")
        template = load_script("prepare_margin_history_template.py")
        backtest_payload = {
            "year": 2026,
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "listing_date": "2026-06-01",
                    "recommendation": {"financing": {"tier": "乙组候选"}},
                }
            ],
        }
        heat_payload = gate.normalize_heat_payloads(
            [
                {
                    "stock_name": "示例科技",
                    "code": "01234",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["多券商热度一致", "额度紧张或截止提前"],
                        "cost_signals": ["融资成本可接受"],
                        "cost_status": "可接受",
                        "risk_flags": [],
                        "timing_valid_row_count": 0,
                        "timing_invalid_row_count": 1,
                    },
                }
            ]
        )
        rows = template.build_rows(
            backtest_payload=backtest_payload,
            heat_payload=heat_payload,
            brokers=[""],
            include="missing-or-not-met",
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("时间证据无效", rows[0]["collection_note"])
        self.assertIn("broker_cutoff_at", rows[0]["collection_note"])

    def test_subscription_return_calculates_expected_pnl_and_financing_cost(self):
        calc = load_script("calculate_subscription_return.py")
        payload = calc.calculate_return_metrics(
            entry_fee_hkd=3000.0,
            first_day_pct=20.0,
            one_lot_success_rate_pct=10.0,
            cash_hkd=550_000.0,
            application_amount_hkd=5_500_000.0,
            financing_rate_pct=3.8,
            financing_days=7,
        )
        self.assertAlmostEqual(payload["returns"]["expected_one_lot_gross_pnl_hkd"], 60.0)
        self.assertAlmostEqual(payload["costs"]["financing_interest_hkd"], 3607.4, places=1)
        self.assertLess(payload["returns"]["expected_one_lot_net_pnl_hkd"], 0)
        self.assertGreater(payload["returns"]["expected_break_even_first_day_pct"], 1000)

    def test_financing_efficiency_audit_flags_negative_scenario_net_pnl(self):
        audit = load_script("audit_financing_efficiency.py")
        self.assertEqual(audit.stock_title({"name": "MINIMAX-W", "code": "00100.HK"}), "稀宇科技（00100.HK）")
        payload = {
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "乙组科技",
                    "entry_fee_hkd": 3000.0,
                    "recommendation": {
                        "action": "建议申购",
                        "financing": {"tier": "乙组候选"},
                    },
                }
            ]
        }
        result = audit.build_payload(
            payload,
            cash_hkd=550_000,
            margin_multiple=10,
            scenario_first_day_pct=20.0,
            scenario_one_lot_success_rate_pct=5.0,
            financing_rate_pct=8.0,
            financing_days=7,
            fees_hkd=100.0,
            include="b-group",
        )
        self.assertEqual(result["summary"]["candidate_count"], 1)
        self.assertEqual(result["summary"]["failed_count"], 1)
        item = result["items"][0]
        self.assertEqual(item["status"], "不通过")
        self.assertIn("情景期望扣成本不正", item["flags"])
        self.assertGreater(item["required_expected_lots_to_break_even"], 10)
        self.assertGreater(item["required_allotment_rate_to_break_even_pct"], 0)
        self.assertIn("不得把最终一手中签率", result["guardrail"])
        markdown = audit.render_markdown(result)
        self.assertIn("港股打新融资资金效率审计", markdown)
        self.assertIn("乙组科技（01234.HK）", markdown)
        self.assertIn("情景期望净额", markdown)
        self.assertIn("打平需获配", markdown)
        self.assertIn("打平配售率", markdown)

        pass_result = audit.build_payload(
            payload,
            cash_hkd=550_000,
            margin_multiple=10,
            scenario_first_day_pct=20.0,
            scenario_one_lot_success_rate_pct=5.0,
            scenario_expected_lots=20.0,
            financing_rate_pct=8.0,
            financing_days=7,
            fees_hkd=100.0,
            include="b-group",
        )
        self.assertEqual(pass_result["items"][0]["status"], "通过")
        self.assertGreater(pass_result["items"][0]["scenario_expected_net_pnl_hkd"], 0)

        rate_result = audit.build_payload(
            payload,
            cash_hkd=550_000,
            margin_multiple=10,
            scenario_first_day_pct=20.0,
            scenario_one_lot_success_rate_pct=5.0,
            scenario_allotment_rate_pct=1.0,
            max_credible_allotment_rate_pct=1.5,
            financing_rate_pct=8.0,
            financing_days=7,
            fees_hkd=100.0,
            include="b-group",
        )
        rate_item = rate_result["items"][0]
        self.assertAlmostEqual(rate_item["application_lots"], 5500000 / 3000)
        self.assertAlmostEqual(rate_item["scenario_expected_lots"], rate_item["application_lots"] * 0.01)
        self.assertEqual(rate_item["scenario_expected_lots_source"], "application_lots_x_allotment_rate")
        self.assertAlmostEqual(rate_item["max_credible_expected_lots"], rate_item["application_lots"] * 0.015)

        tight_result = audit.build_payload(
            payload,
            cash_hkd=550_000,
            margin_multiple=10,
            scenario_first_day_pct=20.0,
            scenario_one_lot_success_rate_pct=5.0,
            scenario_expected_lots=20.0,
            max_credible_expected_lots=5.0,
            financing_rate_pct=8.0,
            financing_days=7,
            fees_hkd=100.0,
            include="b-group",
        )
        self.assertEqual(tight_result["items"][0]["status"], "不通过")
        self.assertTrue(
            any("打平所需获配手数高于可信上限" in flag for flag in tight_result["items"][0]["flags"])
        )

    def test_financing_efficiency_audit_can_scope_to_scenario_template_stocks(self):
        audit = load_script("audit_financing_efficiency.py")
        payload = {
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "建议科技",
                    "entry_fee_hkd": 3000.0,
                    "recommendation": {
                        "action": "建议申购",
                        "financing": {"tier": "乙组候选"},
                    },
                },
                {
                    "code": "05678.HK",
                    "canonical_code": "05678",
                    "name": "观察科技",
                    "entry_fee_hkd": 4000.0,
                    "recommendation": {
                        "action": "可选观察",
                        "financing": {"tier": "现金参与"},
                    },
                },
            ]
        }
        scenario_payload = {
            "groups": [
                {
                    "group_id": "borderline-upgrade",
                    "stocks": [
                        {
                            "stock": "观察科技",
                            "code": "05678",
                            "financing_assumptions": {
                                "financing_rate_pct": 3.8,
                                "financing_days": 7,
                                "scenario_first_day_pct": 20.0,
                                "scenario_allotment_rate_pct": 0.5,
                            },
                        }
                    ],
                }
            ]
        }
        result = audit.build_payload(payload, include="scenario", scenario_payload=scenario_payload)
        self.assertEqual(result["summary"]["candidate_count"], 1)
        self.assertEqual(result["items"][0]["action"], "可选观察")
        self.assertIn("观察科技", result["items"][0]["stock"])

    def test_financing_efficiency_audit_derives_profile_rates_from_margin_heat(self):
        audit = load_script("audit_financing_efficiency.py")
        payload = {
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "强热科技",
                    "entry_fee_hkd": 3000.0,
                    "recommendation": {
                        "action": "建议申购",
                        "financing": {"tier": "乙组候选"},
                    },
                },
                {
                    "code": "05678.HK",
                    "canonical_code": "05678",
                    "name": "半热科技",
                    "entry_fee_hkd": 3000.0,
                    "recommendation": {
                        "action": "建议申购",
                        "financing": {"tier": "乙组候选"},
                    },
                },
            ]
        }
        heat_payload = {
            "items_by_stock": [
                {
                    "stock_name": "强热科技",
                    "code": "01234",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["孖展倍数显著领先", "多券商热度一致", "额度紧张或截止提前"],
                        "heat_signal_groups": ["孖展规模", "多券商一致", "额度紧张"],
                        "cost_signals": ["融资成本可接受"],
                        "cost_status": "可接受",
                        "risk_flags": [],
                        "confidence": "高",
                    },
                },
                {
                    "stock_name": "半热科技",
                    "code": "05678",
                    "summary": {
                        "execution_gate": "不满足",
                        "strong_signals": ["孖展倍数显著领先"],
                        "heat_signal_groups": ["孖展规模"],
                        "cost_signals": ["融资成本可接受"],
                        "cost_status": "可接受",
                        "risk_flags": [],
                    },
                },
            ]
        }
        result = audit.build_payload(
            payload,
            cash_hkd=550_000,
            margin_multiple=10,
            scenario_first_day_pct=20.0,
            financing_rate_pct=3.8,
            financing_days=7,
            include="b-group",
            margin_heat_payload=heat_payload,
            scenario_profile="base",
        )
        items = {item["stock"].split("（", 1)[0]: item for item in result["items"]}
        self.assertEqual(items["强热科技"]["heat_grade"], "强热")
        self.assertEqual(items["强热科技"]["scenario_allotment_rate_source"], "profile:base:hot")
        self.assertAlmostEqual(items["强热科技"]["scenario_allotment_rate_pct"], 0.8)
        self.assertAlmostEqual(items["强热科技"]["max_credible_allotment_rate_pct"], 1.2)
        self.assertEqual(items["强热科技"]["status"], "通过")
        self.assertEqual(items["半热科技"]["heat_grade"], "不完整")
        self.assertEqual(items["半热科技"]["status"], "不通过")
        self.assertTrue(any("融资热度闸门未满足" in flag for flag in items["半热科技"]["flags"]))

        explicit_result = audit.build_payload(
            payload,
            cash_hkd=550_000,
            margin_multiple=10,
            scenario_first_day_pct=20.0,
            scenario_allotment_rate_pct=1.5,
            max_credible_allotment_rate_pct=2.0,
            financing_rate_pct=3.8,
            financing_days=7,
            include="b-group",
            margin_heat_payload=heat_payload,
            scenario_profile="strict",
        )
        explicit_item = next(item for item in explicit_result["items"] if item["stock"].startswith("强热科技"))
        self.assertEqual(explicit_item["scenario_allotment_rate_source"], "explicit_allotment_rate")
        self.assertAlmostEqual(explicit_item["scenario_allotment_rate_pct"], 1.5)
        markdown = audit.render_markdown(result)
        self.assertIn("情景档 base", markdown)
        self.assertIn("profile:base:hot", markdown)

    def test_actual_subscription_input_normalizes_lightweight_text(self):
        actual = load_script("normalize_actual_subscription_input.py")
        payload = actual.normalize_actual_subscription(
            text="科拓股份 02272 申购55万 中签1000股 每手500股 招股价4.5 卖出5.2 融资息300 手续费50",
            cash_hkd=550_000.0,
        )
        self.assertEqual(payload["stock_name"], "科拓股份")
        self.assertEqual(payload["code"], "02272.HK")
        self.assertEqual(payload["actual_subscription"]["applied_amount_hkd"], 550_000.0)
        self.assertEqual(payload["actual_subscription"]["allotted_shares"], 1000)
        self.assertEqual(payload["actual_subscription"]["allotted_lots"], 2)
        self.assertAlmostEqual(payload["returns"]["gross_trading_pnl_hkd"], 700.0)
        self.assertAlmostEqual(payload["returns"]["net_pnl_hkd"], 350.0)
        self.assertAlmostEqual(payload["returns"]["return_on_cash_pct"], 350.0 / 550_000.0 * 100.0)
        markdown = actual.render_markdown(payload)
        self.assertIn("实际申购复盘 - 科拓股份（02272.HK）", markdown)
        self.assertIn("HKD 4.5", markdown)
        self.assertIn("HKD 5.2", markdown)
        self.assertIn("扣成本收益", markdown)

    def test_actual_subscription_input_uses_flags_and_reports_missing_exit(self):
        actual = load_script("normalize_actual_subscription_input.py")
        payload = actual.normalize_actual_subscription(
            stock_name="示例科技",
            code="1234",
            applied_lots=100,
            allotted_lots=1,
            lot_size=500,
            offer_price_hkd=7.2,
        )
        self.assertEqual(payload["actual_subscription"]["applied_amount_hkd"], 360_000.0)
        self.assertEqual(payload["actual_subscription"]["allotted_shares"], 500)
        self.assertIsNone(payload["returns"]["net_pnl_hkd"])
        self.assertIn("sell_or_move", {item["field"] for item in payload["missing"]})

    def test_margin_history_requires_preclose_timing(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "01234",
                "stock_name": "示例科技",
                "broker": "富途",
                "closing_date": "2026-06-24",
                "margin_multiple": "180",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
            }
        ]
        payload = history.normalize_rows(rows)
        summary = payload["stocks"][0]["summary"]
        self.assertEqual(summary["execution_gate"], "不满足")
        self.assertIn("融资截止前时间未确认", summary["risk_flags"])
        self.assertIn("记录时间缺失", summary["risk_flags"])
        self.assertEqual(summary["timing_valid_row_count"], 0)

        confirmed = history.normalize_rows([dict(rows[0], preclose_confirmed="是", observed_at="2026-06-23 15:30")])
        confirmed_summary = confirmed["stocks"][0]["summary"]
        self.assertEqual(confirmed_summary["timing_confidence"], "已确认")
        self.assertEqual(confirmed_summary["execution_gate"], "满足")
        self.assertEqual(confirmed_summary["timing_valid_row_count"], 1)

    def test_margin_history_markdown_distinguishes_pending_invalid_and_contaminated_rows(self):
        history = load_script("normalize_margin_history.py")
        payload = history.normalize_rows(
            [
                {
                    "code": "01234",
                    "stock_name": "待填科技",
                    "broker": "",
                    "closing_date": "2026-06-24",
                },
                {
                    "code": "05678",
                    "stock_name": "晚填科技",
                    "broker": "富途",
                    "observed_at": "2026-06-25 09:30",
                    "closing_date": "2026-06-24",
                    "preclose_confirmed": "是",
                    "margin_multiple": "180",
                    "quota_status": "额度紧张",
                    "financing_rate_pct": "3.8",
                },
                {
                    "code": "09999",
                    "stock_name": "污染科技",
                    "broker": "富途",
                    "observed_at": "2026-06-23 09:30",
                    "broker_cutoff_at": "2026-06-23 16:00",
                    "closing_date": "2026-06-24",
                    "preclose_confirmed": "是",
                    "margin_multiple": "180",
                    "quota_status": "额度紧张",
                    "financing_rate_pct": "3.8",
                    "excerpt": "最终超购5000倍，一手中签率2%。",
                },
                {
                    "code": "01111",
                    "stock_name": "缺口科技",
                    "broker": "富途",
                    "search_attempted_at": "2026-06-22 10:00",
                    "search_source": "HKEX、AASTOCKS、公开券商页面",
                    "unavailable_reason": "未找到公开保存的申购截止前孖展额度记录",
                    "search_note": "公开检索未找到融资截止前孖展数据。",
                },
            ]
        )
        markdown = history.render_markdown(payload)
        self.assertIn("历史孖展填回质量审查", markdown)
        self.assertIn("待填回：1", markdown)
        self.assertIn("已尝试缺口：1", markdown)
        self.assertIn("| 待填科技（01234） | 01234 | 待填回 |", markdown)
        self.assertIn("等待填回，尚未校验时间", markdown)
        self.assertIn("| 晚填科技（05678） | 05678 | 时间无效 |", markdown)
        self.assertIn("记录时间晚于券商/招股截止", markdown)
        self.assertIn("| 污染科技（09999） | 09999 | 证据污染 |", markdown)
        self.assertIn("配售后/上市后结果", markdown)
        self.assertIn("| 缺口科技（01111） | 01111 | 已尝试缺口 |", markdown)
        self.assertNotIn("记录时间缺失", markdown)

        contaminated_gap = history.normalize_rows(
            [
                {
                    "code": "02222",
                    "stock_name": "污染缺口",
                    "search_attempted_at": "2026-06-22 10:00",
                    "search_source": "公开搜索",
                    "unavailable_reason": "只找到配售结果",
                    "search_note": "只找到首日上涨和一手中签率。",
                }
            ]
        )
        self.assertEqual(history.stock_status(contaminated_gap["stocks"][0]), "证据污染")

    def test_margin_history_groups_equivalent_explicit_stock_codes(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "100",
                "stock_name": "稀宇科技",
                "broker": "富途",
                "observed_at": "2026-01-06 09:30",
                "broker_cutoff_at": "2026-01-06 10:00",
                "closing_date": "2026-01-06",
                "preclose_confirmed": "是",
                "margin_amount_hkd": "8000000000",
                "financing_rate_pct": "3.8",
            },
            {
                "code": "00100.HK",
                "stock_name": "MINIMAX-W",
                "broker": "辉立",
                "observed_at": "2026-01-06 09:45",
                "broker_cutoff_at": "2026-01-06 10:00",
                "closing_date": "2026-01-06",
                "preclose_confirmed": "是",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
            },
        ]
        payload = history.normalize_rows(rows)
        self.assertEqual(len(payload["stocks"]), 1)
        stock = payload["stocks"][0]
        self.assertEqual(stock["code"], "00100")
        self.assertEqual(stock["stock_name"], "稀宇科技")
        summary = stock["summary"]
        self.assertIn("富途", summary["brokers"])
        self.assertIn("辉立", summary["brokers"])
        self.assertIn("孖展金额高", summary["strong_signals"])
        self.assertIn("多券商热度一致", summary["strong_signals"])
        self.assertEqual(summary["timing_valid_row_count"], 2)
        self.assertEqual(summary["execution_gate"], "满足")

    def test_margin_history_rejects_post_close_evidence_even_if_marked_preclose(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "01234",
                "stock_name": "示例科技",
                "broker": "富途",
                "observed_at": "2026-06-25 09:30",
                "closing_date": "2026-06-24",
                "preclose_confirmed": "是",
                "margin_multiple": "180",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
            }
        ]
        payload = history.normalize_rows(rows)
        summary = payload["stocks"][0]["summary"]
        self.assertEqual(summary["execution_gate"], "不满足")
        self.assertEqual(summary["timing_valid_row_count"], 0)
        self.assertEqual(summary["timing_invalid_row_count"], 1)
        self.assertIn("记录时间晚于券商/招股截止", summary["risk_flags"])
        history_row = payload["stocks"][0]["history_rows"][0]
        self.assertFalse(history_row["timing_confirmed"])
        self.assertIn("记录时间晚于券商/招股截止", history_row["timing_risks"])

    def test_margin_history_rejects_contaminated_final_result_excerpt(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "01234",
                "stock_name": "示例科技",
                "broker": "富途",
                "observed_at": "2026-06-23 09:30",
                "broker_cutoff_at": "2026-06-23 16:00",
                "closing_date": "2026-06-24",
                "preclose_confirmed": "是",
                "margin_multiple": "180",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
                "excerpt": "最终超购5000倍，一手中签率2%，首日大涨。",
                "source": "https://www.aastocks.com/sc/stocks/market/ipo/listedipo.aspx",
            }
        ]
        payload = history.normalize_rows(rows)
        summary = payload["stocks"][0]["summary"]
        self.assertEqual(summary["execution_gate"], "不满足")
        self.assertEqual(summary["timing_valid_row_count"], 0)
        self.assertEqual(summary["timing_invalid_row_count"], 1)
        self.assertEqual(summary["evidence_contaminated_row_count"], 1)
        self.assertTrue(any("配售后/上市后结果" in risk for risk in summary["risk_flags"]))
        history_row = payload["stocks"][0]["history_rows"][0]
        self.assertTrue(history_row["timing_confirmed"])
        self.assertFalse(history_row["evidence_eligible"])
        self.assertTrue(any("配售后/上市后结果" in risk for risk in history_row["evidence_risks"]))
        self.assertTrue(any("listedipo" in risk for risk in history_row["evidence_risks"]))

    def test_margin_history_rejects_same_day_after_broker_cutoff_time(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "01234",
                "stock_name": "示例科技",
                "broker": "富途",
                "observed_at": "2026-06-24 15:30",
                "broker_cutoff_at": "2026-06-24 10:00",
                "closing_date": "2026-06-24",
                "preclose_confirmed": "是",
                "margin_multiple": "180",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
            }
        ]
        payload = history.normalize_rows(rows)
        summary = payload["stocks"][0]["summary"]
        self.assertEqual(summary["execution_gate"], "不满足")
        self.assertIn("记录时间晚于券商融资截止", summary["risk_flags"])
        history_row = payload["stocks"][0]["history_rows"][0]
        self.assertEqual(history_row["observed_datetime"], "2026-06-24T15:30")
        self.assertEqual(history_row["broker_cutoff_at"], "2026-06-24T10:00")

    def test_margin_history_requires_time_when_broker_cutoff_has_time(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "01234",
                "stock_name": "示例科技",
                "broker": "富途",
                "observed_at": "2026-06-24",
                "broker_cutoff_at": "2026-06-24 10:00",
                "closing_date": "2026-06-24",
                "preclose_confirmed": "是",
                "margin_multiple": "180",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
            }
        ]
        payload = history.normalize_rows(rows)
        summary = payload["stocks"][0]["summary"]
        self.assertEqual(summary["execution_gate"], "不满足")
        self.assertIn("记录时间缺少具体时刻，无法确认早于券商融资截止", summary["risk_flags"])

    def test_margin_history_rejects_source_published_after_broker_cutoff(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "01234",
                "stock_name": "示例科技",
                "broker": "富途",
                "observed_at": "2026-06-24 09:30",
                "source_published_at": "2026-06-24 15:30",
                "broker_cutoff_at": "2026-06-24 10:00",
                "closing_date": "2026-06-24",
                "preclose_confirmed": "是",
                "margin_multiple": "180",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
            }
        ]
        payload = history.normalize_rows(rows)
        summary = payload["stocks"][0]["summary"]
        self.assertEqual(summary["execution_gate"], "不满足")
        self.assertIn("来源发布时间晚于券商融资截止", summary["risk_flags"])
        history_row = payload["stocks"][0]["history_rows"][0]
        self.assertEqual(history_row["source_published_at"], "2026-06-24T15:30")
        self.assertFalse(history_row["timing_confirmed"])

    def test_margin_history_rejects_cutoff_field_later_than_credit_cutoff_excerpt(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "02729",
                "stock_name": "凯乐士科技",
                "broker": "国泰君安",
                "observed_at": "2026-03-19 04:23",
                "source_published_at": "2026-03-19 04:23",
                "broker_cutoff_at": "2026-03-19 12:00",
                "closing_date": "2026-03-19",
                "preclose_confirmed": "是",
                "margin_multiple": "428.05",
                "quota_status": "热门",
                "financing_rate_pct": "0",
                "excerpt": "GTJAI材料显示信贷便利申请认购：2026年3月18日(周三)，中午12时正；大公报2026-03-19 04:23称孖展超购428.05倍。",
            }
        ]
        payload = history.normalize_rows(rows)
        summary = payload["stocks"][0]["summary"]
        self.assertEqual(summary["execution_gate"], "不满足")
        self.assertIn("broker_cutoff_at晚于证据文本中的信贷便利截止", summary["risk_flags"])
        self.assertIn("记录时间晚于证据文本中的信贷便利截止", summary["risk_flags"])
        self.assertIn("来源发布时间晚于证据文本中的信贷便利截止", summary["risk_flags"])
        history_row = payload["stocks"][0]["history_rows"][0]
        self.assertEqual(history_row["contextual_credit_cutoff_at"], "2026-03-18T12:00")
        self.assertFalse(history_row["timing_confirmed"])

    def test_margin_history_assume_preclose_does_not_override_date_contradiction(self):
        history = load_script("normalize_margin_history.py")
        rows = [
            {
                "code": "01234",
                "stock_name": "示例科技",
                "broker": "富途",
                "observed_at": "2026-06-25",
                "closing_date": "2026-06-24",
                "margin_multiple": "180",
                "quota_status": "额度紧张",
                "financing_rate_pct": "3.8",
            }
        ]
        payload = history.normalize_rows(rows, assume_preclose=True)
        summary = payload["stocks"][0]["summary"]
        self.assertEqual(summary["execution_gate"], "不满足")
        self.assertEqual(summary["timing_confidence"], "未确认")
        self.assertIn("记录时间晚于券商/招股截止", summary["risk_flags"])

    def test_report_handles_overlapping_cash_windows(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                    "source_urls": {"aastocks_summary": "https://www.aastocks.com"},
                },
                {
                    "code": "05678.HK",
                    "canonical_code": "05678",
                    "name": "样本智能",
                    "industry": "人工智能软件",
                    "entry_fee_hkd": 3500.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中信证券",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p2.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a2.pdf",
                    },
                    "source_urls": {"aastocks_summary": "https://www.aastocks.com"},
                },
                {
                    "code": "09876.HK",
                    "canonical_code": "09876",
                    "name": "样本芯片",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 4000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "华泰金融",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p3.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a3.pdf",
                    },
                    "source_urls": {"aastocks_summary": "https://www.aastocks.com"},
                },
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
        )
        self.assertIn("建议申购", markdown)
        self.assertIn("数据覆盖：可申购 3/3；已截止/复盘 0/3", markdown)
        self.assertIn("事前推荐区只展示仍可申购的 3 只", markdown)
        self.assertIn("## 默认资金排期建议", markdown)
        self.assertIn("已排入默认资金", markdown)
        self.assertIn("资金冲突待取舍", markdown)
        self.assertIn("现金/甲组预案；乙组待闸门", markdown)
        self.assertIn("默认排期先按现金/甲组预案预留 HKD 27.50 万", markdown)
        self.assertIn("不能重复使用", markdown)
        self.assertIn("## 同窗口取舍复核", markdown)
        self.assertIn("不能只靠基础分数", markdown)
        self.assertIn("招股书深挖", markdown)
        self.assertIn("T-1/T-0 孖展热度", markdown)
        self.assertIn("事前占款效率", markdown)
        self.assertIn("不得使用一手中签率", markdown)
        self.assertNotIn("一手资金效率", markdown)
        self.assertIn("替换默认排期", markdown)
        self.assertIn("至少两个独立需求/额度热度信号且成本可接受", markdown)
        self.assertIn("至少两个独立需求/额度热度信号且成本可接受", markdown)
        self.assertIn("乙组仅列入候选，当前不可直接执行", markdown)
        self.assertIn("## 融资核价清单", markdown)
        self.assertIn("乙组待闸门", markdown)
        self.assertIn("利率和手续费", markdown)
        self.assertIn("未提供或未匹配到舆情摘录", markdown)

    def test_report_keeps_missing_critical_issue_fields_under_observation(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                    "source_urls": {"aastocks_summary": "https://www.aastocks.com"},
                },
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
            market_regime_payload={"market_regime": {"label": "偏热", "sample_size": 20}},
        )
        self.assertIn("## 建议申购\n暂无。", markdown)
        self.assertIn("## 可选观察", markdown)
        self.assertIn("关键发行资料未完整披露", markdown)

    def test_report_lists_borderline_observation_review_checklist(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "临界科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                },
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
        )
        self.assertIn("## 临界观察复核清单", markdown)
        self.assertIn("临界科技（01234.HK）", markdown)
        self.assertIn("评分接近建议阈值", markdown)
        self.assertIn("孖展倍数/金额", markdown)
        self.assertIn("才从观察升级到现金/甲组", markdown)

    def test_report_lists_prospectus_deep_dive_priority_queue(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                },
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
        )
        self.assertIn("## 招股书深挖优先队列", markdown)
        self.assertIn("| P0 | 示例科技（01234.HK） | 建议申购 |", markdown)
        self.assertIn("[HKEX招股书](https://www1.hkexnews.hk/p1.pdf)", markdown)
        self.assertIn("估值/发行市值", markdown)
        self.assertIn("deep_dive_prospectus.py", markdown)

    def test_deep_dive_prospectus_outputs_structured_signals(self):
        deep = load_script("deep_dive_prospectus.py")
        text = (
            "财务资料显示，收入增加，毛利率上升，但公司仍录得净亏损。"
            "风险因素包括客户集中，五大客户占比较高。"
            "基石投资者已同意锁定。所得款项用途包括研发。"
        )
        analysis = deep.analyze_text(text)
        payload = deep.build_payload(
            stock_name="示例科技",
            code="01234",
            source="pasted",
            analysis=analysis,
            notes=[],
            text=text,
        )
        signals = payload["signals"]
        self.assertLess(signals["score_modifier"], 0)
        self.assertTrue(any("收入" in item for item in signals["positive_flags"]))
        self.assertTrue(any("亏损" in item for item in signals["risk_flags"]))
        self.assertTrue(any("客户集中" in item for item in signals["risk_flags"]))

    def test_report_merges_deep_dive_json_and_downgrades_structural_risk(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "深挖科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                },
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
            deep_dive_payload={
                "stock_name": "深挖科技",
                "code": "01234",
                "text_available": True,
                "source": "pasted",
                "signals": {
                    "score_modifier": -9,
                    "confidence": "高",
                    "positive_flags": ["基石投资者质量尚可"],
                    "risk_flags": ["估值偏高", "客户集中", "经营现金流可能承压"],
                    "missing_checks": ["同业估值片段未定位"],
                },
            },
        )
        self.assertIn("数据覆盖：可申购 1/1；已截止/复盘 0/1", markdown)
        self.assertIn("深挖 1/1", markdown)
        self.assertIn("## 建议申购\n暂无。", markdown)
        self.assertIn("## 可选观察", markdown)
        self.assertIn("招股书深挖出现估值、财务或结构性风险", markdown)
        self.assertIn("**招股书深挖补充**", markdown)
        self.assertIn("深挖信号调整：-9 分", markdown)
        self.assertIn("风险点：估值偏高；客户集中", markdown)
        self.assertIn("深挖来源：pasted", markdown)

    def test_report_does_not_allocate_cash_to_closed_subscription(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "已截止科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-18",
                    "listing_date": "2026-06-24",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                },
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
        )
        self.assertIn("不进入新的申购或融资动作", markdown)
        self.assertIn("数据覆盖：可申购 0/1；已截止/复盘 1/1", markdown)
        self.assertIn("事前推荐区只展示仍可申购的 0 只", markdown)
        self.assertIn("已截止/复盘 1 只单列到上市表现复盘/监控", markdown)
        self.assertIn("暂无仍需占用默认现金的新申购安排", markdown)
        self.assertIn("| 已截止科技（01234.HK） | 2026-06-18 至 2026-06-24 | HKD 0 | 不占用默认现金。 |", markdown)
        self.assertIn("## 建议申购\n暂无。", markdown)
        self.assertIn("## 可选观察\n暂无。", markdown)
        self.assertIn("## 暂不参与\n暂无。", markdown)
        pre_review = markdown.split("## 上市表现复盘", 1)[0]
        self.assertNotIn("| 状态 | 已截止", pre_review)
        review_section = markdown.split("## 上市表现复盘", 1)[1]
        self.assertIn("已截止科技（01234.HK）：已进入复盘/监控窗口，不进入事前推荐区", review_section)

    def test_grey_market_status_is_kept_out_of_pre_close_recommendation_buckets(self):
        report = load_script("build_recommendation_report.py")
        audit = load_script("audit_report_quality.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "06067.HK",
                    "canonical_code": "06067",
                    "name": "星源材质今日暗盘",
                    "status": "已截止待上市",
                    "industry": "先进材料",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-18",
                    "listing_date": "2026-06-24",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                },
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
        )
        pre_review = markdown.split("## 上市表现复盘", 1)[0]
        self.assertNotIn("今日暗盘", pre_review)
        self.assertIn("星源材质（06067.HK）：已截止待上市；今日暗盘；已进入复盘/监控窗口", markdown)
        payload = audit.build_payload(markdown, report_type="current")
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertFalse(
            any(item["code"] == "possible_future_data_leakage" for item in payload["findings"]),
            payload["findings"],
        )

    def test_report_merges_listing_review_json_without_changing_subscription_action(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-25",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "复盘科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-18",
                    "listing_date": "2026-06-24",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                },
            ],
        }
        review_payload = {
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "first_day_change_pct": 30.0,
                    "oversubscription_rate": 1500.0,
                    "one_lot_success_rate_pct": 5.0,
                    "entry_fee_hkd": 3000.0,
                }
            ]
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
            review_payload=review_payload,
        )
        self.assertIn("上市复盘匹配 1/1；首日表现 1/1", markdown)
        self.assertIn("不进入新的申购或融资动作", markdown)
        self.assertIn("首日 +30.00%", markdown)
        self.assertIn("公开超购 1,500.0x", markdown)
        self.assertIn("一手中签率 5.00%", markdown)
        self.assertIn("最终强热度", markdown)
        self.assertIn("一手期望毛利 HKD 45", markdown)
        self.assertIn("未列入建议申购但首日强收益", markdown)
        self.assertIn("T-1/T-0 孖展/额度信号应触发升级复核", markdown)
        self.assertIn("升级前仍要看资金效率", markdown)
        self.assertIn("| 复盘科技（01234.HK） | 2026-06-18 至 2026-06-24 | HKD 0 | 不占用默认现金。 |", markdown)

    def test_listing_review_diagnoses_false_positive_with_weak_heat(self):
        report = load_script("build_recommendation_report.py")
        analysis = {
            "title": "破发科技（01234.HK）",
            "category": "建议申购",
            "ipo": {"code": "01234.HK", "entry_fee_hkd": 3000.0},
            "review_record": {
                "code": "01234.HK",
                "first_day_change_pct": -5.0,
                "oversubscription_rate": 80.0,
                "one_lot_success_rate_pct": 30.0,
                "entry_fee_hkd": 3000.0,
            },
        }
        line = report.review_line(analysis)
        self.assertIn("最终弱热度", line)
        self.assertIn("降级乙组或退回现金", line)
        self.assertIn("一手期望不正", line)

    def test_report_uses_margin_heat_gate(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                }
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
            margin_heat_payload={
                "stock_name": "示例科技",
                "code": "01234",
                "summary": {
                    "execution_gate": "满足",
                    "strong_signals": ["孖展倍数显著领先", "多券商热度一致"],
                    "cost_signals": ["融资成本可接受"],
                    "cost_status": "可接受",
                    "risk_flags": [],
                    "min_financing_rate_pct": 3.8,
                },
            },
        )
        self.assertIn("融资热度闸门已满足", markdown)
        self.assertIn("可进入乙组执行核价", markdown)
        self.assertIn("年化 3.80%", markdown)
        self.assertIn("## 融资核价清单", markdown)
        self.assertIn("乙组可执行核价", markdown)
        self.assertIn("仍需核实利率、手续费、额度、截止时间", markdown)

    def test_report_rejects_margin_heat_with_duplicate_scale_only(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                }
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
            margin_heat_payload={
                "stock_name": "示例科技",
                "code": "01234",
                "summary": {
                    "execution_gate": "满足",
                    "strong_signals": ["孖展倍数显著领先", "孖展金额高"],
                    "cost_signals": ["融资成本可接受"],
                    "cost_status": "可接受",
                    "risk_flags": [],
                    "min_financing_rate_pct": 3.8,
                },
            },
        )
        self.assertIn("融资热度闸门未满足", markdown)
        self.assertIn("独立热度信号 1 类：孖展规模", markdown)
        self.assertIn("乙组待闸门", markdown)
        self.assertNotIn("乙组可执行核价", markdown)

    def test_report_renders_financing_lock_timeline_before_cutoff(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-23",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "今日锁单科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-23",
                    "listing_date": "2026-06-26",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                },
                {
                    "code": "05678.HK",
                    "canonical_code": "05678",
                    "name": "明日锁单科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3500.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-27",
                    "sponsor": "中信证券",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p2.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a2.pdf",
                    },
                },
                {
                    "code": "09876.HK",
                    "canonical_code": "09876",
                    "name": "已截止科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 4000.0,
                    "closing_date": "2026-06-20",
                    "listing_date": "2026-06-27",
                    "sponsor": "华泰金融",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p3.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a3.pdf",
                    },
                },
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
        )
        self.assertIn("## 融资锁单时间表", markdown)
        section = markdown.split("## 融资锁单时间表", 1)[1].split("## 默认资金排期建议", 1)[0]
        self.assertIn("T-0/今日截止", section)
        self.assertIn("T-1", section)
        self.assertIn("今天完成孖展倍数/金额", section)
        self.assertIn("热度闸门未满足则退回现金/甲组", section)
        self.assertIn("不要等配售结果或暗盘再决定是否融资", section)
        self.assertIn("最晚 T-1/T-0 决定是否退回甲组/现金", section)
        self.assertNotIn("已截止科技", section)

    def test_report_uses_cold_market_regime_to_block_b_group(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "industry": "半导体设备",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                }
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
            market_regime_payload={
                "market_regime": {
                    "label": "偏冷",
                    "sample_size": 20,
                    "median_first_day_pct": -2.0,
                    "break_even_or_down_rate": 0.45,
                }
            },
        )
        self.assertIn("市场温度：偏冷", markdown)
        self.assertIn("不直接执行乙组融资", markdown)

    def test_report_downgrades_generic_tech_outside_hot_market(self):
        report = load_script("build_recommendation_report.py")
        payload = {
            "as_of_date": "2026-06-21",
            "sources": [],
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例软件",
                    "industry": "应用软件",
                    "entry_fee_hkd": 3000.0,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中金公司",
                    "hk_public_offer_shares_raw": "10000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p1.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a1.pdf",
                    },
                }
            ],
        }
        markdown = report.build_report(
            payload,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
            sentiment=None,
            market_regime_payload={"market_regime": {"label": "中性", "sample_size": 20}},
        )
        self.assertIn("## 建议申购\n暂无。", markdown)
        self.assertIn("非热市下泛软件/泛IT题材不直接建议申购", markdown)

    def test_estimate_market_regime_payload(self):
        estimate = load_script("estimate_market_regime.py")
        self.assertTrue(estimate.parse_args(["--json"]).json)
        records = [
            {
                "listing_date": f"2026-01-{i + 1:02d}",
                "name": f"历史{i}",
                "code": f"0{i:04d}.HK",
                "first_day_change_pct": -8.0,
            }
            for i in range(1, 9)
        ]
        payload = estimate.build_payload(
            as_of=dt.date(2026, 2, 1),
            records=records,
            sources=[],
            window=20,
            min_samples=8,
            strong_threshold_pct=20.0,
        )
        self.assertEqual(payload["market_regime"]["label"], "偏冷")
        self.assertEqual(len(payload["recent_listings"]), 8)

    def test_multi_year_weighted_rows_use_recency_weights(self):
        multi = load_script("backtest_multi_year.py")
        payloads = {
            2026: {
                "summary": {
                    "by_action": {
                        "建议申购": {"count": 10, "positive_rate": 0.9, "strong_rate": 0.5, "avg_first_day_pct": 30, "median_first_day_pct": 20},
                    }
                },
                "legacy_summary": {
                    "by_action": {
                        "建议申购": {"count": 10, "positive_rate": 0.8, "strong_rate": 0.4, "avg_first_day_pct": 20, "median_first_day_pct": 10},
                    }
                },
            },
            2025: {
                "summary": {
                    "by_action": {
                        "建议申购": {"count": 10, "positive_rate": 0.5, "strong_rate": 0.2, "avg_first_day_pct": -10, "median_first_day_pct": -5},
                    }
                },
                "legacy_summary": {
                    "by_action": {
                        "建议申购": {"count": 10, "positive_rate": 0.5, "strong_rate": 0.2, "avg_first_day_pct": -10, "median_first_day_pct": -5},
                    }
                },
            },
        }
        weights = multi.recency_weights([2026, 2025], 0.5)
        self.assertEqual(weights, {2026: 1.0, 2025: 0.5})
        self.assertEqual(multi.parse_input_json(["2026=/tmp/a.json"]), {2026: "/tmp/a.json"})
        rows = multi.weighted_rows(payloads, weights=weights, section="summary", labels=["建议申购"])
        self.assertAlmostEqual(rows["建议申购"]["positive_rate"], (0.9 * 10 + 0.5 * 10 * 0.5) / 15)
        legacy_rows = multi.weighted_rows(payloads, weights=weights, section="legacy_summary", labels=["建议申购"])
        self.assertAlmostEqual(legacy_rows["建议申购"]["avg_first_day_pct"], (20 * 10 + -10 * 10 * 0.5) / 15)

    def test_multi_year_default_decay_prioritizes_current_year(self):
        multi = load_script("backtest_multi_year.py")
        args = multi.parse_args([])
        self.assertEqual(args.decay, 0.15)
        self.assertEqual(multi.recency_weights([2026, 2025, 2024], args.decay), {2026: 1.0, 2025: 0.15, 2024: 0.0225})

    def test_multi_year_report_puts_primary_year_before_weighted_evidence(self):
        multi = load_script("backtest_multi_year.py")
        payload = {
            "generated_at": "2026-06-21T00:00:00",
            "years": [2026, 2025],
            "primary_year": 2026,
            "weights": {2026: 1.0, 2025: 0.15},
            "effective_weights": {2026: 1.0, 2025: 0.15},
            "strong_threshold_pct": 20.0,
            "yearly": [
                {
                    "year": 2026,
                    "sample_count": 10,
                    "apply_count": 5,
                    "apply_positive_rate": 0.9,
                    "apply_strong_rate": 0.6,
                    "apply_avg_first_day_pct": 50.0,
                    "apply_avg_expected_one_lot_pnl_hkd": 150.0,
                    "false_positive_count": 0,
                    "false_negative_count": 0,
                    "b_group_count": 1,
                    "b_group_positive_rate": 1.0,
                    "b_group_strong_rate": 0.5,
                    "b_group_avg_first_day_pct": 30.0,
                    "b_group_avg_expected_one_lot_pnl_hkd": 80.0,
                }
            ],
            "coverage_warnings": [],
            "quality_weight_notes": [],
            "weighted_summary": {
                "建议申购": {"weighted_count": 5.0, "positive_rate": 0.7, "strong_rate": 0.4, "avg_first_day_pct": 35.0, "median_first_day_pct": 20.0, "avg_expected_one_lot_pnl_hkd": 90.0},
                "可选观察": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
                "暂不参与": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
            },
            "weighted_legacy_summary": {
                "建议申购": {"weighted_count": 5.0, "positive_rate": 0.8, "strong_rate": 0.5, "avg_first_day_pct": 40.0, "median_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 120.0},
                "可选观察": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
                "暂不参与": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
            },
            "weighted_financing_summary": {
                "乙组候选": {"weighted_count": 1.0, "positive_rate": 1.0, "strong_rate": 0.5, "avg_first_day_pct": 30.0, "median_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 80.0},
                "甲组候选": {"weighted_count": 4.0, "positive_rate": 0.8, "strong_rate": 0.5, "avg_first_day_pct": 35.0, "median_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 100.0},
                "现金参与": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
                "不融资": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
            },
            "year_payloads": {
                2026: {
                    "summary": {
                        "by_action": {
                            "建议申购": {
                                "count": 5,
                                "avg_first_day_pct": 50.0,
                                "avg_expected_one_lot_pnl_hkd": 150.0,
                            }
                        }
                    },
                    "legacy_summary": {
                        "by_action": {
                            "建议申购": {
                                "count": 5,
                                "avg_first_day_pct": 45.0,
                                "avg_expected_one_lot_pnl_hkd": 120.0,
                            }
                        }
                    },
                }
            },
        }
        markdown = multi.render_markdown(payload)
        expert_section = markdown.split("## 专家审查结论", 1)[1]
        self.assertLess(expert_section.index("2026 单年审查"), expert_section.index("近因加权旁证"))
        self.assertIn("主结论以该年单年回测为准", expert_section)
        self.assertIn("近因加权旁证：当前事前策略的平均首日表现弱于原策略", expert_section)

    def test_multi_year_quality_adjusted_weights_exclude_low_coverage_years(self):
        multi = load_script("backtest_multi_year.py")
        payloads = {
            2026: {"records": [{} for _ in range(10)], "data_quality": {"total": 10, "detail_ok_count": 10, "industry_count": 10}},
            2025: {"records": [{} for _ in range(10)], "data_quality": {"total": 10, "detail_ok_count": 0, "industry_count": 0}},
        }
        weights = {2026: 1.0, 2025: 0.15}
        adjusted, notes = multi.quality_adjusted_weights(payloads, weights)
        self.assertEqual(adjusted[2026], 1.0)
        self.assertEqual(adjusted[2025], 0.0)
        self.assertIn("有效权重设为 0", "；".join(notes))

    def test_multi_year_report_flags_empty_years(self):
        multi = load_script("backtest_multi_year.py")
        payload = {
            "generated_at": "2026-06-21T00:00:00",
            "years": [2026, 2023],
            "weights": {2026: 1.0, 2023: 0.7},
            "effective_weights": {2026: 1.0, 2023: 0.0},
            "strong_threshold_pct": 20.0,
            "yearly": [
                {
                    "year": 2026,
                    "sample_count": 1,
                    "apply_count": 1,
                    "apply_positive_rate": 1.0,
                    "apply_strong_rate": 1.0,
                    "apply_avg_first_day_pct": 30.0,
                    "false_positive_count": 0,
                    "false_negative_count": 0,
                    "b_group_count": 1,
                    "b_group_positive_rate": 1.0,
                    "b_group_strong_rate": 1.0,
                    "b_group_avg_first_day_pct": 30.0,
                },
                {
                    "year": 2023,
                    "sample_count": 0,
                    "apply_count": 0,
                    "apply_positive_rate": None,
                    "apply_strong_rate": None,
                    "apply_avg_first_day_pct": None,
                    "false_positive_count": 0,
                    "false_negative_count": 0,
                    "b_group_count": 0,
                    "b_group_positive_rate": None,
                    "b_group_strong_rate": None,
                    "b_group_avg_first_day_pct": None,
                },
            ],
            "coverage_warnings": ["2023 年未抓到 AASTOCKS 已上市新股样本，可能是公开分页覆盖不足；该年不会影响加权指标。"],
            "weighted_summary": {
                "建议申购": {"weighted_count": 1.0, "positive_rate": 1.0, "strong_rate": 1.0, "avg_first_day_pct": 30.0, "median_first_day_pct": 30.0},
                "可选观察": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None},
                "暂不参与": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None},
            },
            "weighted_legacy_summary": {
                "建议申购": {"weighted_count": 1.0, "positive_rate": 1.0, "strong_rate": 1.0, "avg_first_day_pct": 20.0, "median_first_day_pct": 20.0}
            },
            "weighted_financing_summary": {
                "乙组候选": {"weighted_count": 1.0, "positive_rate": 1.0, "strong_rate": 1.0, "avg_first_day_pct": 30.0, "median_first_day_pct": 30.0},
                "甲组候选": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None},
                "现金参与": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None},
                "不融资": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None},
            },
            "quality_weight_notes": ["2023 年无可用样本，有效权重设为 0。"],
        }
        markdown = multi.render_markdown(payload)
        self.assertIn("主评估年份：2026", markdown)
        self.assertIn("旧年份只作为低权重压力测试", markdown)
        self.assertIn("主结论以单年回测为准", markdown)
        self.assertIn("近因权重：2026=1.00, 2023=0.70", markdown)
        self.assertIn("有效权重：2026=1.00, 2023=0.00", markdown)
        self.assertIn("数据质量权重", markdown)
        self.assertIn("数据覆盖提示", markdown)
        self.assertIn("2023 年未抓到", markdown)

    def test_multi_year_report_flags_cross_cycle_b_group_instability(self):
        multi = load_script("backtest_multi_year.py")
        payload = {
            "generated_at": "2026-06-21T00:00:00",
            "years": [2026, 2025, 2024],
            "primary_year": 2026,
            "weights": {2026: 1.0, 2025: 0.15, 2024: 0.0225},
            "effective_weights": {2026: 1.0, 2025: 0.15, 2024: 0.0225},
            "strong_threshold_pct": 20.0,
            "yearly": [
                {
                    "year": 2026,
                    "sample_count": 69,
                    "apply_count": 41,
                    "apply_positive_rate": 0.875,
                    "apply_strong_rate": 0.60,
                    "apply_avg_first_day_pct": 66.4,
                    "apply_avg_expected_one_lot_pnl_hkd": 147.0,
                    "false_positive_count": 5,
                    "false_negative_count": 13,
                    "b_group_count": 23,
                    "b_group_positive_rate": 0.826,
                    "b_group_strong_rate": 0.609,
                    "b_group_avg_first_day_pct": 61.8,
                    "b_group_avg_expected_one_lot_pnl_hkd": 93.0,
                },
                {
                    "year": 2025,
                    "sample_count": 117,
                    "apply_count": 24,
                    "apply_positive_rate": 0.739,
                    "apply_strong_rate": 0.435,
                    "apply_avg_first_day_pct": 38.8,
                    "apply_avg_expected_one_lot_pnl_hkd": 35.0,
                    "false_positive_count": 6,
                    "false_negative_count": 40,
                    "b_group_count": 10,
                    "b_group_positive_rate": 0.70,
                    "b_group_strong_rate": 0.40,
                    "b_group_avg_first_day_pct": 33.0,
                    "b_group_avg_expected_one_lot_pnl_hkd": 34.0,
                },
            ],
            "coverage_warnings": [],
            "quality_weight_notes": [],
            "weighted_summary": {
                "建议申购": {"weighted_count": 44.6, "positive_rate": 0.86, "strong_rate": 0.58, "avg_first_day_pct": 63.0, "median_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 138.0},
                "可选观察": {"weighted_count": 39.4, "positive_rate": 0.74, "strong_rate": 0.46, "avg_first_day_pct": 40.0, "median_first_day_pct": 10.0, "avg_expected_one_lot_pnl_hkd": 70.0},
                "暂不参与": {"weighted_count": 2.6, "positive_rate": 1.0, "strong_rate": 0.9, "avg_first_day_pct": 80.0, "median_first_day_pct": 80.0, "avg_expected_one_lot_pnl_hkd": 650.0},
            },
            "weighted_legacy_summary": {
                "建议申购": {"weighted_count": 40.0, "positive_rate": 0.8, "strong_rate": 0.50, "avg_first_day_pct": 55.0, "median_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 120.0},
                "可选观察": {"weighted_count": 44.0, "positive_rate": 0.7, "strong_rate": 0.4, "avg_first_day_pct": 40.0, "median_first_day_pct": 20.0, "avg_expected_one_lot_pnl_hkd": 90.0},
                "暂不参与": {"weighted_count": 1.0, "positive_rate": 1.0, "strong_rate": 1.0, "avg_first_day_pct": 100.0, "median_first_day_pct": 100.0, "avg_expected_one_lot_pnl_hkd": 10.0},
            },
            "weighted_financing_summary": {
                "乙组候选": {"weighted_count": 24.5, "positive_rate": 0.82, "strong_rate": 0.595, "avg_first_day_pct": 58.0, "median_first_day_pct": 70.0, "avg_expected_one_lot_pnl_hkd": 89.0},
                "甲组候选": {"weighted_count": 20.0, "positive_rate": 0.9, "strong_rate": 0.57, "avg_first_day_pct": 70.0, "median_first_day_pct": 31.0, "avg_expected_one_lot_pnl_hkd": 200.0},
                "现金参与": {"weighted_count": 39.0, "positive_rate": 0.74, "strong_rate": 0.46, "avg_first_day_pct": 41.0, "median_first_day_pct": 10.0, "avg_expected_one_lot_pnl_hkd": 71.0},
                "不融资": {"weighted_count": 3.0, "positive_rate": 1.0, "strong_rate": 0.9, "avg_first_day_pct": 88.0, "median_first_day_pct": 88.0, "avg_expected_one_lot_pnl_hkd": 655.0},
            },
        }
        notes = "\n".join(multi.cross_cycle_financing_notes(payload))
        self.assertIn("跨周期融资压力审查", notes)
        self.assertIn("乙组候选跨周期不稳定", notes)
        self.assertIn("不应默认执行乙组", notes)
        self.assertIn("暂不参与", notes)
        markdown = multi.render_markdown(payload)
        self.assertIn("跨周期融资压力审查", markdown)
        self.assertIn("实盘必须等融资截止前", markdown)

    def test_multi_year_expert_conclusion_warns_when_one_lot_pnl_lags_legacy(self):
        multi = load_script("backtest_multi_year.py")
        payload = {
            "generated_at": "2026-06-21T00:00:00",
            "years": [2026, 2025],
            "primary_year": 2026,
            "weights": {2026: 1.0, 2025: 0.15},
            "effective_weights": {2026: 1.0, 2025: 0.15},
            "strong_threshold_pct": 20.0,
            "yearly": [
                {
                    "year": 2026,
                    "sample_count": 10,
                    "apply_count": 5,
                    "apply_positive_rate": 0.9,
                    "apply_strong_rate": 0.6,
                    "apply_avg_first_day_pct": 50.0,
                    "apply_avg_expected_one_lot_pnl_hkd": 50.0,
                    "false_positive_count": 0,
                    "false_negative_count": 0,
                    "b_group_count": 1,
                    "b_group_positive_rate": 1.0,
                    "b_group_strong_rate": 0.5,
                    "b_group_avg_first_day_pct": 30.0,
                    "b_group_avg_expected_one_lot_pnl_hkd": 20.0,
                }
            ],
            "coverage_warnings": [],
            "quality_weight_notes": [],
            "weighted_summary": {
                "建议申购": {"weighted_count": 5.0, "positive_rate": 0.9, "strong_rate": 0.6, "avg_first_day_pct": 50.0, "median_first_day_pct": 40.0, "avg_expected_one_lot_pnl_hkd": 50.0},
                "可选观察": {"weighted_count": 5.0, "positive_rate": 0.7, "strong_rate": 0.3, "avg_first_day_pct": 20.0, "median_first_day_pct": 10.0, "avg_expected_one_lot_pnl_hkd": 80.0},
                "暂不参与": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
            },
            "weighted_legacy_summary": {
                "建议申购": {"weighted_count": 5.0, "positive_rate": 0.8, "strong_rate": 0.5, "avg_first_day_pct": 40.0, "median_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 120.0},
                "可选观察": {"weighted_count": 5.0, "positive_rate": 0.7, "strong_rate": 0.3, "avg_first_day_pct": 20.0, "median_first_day_pct": 10.0, "avg_expected_one_lot_pnl_hkd": 80.0},
                "暂不参与": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
            },
            "weighted_financing_summary": {
                "乙组候选": {"weighted_count": 1.0, "positive_rate": 1.0, "strong_rate": 0.5, "avg_first_day_pct": 30.0, "median_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 20.0},
                "甲组候选": {"weighted_count": 4.0, "positive_rate": 0.8, "strong_rate": 0.5, "avg_first_day_pct": 45.0, "median_first_day_pct": 30.0, "avg_expected_one_lot_pnl_hkd": 100.0},
                "现金参与": {"weighted_count": 5.0, "positive_rate": 0.7, "strong_rate": 0.3, "avg_first_day_pct": 20.0, "median_first_day_pct": 10.0, "avg_expected_one_lot_pnl_hkd": 80.0},
                "不融资": {"weighted_count": 0.0, "positive_rate": None, "strong_rate": None, "avg_first_day_pct": None, "median_first_day_pct": None, "avg_expected_one_lot_pnl_hkd": None},
            },
        }
        markdown = multi.render_markdown(payload)
        self.assertIn("平均首日表现不弱于原策略，但一手期望低于原策略", markdown)
        self.assertIn("不要只按涨幅优化", markdown)
        self.assertIn("资金效率", markdown)

    def test_preclose_score_does_not_use_final_allotment_result(self):
        backtest = load_script("backtest_year_ipos.py")
        base = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例科技",
            "industry": "半导体产品及设备",
            "entry_fee_hkd": 3600.0,
            "listing_price_hkd": 7.2,
            "sponsor": "中国国际金融香港证券有限公司",
            "hk_public_offer_shares_raw": "5000000(10.00%)",
            "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
        }
        cold_final = dict(base, oversubscription_rate=10.0, one_lot_success_rate_pct=50.0)
        hot_final = dict(base, oversubscription_rate=5000.0, one_lot_success_rate_pct=1.0)
        self.assertEqual(
            backtest.optimized_preclose_score(cold_final),
            backtest.optimized_preclose_score(hot_final),
        )

    def test_backtest_adds_review_only_expected_one_lot_pnl(self):
        backtest = load_script("backtest_year_ipos.py")
        record = {
            "recommendation": {"action": "建议申购"},
            "entry_fee_hkd": 3000.0,
            "first_day_change_pct": 20.0,
            "one_lot_success_rate_pct": 10.0,
        }
        self.assertAlmostEqual(backtest.expected_one_lot_gross_pnl(record), 60.0)
        summary = backtest.summarize([record], threshold=20.0)
        row = summary["by_action"]["建议申购"]
        self.assertAlmostEqual(row["avg_expected_one_lot_pnl_hkd"], 60.0)
        self.assertAlmostEqual(row["positive_expected_pnl_rate"], 1.0)

    def test_backtest_capital_schedule_blocks_overlapping_cash(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {
                "code": "00001.HK",
                "canonical_code": "00001",
                "name": "先发科技",
                "closing_date": "2026-01-05",
                "listing_date": "2026-01-10",
                "entry_fee_hkd": 300_000.0,
                "first_day_change_pct": 20.0,
                "one_lot_success_rate_pct": 10.0,
                "recommendation": {"action": "建议申购", "score": 79},
            },
            {
                "code": "00002.HK",
                "canonical_code": "00002",
                "name": "重叠科技",
                "closing_date": "2026-01-06",
                "listing_date": "2026-01-11",
                "entry_fee_hkd": 300_000.0,
                "first_day_change_pct": 80.0,
                "one_lot_success_rate_pct": 10.0,
                "recommendation": {"action": "建议申购", "score": 80},
            },
            {
                "code": "00003.HK",
                "canonical_code": "00003",
                "name": "后续科技",
                "closing_date": "2026-01-12",
                "listing_date": "2026-01-16",
                "entry_fee_hkd": 300_000.0,
                "first_day_change_pct": 30.0,
                "one_lot_success_rate_pct": 10.0,
                "recommendation": {"action": "建议申购", "score": 78},
            },
        ]
        summary = backtest.summarize_capital_schedule(records, cash_hkd=550_000.0)
        self.assertEqual(summary["candidate_count"], 3)
        self.assertEqual(summary["selected_count"], 2)
        self.assertEqual(summary["conflict_skipped_count"], 1)
        self.assertEqual(summary["peak_cash_reserved_hkd"], 300_000.0)
        self.assertLessEqual(summary["peak_cash_reserved_hkd"], 550_000.0)
        self.assertAlmostEqual(summary["selected_avg_expected_one_lot_pnl_hkd"], 16500.0)
        self.assertAlmostEqual(summary["conflict_avg_expected_one_lot_pnl_hkd"], 6000.0)
        self.assertIn("重叠科技（00002.HK）", summary["selected_examples"])
        self.assertIn("先发科技（00001.HK）", summary["conflict_examples"][0]["stock"])
        markdown = "\n".join(backtest.render_capital_schedule_section(summary))
        self.assertIn("资金窗口压力测试", markdown)
        self.assertIn("同一锁定窗口现金不可重复使用", markdown)
        self.assertIn("排入平均一手期望", markdown)
        self.assertIn("冲突平均一手期望", markdown)
        self.assertIn("一手期望覆盖", markdown)
        self.assertIn("先发科技（00001.HK）", markdown)

    def test_backtest_peak_capital_releases_cash_before_same_day_new_lock(self):
        backtest = load_script("backtest_year_ipos.py")
        first = {
            "_capital_required_hkd": 550_000.0,
            "_capital_window": (dt.date(2026, 1, 1), dt.date(2026, 1, 5)),
        }
        second = {
            "_capital_required_hkd": 550_000.0,
            "_capital_window": (dt.date(2026, 1, 6), dt.date(2026, 1, 10)),
        }
        self.assertFalse(backtest.windows_overlap(first["_capital_window"], second["_capital_window"]))
        self.assertEqual(backtest.peak_capital_reserved([first, second]), 550_000.0)

    def test_backtest_capital_schedule_variants_compare_preclose_tiebreakers(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {
                "code": "00001.HK",
                "canonical_code": "00001",
                "name": "高费科技",
                "closing_date": "2026-01-05",
                "listing_date": "2026-01-10",
                "entry_fee_hkd": 310_000.0,
                "first_day_change_pct": 10.0,
                "one_lot_success_rate_pct": 10.0,
                "recommendation": {"action": "建议申购", "score": 80, "financing": {"tier": "甲组候选"}},
            },
            {
                "code": "00002.HK",
                "canonical_code": "00002",
                "name": "低费科技",
                "closing_date": "2026-01-06",
                "listing_date": "2026-01-11",
                "entry_fee_hkd": 300_000.0,
                "first_day_change_pct": 80.0,
                "one_lot_success_rate_pct": 10.0,
                "recommendation": {"action": "建议申购", "score": 80, "financing": {"tier": "甲组候选"}},
            },
        ]
        baseline = backtest.summarize_capital_schedule(records, cash_hkd=550_000.0, priority_strategy="score")
        optimized = backtest.summarize_capital_schedule(records, cash_hkd=550_000.0, priority_strategy="score_entry")
        self.assertIn("高费科技（00001.HK）", baseline["selected_examples"])
        self.assertIn("低费科技（00002.HK）", optimized["selected_examples"])
        variants = backtest.summarize_capital_schedule_variants(records, cash_hkd=550_000.0)
        markdown = "\n".join(backtest.render_capital_priority_sensitivity_section(variants))
        self.assertIn("排期排序敏感性", markdown)
        self.assertIn("分数+低入场费优先", markdown)
        self.assertIn("事前效用组合最优", markdown)
        self.assertIn("排入平均一手期望", markdown)
        self.assertIn("冲突平均一手期望", markdown)
        self.assertIn("排序只使用事前可见字段", markdown)

    def test_backtest_capital_schedule_utility_selects_best_preclose_combination(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {
                "code": "00001.HK",
                "canonical_code": "00001",
                "name": "单只高分",
                "closing_date": "2026-01-05",
                "listing_date": "2026-01-10",
                "entry_fee_hkd": 550_000.0,
                "first_day_change_pct": 10.0,
                "one_lot_success_rate_pct": 10.0,
                "recommendation": {"action": "建议申购", "score": 80},
            },
            {
                "code": "00002.HK",
                "canonical_code": "00002",
                "name": "组合一号",
                "closing_date": "2026-01-05",
                "listing_date": "2026-01-10",
                "entry_fee_hkd": 275_000.0,
                "first_day_change_pct": 20.0,
                "one_lot_success_rate_pct": 10.0,
                "recommendation": {"action": "建议申购", "score": 79},
            },
            {
                "code": "00003.HK",
                "canonical_code": "00003",
                "name": "组合二号",
                "closing_date": "2026-01-05",
                "listing_date": "2026-01-10",
                "entry_fee_hkd": 275_000.0,
                "first_day_change_pct": 20.0,
                "one_lot_success_rate_pct": 10.0,
                "recommendation": {"action": "建议申购", "score": 79},
            },
        ]
        greedy = backtest.summarize_capital_schedule(records, cash_hkd=550_000.0, priority_strategy="score")
        utility = backtest.summarize_capital_schedule(records, cash_hkd=550_000.0, priority_strategy="utility_score_entry")
        self.assertEqual(greedy["selected_count"], 1)
        self.assertEqual(utility["selected_count"], 2)
        self.assertIn("组合一号（00002.HK）", utility["selected_examples"])
        self.assertIn("组合二号（00003.HK）", utility["selected_examples"])
        self.assertIn("单只高分（00001.HK）", utility["conflict_examples"][0]["stock"])

    def test_current_report_schedule_uses_preclose_utility_tiebreaker(self):
        report = load_script("build_recommendation_report.py")
        analyses = [
            {
                "title": "高费科技（00001.HK）",
                "category": "建议申购",
                "score": 75,
                "ipo": {
                    "code": "00001.HK",
                    "entry_fee_hkd": 310_000.0,
                    "closing_date": "2026-01-05",
                    "listing_date": "2026-01-10",
                },
                "subscription_closed": False,
                "review_due": False,
            },
            {
                "title": "低费科技（00002.HK）",
                "category": "建议申购",
                "score": 75,
                "ipo": {
                    "code": "00002.HK",
                    "entry_fee_hkd": 300_000.0,
                    "closing_date": "2026-01-06",
                    "listing_date": "2026-01-11",
                },
                "subscription_closed": False,
                "review_due": False,
            },
        ]
        scheduled = report.attach_funding_and_schedule(
            analyses,
            cash_hkd=550_000.0,
            margin_multiple=10.0,
            margin_rate_pct=None,
            financing_days=7,
        )
        by_title = {item["title"]: item for item in scheduled}
        self.assertEqual(by_title["高费科技（00001.HK）"]["funding_plan"]["schedule_decision"], "已排入默认资金")
        self.assertEqual(by_title["低费科技（00002.HK）"]["funding_plan"]["schedule_decision"], "资金冲突待取舍")
        markdown = "\n".join(report.funding_schedule_section(scheduled))
        self.assertIn("事前组合效用", markdown)

    def test_backtest_margin_history_coverage_reports_missing_b_group_heat(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {
                "code": "00001.HK",
                "canonical_code": "00001",
                "name": "乙组科技",
                "closing_date": "2026-01-05",
                "listing_date": "2026-01-10",
                "recommendation": {"action": "建议申购", "score": 80, "financing": {"tier": "乙组候选"}},
            },
            {
                "code": "00002.HK",
                "canonical_code": "00002",
                "name": "甲组科技",
                "closing_date": "2026-01-06",
                "listing_date": "2026-01-11",
                "recommendation": {"action": "建议申购", "score": 76, "financing": {"tier": "甲组候选"}},
            },
        ]
        coverage = backtest.summarize_margin_history_coverage(records)
        self.assertEqual(coverage["b_group_candidate_count"], 1)
        self.assertEqual(coverage["covered_count"], 0)
        self.assertEqual(coverage["invalid_timing_count"], 0)
        self.assertEqual(coverage["missing_count"], 1)
        self.assertEqual(coverage["coverage_rate"], 0)
        markdown = "\n".join(backtest.render_margin_history_coverage_section(coverage))
        self.assertIn("历史孖展覆盖审查", markdown)
        self.assertIn("覆盖率低于 70%", markdown)
        self.assertIn("prepare_margin_history_template.py", markdown)
        self.assertIn("乙组科技（00001.HK）", markdown)

    def test_backtest_margin_history_coverage_counts_strict_gate_met(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {
                "code": "00001.HK",
                "canonical_code": "00001",
                "name": "乙组科技",
                "closing_date": "2026-01-05",
                "listing_date": "2026-01-10",
                "recommendation": {"action": "建议申购", "score": 80, "financing": {"tier": "乙组候选"}},
            }
        ]
        heat_payload = {
            "stocks": [
                {
                    "code": "00001",
                    "stock_name": "乙组科技",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["孖展倍数显著领先", "多券商热度一致"],
                        "cost_status": "可接受",
                        "cost_signals": ["融资成本可接受"],
                        "risk_flags": [],
                        "min_financing_rate_pct": 3.8,
                    },
                }
            ]
        }
        coverage = backtest.summarize_margin_history_coverage(records, margin_heat_payload=heat_payload)
        self.assertEqual(coverage["covered_count"], 1)
        self.assertEqual(coverage["invalid_timing_count"], 0)
        self.assertEqual(coverage["missing_count"], 0)
        self.assertEqual(coverage["gate_met_count"], 1)
        self.assertEqual(coverage["coverage_rate"], 1)
        markdown = "\n".join(backtest.render_margin_history_coverage_section(coverage))
        self.assertIn("严格闸门满足", markdown)
        self.assertIn("| 1 | 1 | 0 | 0 | 100.0% | 1", markdown)

    def test_backtest_margin_history_coverage_excludes_invalid_timing(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {
                "code": "00001.HK",
                "canonical_code": "00001",
                "name": "乙组科技",
                "closing_date": "2026-01-05",
                "listing_date": "2026-01-10",
                "recommendation": {"action": "建议申购", "score": 80, "financing": {"tier": "乙组候选"}},
            }
        ]
        heat_payload = {
            "stocks": [
                {
                    "code": "00001",
                    "stock_name": "乙组科技",
                    "summary": {
                        "execution_gate": "满足",
                        "strong_signals": ["多券商热度一致", "额度紧张或截止提前"],
                        "cost_status": "可接受",
                        "cost_signals": ["融资成本可接受"],
                        "risk_flags": [],
                        "timing_valid_row_count": 0,
                        "timing_invalid_row_count": 1,
                    },
                }
            ]
        }
        coverage = backtest.summarize_margin_history_coverage(records, margin_heat_payload=heat_payload)
        self.assertEqual(coverage["covered_count"], 0)
        self.assertEqual(coverage["invalid_timing_count"], 1)
        self.assertEqual(coverage["missing_count"], 0)
        self.assertEqual(coverage["coverage_rate"], 0)
        markdown = "\n".join(backtest.render_margin_history_coverage_section(coverage))
        self.assertIn("时间无效样本不计入有效覆盖率", markdown)
        self.assertIn("乙组科技（00001.HK）", markdown)

    def test_backtest_score_band_calibration_warns_against_mechanical_thresholds(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {
                "recommendation": {"score": 79, "action": "建议申购"},
                "entry_fee_hkd": 3000.0,
                "first_day_change_pct": 10.0,
                "one_lot_success_rate_pct": 10.0,
            },
            {
                "recommendation": {"score": 79, "action": "建议申购"},
                "entry_fee_hkd": 3000.0,
                "first_day_change_pct": -5.0,
                "one_lot_success_rate_pct": 10.0,
            },
            {
                "recommendation": {"score": 74, "action": "建议申购"},
                "entry_fee_hkd": 3000.0,
                "first_day_change_pct": 30.0,
                "one_lot_success_rate_pct": 10.0,
            },
        ]
        summary = backtest.summarize_score_bands(records, threshold=20.0)
        self.assertEqual(summary["78+"]["count"], 2)
        self.assertEqual(summary["72-77"]["count"], 1)
        self.assertLess(summary["78+"]["avg_expected_one_lot_pnl_hkd"], summary["72-77"]["avg_expected_one_lot_pnl_hkd"])
        note = backtest.score_band_calibration_note(summary)
        self.assertIn("不应机械提高建议阈值", note)
        self.assertIn("融资热度", note)

    def test_year_backtest_renders_current_year_expert_audit(self):
        backtest = load_script("backtest_year_ipos.py")
        payload = {
            "year": 2026,
            "summary": {
                "by_action": {
                    "建议申购": {"count": 10, "positive_rate": 0.9, "strong_rate": 0.6, "avg_expected_one_lot_pnl_hkd": 120.0},
                    "可选观察": {"count": 8, "positive_rate": 0.8, "strong_rate": 0.5, "avg_expected_one_lot_pnl_hkd": 40.0},
                    "暂不参与": {"count": 2, "positive_rate": 1.0, "strong_rate": 1.0, "avg_expected_one_lot_pnl_hkd": 300.0},
                }
            },
            "heat_gate_proxy": {
                "乙组候选且最终强热度": {"count": 6, "positive_rate": 1.0, "strong_rate": 0.8},
                "乙组候选但最终弱热度": {"count": 4, "positive_rate": 0.5, "strong_rate": 0.25},
            },
        }
        markdown = "\n".join(backtest.render_current_year_expert_audit(payload))
        self.assertIn("2026 年单年样本为主", markdown)
        self.assertIn("不能把早期冷市经验机械套到当前市场", markdown)
        self.assertIn("不等于所有票都应直接上乙组", markdown)
        self.assertIn("券商融资截止前强制采集", markdown)
        self.assertIn("不能泄露进申购前模型", markdown)
        self.assertIn("统计意义不足", markdown)

    def test_backtest_explains_miss_attribution_without_changing_score(self):
        backtest = load_script("backtest_year_ipos.py")
        false_positive = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例芯片",
            "industry": "半导体产品及设备",
            "entry_fee_hkd": 3600.0,
            "closing_date": "2026-06-01",
            "listing_date": "2026-06-05",
            "first_day_change_pct": -10.0,
            "oversubscription_rate": 80.0,
            "one_lot_success_rate_pct": 20.0,
            "recommendation": {
                "action": "建议申购",
                "score": 79,
                "financing": {"tier": "乙组候选"},
                "evidence": ["低入场费", "稀缺/科技行业"],
                "risks": [],
            },
        }
        false_negative = {
            "code": "05678.HK",
            "canonical_code": "05678",
            "name": "观察科技",
            "industry": "新一代信息技术",
            "entry_fee_hkd": 3600.0,
            "closing_date": "2026-06-02",
            "listing_date": "2026-06-06",
            "first_day_change_pct": 80.0,
            "oversubscription_rate": 2500.0,
            "one_lot_success_rate_pct": 2.0,
            "recommendation": {
                "action": "可选观察",
                "score": 68,
                "financing": {"tier": "现金参与"},
                "evidence": ["入场费较低"],
                "risks": [],
            },
        }
        self.assertEqual(backtest.final_heat_label(false_positive), "最终弱热度")
        fp_text = "；".join(backtest.miss_attribution(false_positive, threshold=20.0))
        self.assertIn("孖展/额度闸门", fp_text)
        self.assertIn("二次锁单", fp_text)

        self.assertEqual(backtest.final_heat_label(false_negative), "最终强热度")
        fn_text = "；".join(backtest.miss_attribution(false_negative, threshold=20.0))
        self.assertIn("孖展/额度时间序列", fn_text)
        self.assertIn("升级复核", fn_text)

        table = "\n".join(backtest.render_miss_attribution_table([false_positive, false_negative], threshold=20.0))
        self.assertIn("| 归因 | 次数 | 示例 |", table)
        self.assertIn("示例芯片（01234.HK）", table)
        self.assertIn("观察科技（05678.HK）", table)

        audit = backtest.summarize_miss_attribution_audit(
            [false_positive, false_negative],
            threshold=20.0,
        )
        self.assertEqual(audit["false_positive_count"], 1)
        self.assertEqual(audit["false_negative_count"], 1)
        self.assertEqual(audit["dominant_false_positive"]["share"], 1.0)
        self.assertIn("不得把最终超购", audit["model_guardrail"])

        payload = backtest.build_year_payload(year=2026, records=[false_positive, false_negative])
        self.assertIn("miss_attribution_summary", payload)
        markdown = backtest.render_markdown(payload)
        self.assertIn("归因集中度审计", markdown)
        self.assertIn("防泄露口径", markdown)

    def test_year_backtest_reports_borderline_observation_queue(self):
        backtest = load_script("backtest_year_ipos.py")
        payload = backtest.build_year_payload(
            year=2026,
            records=[
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "临界消费",
                    "industry": "包装食品",
                    "entry_fee_hkd": 3600.0,
                    "listing_price_hkd": 7.2,
                    "sponsor": "中国国际金融香港证券有限公司",
                    "hk_public_offer_shares_raw": "5000000(10.00%)",
                    "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
                    "listing_date": "2026-02-01",
                    "closing_date": "2026-01-25",
                    "first_day_change_pct": 30.0,
                    "oversubscription_rate": 1500.0,
                    "one_lot_success_rate_pct": 2.0,
                }
            ],
        )
        row = payload["borderline_observation"]
        self.assertEqual(row["count"], 1)
        self.assertEqual(row["final_strong_heat_count"], 1)
        markdown = backtest.render_markdown(payload)
        self.assertIn("## 评分分层校准", markdown)
        self.assertIn("## 临界观察队列复盘", markdown)
        self.assertIn("不自动变成建议申购或乙组执行", markdown)
        self.assertIn("临界消费（01234.HK）", markdown)

    def test_financing_tier_is_preclose_candidate_not_final_result(self):
        backtest = load_script("backtest_year_ipos.py")
        record = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例科技",
            "industry": "半导体产品及设备",
            "entry_fee_hkd": 3600.0,
            "listing_price_hkd": 7.2,
            "sponsor": "中国国际金融香港证券有限公司",
            "hk_public_offer_shares_raw": "5000000(10.00%)",
            "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
        }
        scored = backtest.optimized_preclose_score(record)
        self.assertEqual(scored["financing"]["tier"], "乙组候选")
        self.assertIn("融资截止前", scored["financing"]["reason"])
        self.assertIn("至少两个需求/额度类热度信号", scored["financing"]["reason"])
        self.assertIn("成本可接受", scored["financing"]["reason"])

    def test_market_regime_uses_only_prior_listings(self):
        backtest = load_script("backtest_year_ipos.py")
        history = [
            {
                "code": f"0{i:04d}.HK",
                "canonical_code": f"0{i:04d}",
                "name": f"历史{i}",
                "listing_date": f"2026-01-{i + 1:02d}",
                "closing_date": f"2026-01-{i:02d}",
                "first_day_change_pct": -10.0,
            }
            for i in range(1, 9)
        ]
        current = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例科技",
            "listing_date": "2026-02-01",
            "closing_date": "2026-01-25",
            "first_day_change_pct": 200.0,
        }
        records = history + [dict(current)]
        backtest.attach_market_regimes(records, window=20, min_samples=8)
        self.assertEqual(records[-1]["market_regime"]["label"], "偏冷")

        records_with_bad_current = history + [dict(current, first_day_change_pct=-80.0)]
        backtest.attach_market_regimes(records_with_bad_current, window=20, min_samples=8)
        self.assertEqual(records[-1]["market_regime"], records_with_bad_current[-1]["market_regime"])

    def test_display_stock_avoids_english_primary_name(self):
        backtest = load_script("backtest_year_ipos.py")
        report = load_script("build_recommendation_report.py")
        self.assertEqual(
            backtest.display_stock({"name": "SENASIC", "code": "06675.HK"}),
            "代码06675.HK（中文名待核实）",
        )
        self.assertEqual(
            backtest.display_stock({"name": "MINIMAX-W", "code": "00100.HK"}),
            "稀宇科技（00100.HK）",
        )
        self.assertEqual(
            backtest.display_stock({"name": "MANYCORE TECH", "code": "00068.HK"}),
            "群核科技（00068.HK）",
        )
        self.assertEqual(
            backtest.display_stock({"name": "BBSB INTL", "code": "08610.HK"}),
            "马来西亚土木工程承包商（08610.HK）",
        )
        self.assertEqual(
            backtest.display_stock({"name": "示例科技", "code": "01234.HK"}),
            "示例科技（01234.HK）",
        )
        self.assertEqual(
            backtest.display_stock({"name": "星源材质今日暗盘", "code": "06067.HK"}),
            "星源材质（06067.HK）",
        )
        self.assertEqual(
            report.stock_title({"name": "华健未来－Ｂ今日暗盘", "code": "06132.HK"}),
            "华健未来－Ｂ（06132.HK）",
        )
        self.assertEqual(
            report.stock_title({"name": "PT Merdeka Gold-DRS", "code": "06228.HK", "industry": "黄金与贵金属"}),
            "印尼金矿商（06228.HK）",
        )
        self.assertEqual(
            backtest.display_stock({"name": "PT Merdeka Gold-DRS", "code": "06228.HK", "industry": "黄金与贵金属"}),
            "印尼金矿商（06228.HK）",
        )
        self.assertEqual(report.ipo_status({"name": "星源材质今日暗盘", "code": "06067.HK"}), "今日暗盘")
        self.assertEqual(
            report.ipo_status({"name": "星源材质今日暗盘", "status": "已截止待上市", "code": "06067.HK"}),
            "已截止待上市；今日暗盘",
        )

    def test_cold_market_blocks_b_group_candidate(self):
        backtest = load_script("backtest_year_ipos.py")
        record = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例科技",
            "industry": "半导体产品及设备",
            "entry_fee_hkd": 3600.0,
            "listing_price_hkd": 7.2,
            "sponsor": "中国国际金融香港证券有限公司",
            "hk_public_offer_shares_raw": "5000000(10.00%)",
            "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
            "market_regime": {"label": "偏冷", "sample_size": 12},
        }
        scored = backtest.optimized_preclose_score(record)
        self.assertNotEqual(scored["financing"]["tier"], "乙组候选")
        self.assertIn("近期新股市场偏冷", "；".join(scored["risks"] + [scored["financing"]["reason"]]))

    def test_generic_tech_guard_downgrades_preclose_action(self):
        backtest = load_script("backtest_year_ipos.py")
        record = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例软件",
            "industry": "应用软件",
            "entry_fee_hkd": 3600.0,
            "listing_price_hkd": 7.2,
            "sponsor": "中国国际金融香港证券有限公司",
            "hk_public_offer_shares_raw": "5000000(10.00%)",
            "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
            "market_regime": {"label": "中性", "sample_size": 20},
        }
        scored = backtest.optimized_preclose_score(record)
        self.assertEqual(scored["action"], "可选观察")
        self.assertIn("泛软件", "；".join(scored["risks"]))

    def test_hot_market_keeps_data_gap_low_entry_stock_under_observation(self):
        backtest = load_script("backtest_year_ipos.py")
        record = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例药业－Ｂ",
            "industry": "",
            "entry_fee_hkd": 3600.0,
            "listing_price_hkd": 7.2,
            "sponsor": "",
            "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
            "market_regime": {"label": "偏热", "sample_size": 20},
        }
        scored = backtest.optimized_preclose_score(record)
        self.assertEqual(scored["action"], "可选观察")
        self.assertEqual(scored["financing"]["tier"], "现金参与")
        self.assertIn("先观察", "；".join(scored["risks"]))

    def test_hot_market_keeps_strong_sponsor_quality_stock_under_observation(self):
        backtest = load_script("backtest_year_ipos.py")
        record = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例消费",
            "industry": "包装食品",
            "entry_fee_hkd": 24_000.0,
            "listing_price_hkd": 240.0,
            "sponsor": "中国国际金融香港证券有限公司",
            "hk_public_offer_shares_raw": "5000000(10.00%)",
            "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
            "market_regime": {"label": "偏热", "sample_size": 20},
        }
        scored = backtest.optimized_preclose_score(record)
        self.assertEqual(scored["action"], "可选观察")
        self.assertEqual(scored["financing"]["tier"], "现金参与")
        self.assertIn("强保荐", "；".join(scored["risks"]))

    def test_detail_retry_recovers_failed_detail_with_longer_timeout(self):
        backtest = load_script("backtest_year_ipos.py")
        original = backtest.enrich_one_detail
        calls = []

        def fake_enrich(record, *, timeout, retries):
            calls.append((timeout, retries))
            item = dict(record)
            item["detail_status"] = "ok"
            item["industry"] = "半导体产品及设备"
            return item

        backtest.enrich_one_detail = fake_enrich
        try:
            records = [{"canonical_code": "01234", "detail_status": "error: timeout"}]
            retried = backtest.retry_failed_details(records, timeout=3, retries=0, delay=0, limit=1)
        finally:
            backtest.enrich_one_detail = original

        self.assertEqual(retried[0]["detail_status"], "ok")
        self.assertEqual(retried[0]["detail_retry_status"], "ok")
        self.assertGreaterEqual(calls[0][0], 12)
        self.assertEqual(calls[0][1], 1)

    def test_detail_retry_skips_when_target_coverage_is_met(self):
        backtest = load_script("backtest_year_ipos.py")
        original = backtest.enrich_one_detail
        calls = []

        def fake_enrich(record, *, timeout, retries):
            calls.append(record)
            return record

        backtest.enrich_one_detail = fake_enrich
        try:
            records = [
                {"canonical_code": "00001", "detail_status": "ok"},
                {"canonical_code": "00002", "detail_status": "ok"},
                {"canonical_code": "00003", "detail_status": "error: timeout"},
            ]
            retried = backtest.retry_failed_details(records, timeout=3, retries=0, delay=0, target_ratio=0.5)
        finally:
            backtest.enrich_one_detail = original

        self.assertEqual(retried, records)
        self.assertEqual(calls, [])

    def test_data_quality_counts_hkex_documents_and_detail_retries(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {
                "detail_status": "ok",
                "detail_retry_status": "ok",
                "documents": {"prospectus_url": "https://www1.hkexnews.hk/p.pdf"},
                "industry": "半导体",
                "sponsor": "中金公司",
                "entry_fee_hkd": 3000.0,
                "one_lot_success_rate_pct": 5.0,
                "first_day_change_pct": 20.0,
            },
            {
                "source_urls": {"hkex_listing_information": "https://www2.hkexnews.hk"},
                "entry_fee_hkd": 3500.0,
            },
        ]
        quality = backtest.summarize_data_quality(records)
        self.assertEqual(quality["total"], 2)
        self.assertEqual(quality["detail_ok_count"], 1)
        self.assertEqual(quality["detail_retry_ok_count"], 1)
        self.assertEqual(quality["hkex_document_count"], 2)
        self.assertEqual(quality["industry_count"], 1)
        self.assertEqual(quality["sponsor_count"], 1)

    def test_hkex_listing_report_backfills_missing_static_fields(self):
        backtest = load_script("backtest_year_ipos.py")
        records = [
            {"code": "01234.HK", "canonical_code": "01234", "name": "示例科技"},
            {"code": "05678.HK", "canonical_code": "05678", "name": "已有保荐", "sponsor": "原保荐人"},
        ]
        report_records = [
            {
                "code": "01234.HK",
                "canonical_code": "01234",
                "official_english_name": "Example Technology Limited",
                "sponsor": "China International Capital Corporation",
                "offer_price_hkd": 7.2,
                "listing_date": "2025-01-09",
                "source_urls": {"hkex_listing_report": "https://www2.hkexnews.hk/report.xlsx"},
            },
            {
                "code": "05678.HK",
                "canonical_code": "05678",
                "sponsor": "不应覆盖",
                "source_urls": {"hkex_listing_report": "https://www2.hkexnews.hk/report.xlsx"},
            },
        ]
        stats = backtest.apply_hkex_report_records(records, report_records)
        self.assertEqual(stats["matches"], 2)
        self.assertEqual(stats["sponsor_filled"], 1)
        self.assertEqual(records[0]["sponsor"], "China International Capital Corporation")
        self.assertEqual(records[0]["official_english_name"], "Example Technology Limited")
        self.assertEqual(records[0]["offer_price_hkd"], 7.2)
        self.assertEqual(records[1]["sponsor"], "原保荐人")
        self.assertTrue(records[0]["hkex_listing_report_match"])

    def test_rescore_year_payload_uses_current_rules(self):
        backtest = load_script("backtest_year_ipos.py")
        payload = {
            "year": 2026,
            "strong_threshold_pct": 20.0,
            "sources": [],
            "records": [
                *[
                    {
                        "code": f"0{i:04d}.HK",
                        "canonical_code": f"0{i:04d}",
                        "name": f"历史{i}",
                        "industry": "包装食品",
                        "entry_fee_hkd": 3000.0,
                        "listing_price_hkd": 3.0,
                        "sponsor": "示例证券",
                        "hk_public_offer_shares_raw": "5000000(10.00%)",
                        "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
                        "listing_date": f"2026-01-{i + 1:02d}",
                        "closing_date": f"2026-01-{i:02d}",
                        "first_day_change_pct": -8.0,
                    }
                    for i in range(1, 9)
                ],
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例软件",
                    "industry": "应用软件",
                    "entry_fee_hkd": 3600.0,
                    "listing_price_hkd": 7.2,
                    "sponsor": "中国国际金融香港证券有限公司",
                    "hk_public_offer_shares_raw": "5000000(10.00%)",
                    "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
                    "listing_date": "2026-02-01",
                    "closing_date": "2026-01-25",
                    "first_day_change_pct": 10.0,
                    "market_regime": {"label": "中性", "sample_size": 20},
                }
            ],
        }
        rescored = backtest.rescore_year_payload(payload)
        current = next(record for record in rescored["records"] if record["code"] == "01234.HK")
        self.assertEqual(current["recommendation"]["action"], "可选观察")

    def test_year_backtest_cli_can_rescore_input_json_without_refetching(self):
        backtest = load_script("backtest_year_ipos.py")
        payload = {
            "year": 2026,
            "strong_threshold_pct": 20.0,
            "sources": [],
            "records": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "示例科技",
                    "industry": "半导体产品及设备",
                    "entry_fee_hkd": 3600.0,
                    "listing_price_hkd": 7.2,
                    "sponsor": "中国国际金融香港证券有限公司",
                    "hk_public_offer_shares_raw": "5000000(10.00%)",
                    "source_urls": {"aastocks_detail": "https://www.aastocks.com"},
                    "listing_date": "2026-02-01",
                    "closing_date": "2026-01-25",
                    "first_day_change_pct": 30.0,
                    "one_lot_success_rate_pct": 5.0,
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = backtest.main(["--input-json", handle.name, "--rescore-input", "--json"])
        self.assertEqual(code, 0)
        rescored = json.loads(output.getvalue())
        self.assertEqual(rescored["summary"]["by_action"]["建议申购"]["count"], 1)
        self.assertIn("data_quality", rescored)

    def test_strategy_alignment_audit_prioritizes_actionable_2026_logic(self):
        audit = load_script("audit_strategy_alignment.py")
        base_ipo = {
            "code": "01234.HK",
            "canonical_code": "01234",
            "name": "示例科技",
            "industry": "半导体产品及设备",
            "entry_fee_hkd": 3600.0,
            "listing_price_hkd": 7.2,
            "listing_date": "2026-06-26",
            "sponsor": "中国国际金融香港证券有限公司",
            "hk_public_offer_shares_raw": "5000000(10.00%)",
            "documents": {
                "prospectus_url": "https://www1.hkexnews.hk/p.pdf",
                "listing_announcement_url": "https://www1.hkexnews.hk/a.pdf",
            },
        }
        payload = {
            "as_of_date": "2026-06-21",
            "ipos": [
                dict(base_ipo, closing_date="2026-06-24"),
                dict(base_ipo, code="05678.HK", canonical_code="05678", name="已截止科技", closing_date="2026-06-18"),
            ],
        }
        result = audit.audit_payload(payload, market_regime={"label": "偏热", "sample_size": 20})
        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(result["summary"]["actionable"], 1)
        self.assertEqual(result["summary"]["actionable_mismatches"], 0)
        self.assertEqual(result["summary"]["contextual_mismatches"], 1)
        self.assertIn("通过", result["summary"]["verdict"])
        self.assertEqual(result["rows"][0]["status"], "一致")
        self.assertEqual(result["rows"][1]["status"], "上下文差异")

        markdown = audit.render_markdown(result)
        self.assertIn("港股打新策略一致性审查", markdown)
        self.assertIn("当前市场调参以 2026 单年回测为主", markdown)
        self.assertIn("| 可申购不一致率 | 0.0% |", markdown)
        self.assertIn("已截止/复盘", markdown)

    def test_strategy_alignment_audit_separates_deep_dive_overlay(self):
        audit = load_script("audit_strategy_alignment.py")
        payload = {
            "as_of_date": "2026-06-21",
            "ipos": [
                {
                    "code": "01234.HK",
                    "canonical_code": "01234",
                    "name": "深挖科技",
                    "industry": "半导体产品及设备",
                    "entry_fee_hkd": 3600.0,
                    "listing_price_hkd": 7.2,
                    "closing_date": "2026-06-24",
                    "listing_date": "2026-06-26",
                    "sponsor": "中国国际金融香港证券有限公司",
                    "hk_public_offer_shares_raw": "5000000(10.00%)",
                    "documents": {
                        "prospectus_url": "https://www1.hkexnews.hk/p.pdf",
                        "listing_announcement_url": "https://www1.hkexnews.hk/a.pdf",
                    },
                }
            ],
        }
        result = audit.audit_payload(
            payload,
            market_regime={"label": "偏热", "sample_size": 20},
            deep_dive_payload={
                "code": "01234",
                "stock_name": "深挖科技",
                "text_available": True,
                "signals": {
                    "score_modifier": -9,
                    "confidence": "高",
                    "positive_flags": [],
                    "risk_flags": ["估值偏高", "客户集中"],
                    "missing_checks": [],
                },
            },
        )
        self.assertEqual(result["summary"]["actionable"], 1)
        self.assertEqual(result["summary"]["actionable_mismatches"], 0)
        self.assertEqual(result["summary"]["deep_dive_mismatches"], 1)
        self.assertEqual(result["rows"][0]["status"], "深挖覆盖差异")
        markdown = audit.render_markdown(result)
        self.assertIn("深挖覆盖差异", markdown)
        self.assertIn("更完整的事前资料", markdown)


if __name__ == "__main__":
    unittest.main()
