# aws-finops-agent

An AWS cost-optimization agent built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and Amazon Bedrock (Claude). The agent chains three read-only tools to find over-provisioned EC2 instances, look up live pricing, compute exact monthly savings, and surface idle resources — all without mutating any infrastructure.

## Tools

| Tool | API | What it does |
|------|-----|-------------|
| `get_rightsizing_recommendations` | `compute-optimizer:GetEC2InstanceRecommendations` | Returns over/under-provisioned EC2 instances with recommended alternatives and utilization metrics |
| `get_idle_resources` | `ec2:DescribeVolumes`, `ec2:DescribeAddresses` | Returns unattached EBS volumes and unassociated Elastic IPs |
| `estimate_instance_cost` | `pricing:GetProducts` | Looks up the monthly on-demand Linux price for any EC2 instance type in any region |

### Tool-chaining pattern

The agent calls `get_rightsizing_recommendations` first, then calls `estimate_instance_cost` on **both** the current and recommended instance types to compute the exact monthly saving from live pricing — rather than trusting the precomputed figure bundled in the Compute Optimizer response.

```
get_rightsizing_recommendations()
    → "m5.2xlarge → m5.xlarge (saves ~$140/mo)"

estimate_instance_cost("m5.2xlarge")   → $280.32/mo
estimate_instance_cost("m5.xlarge")    → $140.16/mo
    → exact saving: $140.16/mo  ✓
```

## Quick start (no AWS required)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run all tools directly against mock data — no LLM, no AWS credentials
MOCK_MODE=1 python -m src.agent --tools-only
```

## Full agent mode (requires Bedrock access)

```bash
# Uses Claude 3.5 Sonnet via Amazon Bedrock; standard AWS env vars apply
MOCK_MODE=0 python -m src.agent

# Or pass a custom prompt
MOCK_MODE=0 python -m src.agent "Which instances should we resize first, prioritized by savings?"
```

## Environment variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `MOCK_MODE` | `1` / `0` | `0` | Use canned data (`1`) or live AWS APIs (`0`) |
| `AWS_REGION` | e.g. `us-east-1` | boto3 default | AWS region for EC2 / Compute Optimizer calls |

## AWS IAM policy

The agent is read-only. Attach this policy to the IAM role or user running the agent:

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

> **Note:** The AWS Price List API (`pricing:GetProducts`) is a global service endpoint hosted in `us-east-1`. The boto3 client in `tools.py` always targets `us-east-1` for pricing calls regardless of the region used for EC2 operations.

## Project structure

```
src/
├── agent.py      # CLI entry-point + Strands Agent wiring
├── tools.py      # @tool functions (thin wrappers) + _underscore logic
└── mock_data.py  # AWS-shaped canned data for MOCK_MODE=1
requirements.txt
```

### Design conventions

- **Read-only** — no tool mutates infrastructure.
- **Testable logic** — tool logic lives in plain `_underscore` functions; `@tool` wrappers are one-liners so the logic is importable and testable without a Strands runtime.
- **Model-facing docstrings** — `@tool` docstrings describe the tool interface for the LLM, not for human readers.
- **MOCK_MODE** — all three tools branch on `MOCK_MODE=1` at the top of their logic function, keeping mock and real paths structurally identical.
