"""Disposable testbed for the aws-finops-agent.

Creates exactly what the agent's three read-only tools need to find something:
- An idle EC2 instance (t3.micro, free-tier eligible) sitting at near-zero
  utilization so Compute Optimizer flags it as OVER_PROVISIONED.
- An EBS volume that is created but never attached to anything.
- An Elastic IP that is allocated but never associated with anything.

Compute Optimizer account enrollment has no CloudFormation resource, so it isn't
done here -- run this once, separately, before deploying:
    aws compute-optimizer update-enrollment-status --status Active
Recommendations still take ~24-48h of CloudWatch data to appear after the
instance starts running, regardless.

Nothing here is meant to be long-lived. Run `cdk destroy` once you've
finished testing the agent against it.
"""

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Size,
    Stack,
    Tags,
    aws_budgets as budgets,
    aws_ec2 as ec2,
    aws_iam as iam,
)
from constructs import Construct

BUDGET_LIMIT_USD = 25
BUDGET_ALERT_EMAIL = "brahimserghini2@gmail.com"


class FinOpsTestbedStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        Tags.of(self).add("Project", "finops-agent-testbed")

        self._add_budget_alarm()

        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        security_group = ec2.SecurityGroup(
            self,
            "IdleInstanceSg",
            vpc=vpc,
            description="No inbound rules; outbound only for SSM connectivity.",
            allow_all_outbound=True,
        )

        instance = ec2.Instance(
            self,
            "IdleInstance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3, ec2.InstanceSize.MICRO
            ),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            security_group=security_group,
            # Public IP + SSM so you can inspect the box without an SSH key/bastion.
            associate_public_ip_address=True,
        )
        instance.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
        )
        instance.apply_removal_policy(RemovalPolicy.DESTROY)

        idle_volume = ec2.Volume(
            self,
            "IdleVolume",
            availability_zone=instance.instance_availability_zone,
            size=Size.gibibytes(8),
            removal_policy=RemovalPolicy.DESTROY,
        )
        # Intentionally never attached to `instance` -- this is what
        # get_idle_resources is supposed to find.

        idle_eip = ec2.CfnEIP(self, "IdleEip", domain="vpc")
        # Intentionally never associated to an instance/ENI.

        CfnOutput(self, "InstanceId", value=instance.instance_id)
        CfnOutput(self, "IdleVolumeId", value=idle_volume.volume_id)
        CfnOutput(self, "IdleEipAllocationId", value=idle_eip.attr_allocation_id)
        CfnOutput(self, "IdleEipPublicIp", value=idle_eip.ref)

    def _add_budget_alarm(self) -> None:
        """Email BUDGET_ALERT_EMAIL at 80% actual and 100% forecasted monthly spend."""
        subscriber = budgets.CfnBudget.SubscriberProperty(
            subscription_type="EMAIL",
            address=BUDGET_ALERT_EMAIL,
        )
        budgets.CfnBudget(
            self,
            "MonthlyBudgetAlarm",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=BUDGET_LIMIT_USD,
                    unit="USD",
                ),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=80,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[subscriber],
                ),
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="FORECASTED",
                        comparison_operator="GREATER_THAN",
                        threshold=100,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[subscriber],
                ),
            ],
        )
