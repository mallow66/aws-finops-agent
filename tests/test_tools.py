"""
Unit tests for the three FinOps tools.

All tests run against mock data (MOCK_MODE=1) — no AWS credentials needed.
The env var is forced here via os.environ so the module loads in mock mode
regardless of what is set in the shell.
"""
import os
os.environ["MOCK_MODE"] = "1"  # must be set before importing tools

import pytest
from src.tools import (
    _compute_savings_summary,
    _estimate_ebs_volume_cost,
    _estimate_eip_cost,
    _estimate_instance_cost,
    _get_idle_resources,
    _get_rightsizing_recommendations,
)


class TestGetRightsizingRecommendations:
    def test_returns_three_mock_records(self):
        recs = _get_rightsizing_recommendations()
        assert len(recs) == 3

    def test_all_findings_are_over_provisioned(self):
        recs = _get_rightsizing_recommendations()
        assert all(r["finding"] == "OVER_PROVISIONED" for r in recs)

    def test_each_record_has_required_keys(self):
        required = {"instanceArn", "instanceName", "currentInstanceType",
                    "finding", "utilizationMetrics", "recommendationOptions"}
        for rec in _get_rightsizing_recommendations():
            assert required.issubset(rec.keys())

    def test_each_record_has_at_least_one_option(self):
        for rec in _get_rightsizing_recommendations():
            assert len(rec["recommendationOptions"]) >= 1


class TestGetIdleResources:
    def test_returns_both_resource_types(self):
        idle = _get_idle_resources()
        assert "unattached_volumes" in idle
        assert "unattached_eips" in idle

    def test_volumes_have_expected_count(self):
        assert len(_get_idle_resources()["unattached_volumes"]) == 3

    def test_eips_have_expected_count(self):
        assert len(_get_idle_resources()["unattached_eips"]) == 2


class TestEstimateInstanceCost:
    def test_known_type_returns_price(self):
        result = _estimate_instance_cost("m5.2xlarge")
        assert result["monthly_cost_usd"] == 280.32
        assert result["instance_type"] == "m5.2xlarge"
        assert result["region"] == "us-east-1"

    def test_hourly_times_730_equals_monthly(self):
        result = _estimate_instance_cost("c5.large")
        assert abs(result["hourly_cost_usd"] * 730 - result["monthly_cost_usd"]) < 0.01

    def test_unknown_type_returns_error(self):
        result = _estimate_instance_cost("x99.mega")
        assert "error" in result
        assert result["monthly_cost_usd"] is None

    def test_custom_region_is_preserved(self):
        result = _estimate_instance_cost("t3.micro", region="eu-west-1")
        assert result["region"] == "eu-west-1"

    def test_tool_chaining_savings_math(self):
        """The exact saving from chaining estimate_instance_cost matches the
        precomputed figure in the mock rightsizing recommendation."""
        current     = _estimate_instance_cost("m5.2xlarge")["monthly_cost_usd"]
        recommended = _estimate_instance_cost("m5.xlarge")["monthly_cost_usd"]
        assert round(current - recommended, 2) == 140.16

        current     = _estimate_instance_cost("c5.2xlarge")["monthly_cost_usd"]
        recommended = _estimate_instance_cost("c5.large")["monthly_cost_usd"]
        assert round(current - recommended, 2) == 186.15

        current     = _estimate_instance_cost("r5.2xlarge")["monthly_cost_usd"]
        recommended = _estimate_instance_cost("r5.large")["monthly_cost_usd"]
        assert round(current - recommended, 2) == 275.94


class TestEstimateEbsVolumeCost:
    def test_gp2_price_scales_with_size(self):
        result = _estimate_ebs_volume_cost("gp2", 100)
        assert result["monthly_cost_usd"] == 10.00
        assert result["price_per_gib_month_usd"] == 0.10

    def test_gp3_cheaper_than_gp2(self):
        gp2 = _estimate_ebs_volume_cost("gp2", 500)["monthly_cost_usd"]
        gp3 = _estimate_ebs_volume_cost("gp3", 500)["monthly_cost_usd"]
        assert gp3 < gp2

    def test_unknown_type_returns_error(self):
        result = _estimate_ebs_volume_cost("gp99", 100)
        assert "error" in result
        assert result["monthly_cost_usd"] is None

    def test_custom_region_is_preserved(self):
        result = _estimate_ebs_volume_cost("gp2", 8, region="eu-west-1")
        assert result["region"] == "eu-west-1"


class TestEstimateEipCost:
    def test_flat_monthly_price(self):
        result = _estimate_eip_cost()
        assert result["hourly_cost_usd"] == 0.005
        assert result["monthly_cost_usd"] == 3.65  # 0.005 * 730

    def test_same_price_in_every_region(self):
        assert (_estimate_eip_cost("eu-west-1")["monthly_cost_usd"]
                == _estimate_eip_cost("us-east-1")["monthly_cost_usd"])


class TestComputeSavingsSummary:
    def test_resize_and_delete_items_total_correctly(self):
        summary = _compute_savings_summary([
            {"label": "Resize m5.2xlarge -> m5.xlarge",
             "current_monthly_cost_usd": 280.32,
             "optimized_monthly_cost_usd": 140.16},
            {"label": "Delete vol-abc",
             "current_monthly_cost_usd": 10.00,
             "optimized_monthly_cost_usd": 0},
            {"label": "Release eipalloc-abc",
             "current_monthly_cost_usd": 3.65,
             "optimized_monthly_cost_usd": 0},
        ])
        savings = [i["monthly_saving_usd"] for i in summary["items"]]
        assert savings == [140.16, 10.00, 3.65]
        assert summary["total_monthly_savings_usd"] == 153.81

    def test_missing_optimized_cost_defaults_to_zero(self):
        summary = _compute_savings_summary([
            {"label": "Delete vol-abc", "current_monthly_cost_usd": 10.00},
        ])
        assert summary["items"][0]["monthly_saving_usd"] == 10.00

    def test_empty_input_totals_zero(self):
        summary = _compute_savings_summary([])
        assert summary["items"] == []
        assert summary["total_monthly_savings_usd"] == 0.0
