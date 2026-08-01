#!/usr/bin/env python3
import os

import aws_cdk as cdk

from finops_agent_infra.finops_stack import FinOpsTestbedStack

app = cdk.App()

FinOpsTestbedStack(
    app,
    "FinOpsAgentTestbed",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)

app.synth()
