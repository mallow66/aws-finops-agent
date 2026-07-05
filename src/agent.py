"""AWS FinOps cost-optimization agent.

Run modes
---------
--tools-only   Call each tool's underlying logic directly; no LLM involved.
               Useful for CI, debugging, and demos without Bedrock access.
(default)      Send a prompt to a Strands + Bedrock agent that has all three
               tools available and can chain them autonomously.
"""

import argparse
import json
import sys

from src.tools import (
    _estimate_instance_cost,
    _get_idle_resources,
    _get_rightsizing_recommendations,
    estimate_instance_cost,
    get_idle_resources,
    get_rightsizing_recommendations,
)

_AGENT_TOOLS = [get_rightsizing_recommendations, get_idle_resources, estimate_instance_cost]

_DEFAULT_PROMPT = (
    "Analyze our AWS spend. "
    "Call get_rightsizing_recommendations to find over-provisioned instances. "
    "For each recommendation, call estimate_instance_cost on the current instance "
    "type and on the recommended type, then compute the exact monthly saving "
    "yourself instead of trusting the precomputed figure. "
    "Also call get_idle_resources and report unattached EBS volumes and Elastic IPs. "
    "Finish with a prioritized summary and a total estimated monthly savings figure."
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


def _run_agent(prompt: str) -> None:
    try:
        from strands import Agent
        from strands.models.bedrock import BedrockModel
    except ImportError:
        print(
            "strands-agents is not installed. Run: pip install strands-agents",
            file=sys.stderr,
        )
        sys.exit(1)

    model = BedrockModel(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0")
    agent = Agent(model=model, tools=_AGENT_TOOLS)
    agent(prompt)


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
