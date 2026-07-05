# Canned AWS-shaped data used when MOCK_MODE=1.
# Shapes mirror real boto3 responses so tools stay testable without AWS credentials.

MOCK_RIGHTSIZING_RECOMMENDATIONS = [
    {
        "instanceArn": "arn:aws:ec2:us-east-1:123456789012:instance/i-0a1b2c3d4e5f67890",
        "instanceName": "web-server-prod-1",
        "currentInstanceType": "m5.2xlarge",
        "finding": "OVER_PROVISIONED",
        "utilizationMetrics": [
            {"name": "CPU", "statistic": "MAXIMUM", "value": 12.3},
            {"name": "MEMORY_USAGE", "statistic": "MAXIMUM", "value": 18.7},
        ],
        "recommendationOptions": [
            {
                "instanceType": "m5.xlarge",
                "performanceRisk": 0.1,
                "estimatedMonthlySavings": {"value": 140.16, "currency": "USD"},
            }
        ],
    },
    {
        "instanceArn": "arn:aws:ec2:us-east-1:123456789012:instance/i-0b2c3d4e5f678901a",
        "instanceName": "batch-worker-staging",
        "currentInstanceType": "c5.2xlarge",
        "finding": "OVER_PROVISIONED",
        "utilizationMetrics": [
            {"name": "CPU", "statistic": "MAXIMUM", "value": 22.5},
        ],
        "recommendationOptions": [
            {
                "instanceType": "c5.large",
                "performanceRisk": 0.2,
                "estimatedMonthlySavings": {"value": 186.15, "currency": "USD"},
            }
        ],
    },
    {
        "instanceArn": "arn:aws:ec2:us-east-1:123456789012:instance/i-0c3d4e5f6789012bc",
        "instanceName": "data-pipeline-worker",
        "currentInstanceType": "r5.2xlarge",
        "finding": "OVER_PROVISIONED",
        "utilizationMetrics": [
            {"name": "CPU", "statistic": "MAXIMUM", "value": 8.1},
            {"name": "MEMORY_USAGE", "statistic": "MAXIMUM", "value": 31.0},
        ],
        "recommendationOptions": [
            {
                "instanceType": "r5.large",
                "performanceRisk": 0.15,
                "estimatedMonthlySavings": {"value": 275.94, "currency": "USD"},
            }
        ],
    },
]

MOCK_IDLE_RESOURCES = {
    "unattached_volumes": [
        {
            "VolumeId": "vol-0a1b2c3d4e5f67890",
            "Size": 100,
            "VolumeType": "gp2",
            "CreateTime": "2024-11-15T09:22:00Z",
            "Tags": [{"Key": "Name", "Value": "old-db-snapshot-data"}],
        },
        {
            "VolumeId": "vol-0b2c3d4e5f6789012",
            "Size": 500,
            "VolumeType": "gp3",
            "CreateTime": "2024-09-03T14:07:00Z",
            "Tags": [],
        },
        {
            "VolumeId": "vol-0c3d4e5f678901234",
            "Size": 50,
            "VolumeType": "gp2",
            "CreateTime": "2025-01-20T08:45:00Z",
            "Tags": [{"Key": "Name", "Value": "temp-test-volume"}],
        },
    ],
    "unattached_eips": [
        {
            "AllocationId": "eipalloc-0a1b2c3d4e5f67890",
            "PublicIp": "54.201.100.25",
            "Domain": "vpc",
            "Tags": [{"Key": "Name", "Value": "legacy-nat-ip"}],
        },
        {
            "AllocationId": "eipalloc-0b2c3d4e5f678901",
            "PublicIp": "52.87.200.42",
            "Domain": "vpc",
            "Tags": [],
        },
    ],
}

# Monthly on-demand Linux prices for us-east-1 (730 hrs/month).
# Source: https://aws.amazon.com/ec2/pricing/on-demand/ as of 2025-01.
MOCK_EC2_PRICES: dict[str, float] = {
    "t3.micro":    7.59,
    "t3.small":   15.18,
    "t3.medium":  30.37,
    "t3.large":   60.74,
    "t3.xlarge":  121.47,
    "t3.2xlarge": 242.94,
    "m5.large":    70.08,
    "m5.xlarge":  140.16,
    "m5.2xlarge": 280.32,
    "m5.4xlarge": 560.64,
    "m5.8xlarge": 1121.28,
    "c5.large":    62.05,
    "c5.xlarge":  124.10,
    "c5.2xlarge": 248.20,
    "c5.4xlarge": 496.40,
    "r5.large":    91.98,
    "r5.xlarge":  183.96,
    "r5.2xlarge": 367.92,
    "r5.4xlarge": 735.84,
}
