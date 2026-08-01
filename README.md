# aws-finops-agent

AWS cost-optimization agent that chains three read-only tools to find over-provisioned EC2 instances, look up live pricing, compute exact monthly savings, and surface idle resources — without mutating any infrastructure.

Built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python).

---

## Tools

| Tool | AWS API | What it does |
|------|---------|-------------|
| `get_rightsizing_recommendations` | `compute-optimizer:GetEC2InstanceRecommendations` | Over/under-provisioned EC2 instances with recommended alternatives and utilization metrics |
| `get_idle_resources` | `ec2:DescribeVolumes`, `ec2:DescribeAddresses` | Unattached EBS volumes and unassociated Elastic IPs |
| `estimate_instance_cost` | `pricing:GetProducts` | Monthly on-demand Linux price for any EC2 instance type in any region |

### Tool-chaining pattern

The agent calls `get_rightsizing_recommendations` first, then calls `estimate_instance_cost` on **both** the current and recommended types to compute the exact saving from live pricing — rather than trusting the precomputed figure in the Compute Optimizer response.

```
get_rightsizing_recommendations()
    → "m5.2xlarge → m5.xlarge (saves ~$140/mo)"

estimate_instance_cost("m5.2xlarge")   → $280.32/mo
estimate_instance_cost("m5.xlarge")    → $140.16/mo
    → exact saving: $140.16/mo  ✓
```

---

## Quick start

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run all tools directly against mock data — no LLM, no AWS credentials
MOCK_MODE=1 python -m src.agent --tools-only
```

## Full agent mode

```bash
# Uses Claude via Amazon Bedrock (default); standard AWS env vars apply,
# plus Bedrock model access/enrollment for the account
MOCK_MODE=0 python -m src.agent

# Or via the Anthropic API directly -- no AWS/Bedrock involved
MODEL_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-... MOCK_MODE=0 python -m src.agent

# Or pass a custom prompt
MOCK_MODE=0 python -m src.agent "Which instances should we resize first, prioritized by savings?"
```

## Project structure

```
src/
├── agent.py      # CLI entry-point + Strands Agent wiring
├── tools.py      # @tool functions (thin wrappers) + _underscore logic
└── mock_data.py  # AWS-shaped canned data for MOCK_MODE=1
tests/
infra/            # AWS CDK app that provisions a disposable testbed
requirements.txt
```

---

## Environment variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `MOCK_MODE` | `1` / `0` | `0` | Use canned data (`1`) or live AWS APIs (`0`) |
| `AWS_REGION` | e.g. `us-east-1` | SDK default | Region for EC2 / Compute Optimizer calls |
| `AWS_ACCESS_KEY_ID` | — | — | Explicit credentials (or use IAM role / `~/.aws`) |
| `AWS_SECRET_ACCESS_KEY` | — | — | Explicit credentials |
| `MODEL_PROVIDER` | `bedrock` / `anthropic` | `bedrock` | LLM backend for `src/agent.py` |
| `BEDROCK_MODEL_ID` | e.g. `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | see `agent.py` | Used when `MODEL_PROVIDER=bedrock` |
| `ANTHROPIC_API_KEY` | — | — | Required when `MODEL_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL_ID` | e.g. `claude-sonnet-4-5-20250929` | see `agent.py` | Used when `MODEL_PROVIDER=anthropic` |

---

## AWS IAM policy

The agent is read-only. Attach this policy to the IAM role or user running it:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FinOpsAgentReadOnly",
      "Effect": "Allow",
      "Action": [
        "compute-optimizer:GetEC2InstanceRecommendations",
        "ec2:DescribeVolumes",
        "ec2:DescribeAddresses",
        "pricing:GetProducts"
      ],
      "Resource": "*"
    }
  ]
}
```

> **Note:** The AWS Price List API (`pricing:GetProducts`) is a global endpoint only available in `us-east-1`. Pricing calls always target `us-east-1`, regardless of which region is used for EC2 operations.

---

## Design conventions

- **Read-only**: no tool mutates infrastructure.
- **Testable logic**: `_underscore` functions hold all logic; `@tool` wrappers are one-liners.
- **Model-facing descriptions**: `@tool` docstrings describe the interface for the LLM.
- **Mock/real parity**: `MOCK_MODE` is checked at the top of each `_underscore` function.
