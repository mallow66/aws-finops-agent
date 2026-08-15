"""AWS FinOps cost-optimization agent.

Run modes
---------
--tools-only   Call each tool's underlying logic directly; no LLM involved.
               Useful for CI, debugging, and demos without any LLM access.
(default)      Send a prompt to a Strands agent that has all the tools
               available and can chain them autonomously. MODEL_PROVIDER
               selects which LLM backend it talks to (see _run_agent).
"""

import argparse
import json
import os
import sys

from src.tools import (
    _compute_savings_summary,
    _estimate_ebs_volume_cost,
    _estimate_eip_cost,
    _estimate_instance_cost,
    _get_idle_resources,
    _get_rightsizing_recommendations,
    compute_savings_summary,
    estimate_ebs_volume_cost,
    estimate_eip_cost,
    estimate_instance_cost,
    get_idle_resources,
    get_rightsizing_recommendations,
)

_AGENT_TOOLS = [
    get_rightsizing_recommendations,
    get_idle_resources,
    estimate_instance_cost,
    estimate_ebs_volume_cost,
    estimate_eip_cost,
    compute_savings_summary,
]

_DEFAULT_PROMPT = (
    "Analyze our AWS spend. "
    "Call get_rightsizing_recommendations to find over-provisioned instances. "
    "For each recommendation that has options, call estimate_instance_cost on the "
    "current type and on each recommended type. "
    "Call get_idle_resources; price every unattached EBS volume with "
    "estimate_ebs_volume_cost and every unassociated Elastic IP with estimate_eip_cost. "
    "Do not do any dollar arithmetic yourself: build one line item per finding from "
    "the tool-reported figures, pass them all to compute_savings_summary, and report "
    "its per-item savings and total verbatim. "
    "If something cannot be priced with these tools, label it 'unpriced' instead of "
    "estimating a figure from memory. "
    "Finish with a prioritized summary and the tool-computed total monthly savings."
)


def _print_section(title: str, data) -> None:
    bar = "=" * 62
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)
    print(json.dumps(data, indent=2, default=str))


def _run_tools_only() -> None:
    recs = _get_rightsizing_recommendations()
    _print_section("Rightsizing Recommendations", recs)

    idle = _get_idle_resources()
    _print_section("Idle Resources", idle)

    # Derive every instance type mentioned in the recommendations and price them.
    seen: set[str] = set()
    for rec in recs:
        seen.add(rec.get("currentInstanceType", ""))
        for opt in rec.get("recommendationOptions", []):
            seen.add(opt.get("instanceType", ""))
    seen.discard("")

    for itype in sorted(seen):
        cost = _estimate_instance_cost(itype)
        _print_section(f"Pricing: {itype}", cost)

    # Price the idle resources and roll everything up deterministically.
    line_items: list[dict] = []
    for vol in idle.get("unattached_volumes", []):
        cost = _estimate_ebs_volume_cost(vol.get("VolumeType", ""), vol.get("Size", 0))
        _print_section(f"Pricing: EBS {vol.get('VolumeId', '?')}", cost)
        if cost.get("monthly_cost_usd") is not None:
            line_items.append({
                "label": f"Delete {vol.get('VolumeId', '?')}",
                "current_monthly_cost_usd": cost["monthly_cost_usd"],
                "optimized_monthly_cost_usd": 0,
            })

    eips = idle.get("unattached_eips", [])
    if eips:
        eip_cost = _estimate_eip_cost()
        _print_section("Pricing: Elastic IP (per address)", eip_cost)
        for eip in eips:
            line_items.append({
                "label": f"Release {eip.get('AllocationId', '?')}",
                "current_monthly_cost_usd": eip_cost["monthly_cost_usd"],
                "optimized_monthly_cost_usd": 0,
            })

    _print_section("Savings Summary (idle resources)", _compute_savings_summary(line_items))


def _build_model():
    """Build the Strands model for MODEL_PROVIDER ('bedrock' or 'anthropic').

    bedrock (default): Amazon Bedrock, model id from BEDROCK_MODEL_ID.
        Needs AWS credentials plus Bedrock model access/enrollment.
    anthropic: Anthropic API directly, model id from ANTHROPIC_MODEL_ID.
        Needs ANTHROPIC_API_KEY; no AWS involvement at all.
    """
    provider = os.getenv("MODEL_PROVIDER", "bedrock")

    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
            sys.exit(1)
        model_id = os.getenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-5-20250929")
        # max_tokens is required by AnthropicModel; it is only read when the
        # first request is formatted, so omitting it fails mid-run, not here.
        max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192"))
        return AnthropicModel(
            client_args={"api_key": api_key},
            model_id=model_id,
            max_tokens=max_tokens,
        )

    from strands.models.bedrock import BedrockModel

    model_id = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    return BedrockModel(model_id=model_id)


def _run_agent(prompt: str) -> None:
    try:
        from strands import Agent
    except ImportError:
        print(
            "strands-agents is not installed. Run: pip install strands-agents",
            file=sys.stderr,
        )
        sys.exit(1)

    from strands.types.exceptions import ModelThrottledException

    model = _build_model()
    agent = Agent(model=model, tools=_AGENT_TOOLS)
    try:
        agent(prompt)
    except ModelThrottledException as exc:
        # The SDK already exhausted its own retries by this point, so a raw
        # traceback here is just noise — the fix is on the account, not in code.
        print(f"\nModel is throttled and retries are exhausted: {exc}", file=sys.stderr)
        print(
            "Wait for the quota to reset, switch provider with MODEL_PROVIDER=anthropic, "
            "or run 'python -m src.agent --tools-only' to exercise the tools without an LLM.",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AWS FinOps cost-optimization agent powered by Strands + Bedrock.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tools-only",
        action="store_true",
        help="Run tools directly without the LLM (no Bedrock required).",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=_DEFAULT_PROMPT,
        help="Question or instruction to send to the agent (ignored with --tools-only).",
    )
    args = parser.parse_args()

    if args.tools_only:
        _run_tools_only()
    else:
        _run_agent(args.prompt)


if __name__ == "__main__":
    main()
