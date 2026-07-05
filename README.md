# aws-finops-agent

AWS cost-optimization agent that chains three read-only tools to find over-provisioned EC2 instances, look up live pricing, compute exact monthly savings, and surface idle resources — without mutating any infrastructure.

Available in two implementations that mirror each other exactly:

| | Python | Java |
|---|---|---|
| Framework | [Strands Agents SDK](https://github.com/strands-agents/sdk-python) | [Spring AI](https://docs.spring.io/spring-ai/reference/) |
| Entry point | `src/agent.py` | `java/src/main/java/com/finops/agent/FinOpsAgentApplication.java` |
| Tools file | `src/tools.py` | `java/src/main/java/com/finops/agent/FinOpsTools.java` |
| Mock data | `src/mock_data.py` | `java/src/main/java/com/finops/agent/MockData.java` |

---

## Tools

Both implementations expose the same three tools:

| Tool | AWS API | What it does |
|------|---------|-------------|
| `get_rightsizing_recommendations` / `getRightsizingRecommendations` | `compute-optimizer:GetEC2InstanceRecommendations` | Over/under-provisioned EC2 instances with recommended alternatives and utilization metrics |
| `get_idle_resources` / `getIdleResources` | `ec2:DescribeVolumes`, `ec2:DescribeAddresses` | Unattached EBS volumes and unassociated Elastic IPs |
| `estimate_instance_cost` / `estimateInstanceCost` | `pricing:GetProducts` | Monthly on-demand Linux price for any EC2 instance type in any region |

### Tool-chaining pattern

The agent calls `getRightsizingRecommendations` first, then calls `estimateInstanceCost` on **both** the current and recommended types to compute the exact saving from live pricing — rather than trusting the precomputed figure in the Compute Optimizer response.

```
getRightsizingRecommendations()
    → "m5.2xlarge → m5.xlarge (saves ~$140/mo)"

estimateInstanceCost("m5.2xlarge")   → $280.32/mo
estimateInstanceCost("m5.xlarge")    → $140.16/mo
    → exact saving: $140.16/mo  ✓
```

---

## Python implementation (Strands Agents SDK)

### Quick start

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run all tools directly against mock data — no LLM, no AWS credentials
MOCK_MODE=1 python -m src.agent --tools-only
```

### Full agent mode

```bash
# Uses Claude 3.5 Sonnet via Amazon Bedrock; standard AWS env vars apply
MOCK_MODE=0 python -m src.agent

# Or pass a custom prompt
MOCK_MODE=0 python -m src.agent "Which instances should we resize first, prioritized by savings?"
```

### Project structure

```
src/
├── agent.py      # CLI entry-point + Strands Agent wiring
├── tools.py      # @tool functions (thin wrappers) + _underscore logic
└── mock_data.py  # AWS-shaped canned data for MOCK_MODE=1
requirements.txt
```

---

## Java implementation (Spring AI)

### Prerequisites

- Java 17+
- Maven 3.8+ (`brew install maven` on macOS)

### Quick start

```bash
cd java

# Run all tools directly against mock data — no LLM, no AWS credentials
MOCK_MODE=1 mvn spring-boot:run -Dspring-boot.run.arguments="--tools-only"
```

### Full agent mode

```bash
# Uses Claude 3.5 Sonnet via Amazon Bedrock; standard AWS env vars apply
cd java
MOCK_MODE=0 mvn spring-boot:run

# Or pass a custom prompt
MOCK_MODE=0 mvn spring-boot:run -Dspring-boot.run.arguments="Which instances should we resize first?"
```

### Build a fat JAR

```bash
cd java
mvn package -q
MOCK_MODE=1 java -jar target/aws-finops-agent-0.1.0.jar --tools-only
```

### Project structure

```
java/
├── pom.xml
└── src/main/
    ├── java/com/finops/agent/
    │   ├── FinOpsAgentApplication.java  # CLI entry-point + Spring AI agent wiring
    │   ├── FinOpsTools.java             # @Tool methods (thin wrappers) + fetch* logic
    │   └── MockData.java                # AWS-shaped canned data for MOCK_MODE=1
    └── resources/
        └── application.properties       # Bedrock model + logging config
```

---

## Environment variables

Both implementations share the same variables:

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `MOCK_MODE` | `1` / `0` | `0` | Use canned data (`1`) or live AWS APIs (`0`) |
| `AWS_REGION` | e.g. `us-east-1` | SDK default | Region for EC2 / Compute Optimizer calls |
| `AWS_ACCESS_KEY_ID` | — | — | Explicit credentials (or use IAM role / `~/.aws`) |
| `AWS_SECRET_ACCESS_KEY` | — | — | Explicit credentials |

---

## AWS IAM policy

The agent is read-only. Attach this policy to the IAM role or user running either implementation:

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

> **Note:** The AWS Price List API (`pricing:GetProducts`) is a global endpoint only available in `us-east-1`. Both implementations always target `us-east-1` for pricing calls, regardless of which region is used for EC2 operations.

---

## Design conventions (both implementations)

| Convention | Python | Java |
|---|---|---|
| **Read-only** | No tool mutates infrastructure | Same |
| **Testable logic** | `_underscore` functions hold all logic; `@tool` wrappers are one-liners | `fetch*()` package-private methods; `@Tool` public wrappers are one-liners |
| **Model-facing descriptions** | `@tool` docstrings describe the interface for the LLM | `@Tool(description = "...")` text blocks describe the interface for the LLM |
| **Mock/real parity** | `MOCK_MODE` checked at the top of each `_underscore` function | `MOCK_MODE` checked at the top of each `fetch*()` method |
| **No Spring context in tools-only** | N/A (Python has no DI framework) | `--tools-only` exits `main()` before `SpringApplication.run()` — no Bedrock config needed |
