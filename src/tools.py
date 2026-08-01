import json
import os

import boto3
from strands import tool

from src.mock_data import MOCK_EC2_PRICES, MOCK_IDLE_RESOURCES, MOCK_RIGHTSIZING_RECOMMENDATIONS

MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"
_HOURS_PER_MONTH = 730


# ---------------------------------------------------------------------------
# get_rightsizing_recommendations
# ---------------------------------------------------------------------------

def _get_rightsizing_recommendations() -> list[dict]:
    if MOCK_MODE:
        return MOCK_RIGHTSIZING_RECOMMENDATIONS
    # get_ec2_instance_recommendations has no boto3 paginator defined for it;
    # page manually via nextToken instead.
    client = boto3.client("compute-optimizer")
    recs: list[dict] = []
    next_token = None
    while True:
        kwargs = {"nextToken": next_token} if next_token else {}
        page = client.get_ec2_instance_recommendations(**kwargs)
        recs.extend(page.get("instanceRecommendations", []))
        next_token = page.get("nextToken")
        if not next_token:
            break
    return recs


@tool
def get_rightsizing_recommendations() -> str:
    """Return EC2 rightsizing recommendations from AWS Compute Optimizer.

    Each record contains:
    - instanceArn / instanceName
    - currentInstanceType
    - finding: OVER_PROVISIONED | UNDER_PROVISIONED | OPTIMIZED
    - utilizationMetrics (CPU, memory max %)
    - recommendationOptions: list of alternatives with instanceType,
      performanceRisk (0–1), and estimatedMonthlySavings

    The precomputed estimatedMonthlySavings is an approximation. Call
    estimate_instance_cost on the current and recommended types to derive
    the exact saving from live pricing data.
    """
    return json.dumps(_get_rightsizing_recommendations(), default=str)


# ---------------------------------------------------------------------------
# get_idle_resources
# ---------------------------------------------------------------------------

def _get_idle_resources() -> dict:
    if MOCK_MODE:
        return MOCK_IDLE_RESOURCES
    ec2 = boto3.client("ec2")
    volumes_resp = ec2.describe_volumes(
        Filters=[{"Name": "status", "Values": ["available"]}]
    )
    eips_resp = ec2.describe_addresses(
        Filters=[{"Name": "domain", "Values": ["vpc"]}]
    )
    unattached_eips = [
        addr
        for addr in eips_resp.get("Addresses", [])
        if "AssociationId" not in addr
    ]
    return {
        "unattached_volumes": volumes_resp.get("Volumes", []),
        "unattached_eips": unattached_eips,
    }


@tool
def get_idle_resources() -> str:
    """Return idle AWS resources that are incurring cost but not actively used.

    Scans for:
    - EBS volumes in 'available' state (created but never attached, or detached)
    - Elastic IPs allocated in a VPC but not associated with any instance or ENI

    Returns JSON with keys 'unattached_volumes' (VolumeId, Size GiB, VolumeType,
    CreateTime) and 'unattached_eips' (AllocationId, PublicIp).
    """
    return json.dumps(_get_idle_resources(), default=str)


# ---------------------------------------------------------------------------
# estimate_instance_cost
# ---------------------------------------------------------------------------

def _estimate_instance_cost(instance_type: str, region: str = "us-east-1") -> dict:
    if MOCK_MODE:
        price = MOCK_EC2_PRICES.get(instance_type)
        if price is None:
            return {
                "instance_type": instance_type,
                "region": region,
                "monthly_cost_usd": None,
                "error": f"No mock price available for '{instance_type}'. "
                         f"Known types: {sorted(MOCK_EC2_PRICES)}",
            }
        return {
            "instance_type": instance_type,
            "region": region,
            "hourly_cost_usd": round(price / _HOURS_PER_MONTH, 6),
            "monthly_cost_usd": round(price, 2),
        }

    # Pricing API is only available in us-east-1 / ap-south-1
    client = boto3.client("pricing", region_name="us-east-1")
    resp = client.get_products(
        ServiceCode="AmazonEC2",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "instanceType",    "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            {"Type": "TERM_MATCH", "Field": "regionCode",      "Value": region},
            {"Type": "TERM_MATCH", "Field": "tenancy",         "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw",  "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus",  "Value": "Used"},
        ],
        MaxResults=1,
    )
    price_list = resp.get("PriceList", [])
    if not price_list:
        return {
            "instance_type": instance_type,
            "region": region,
            "monthly_cost_usd": None,
            "error": "No pricing data returned by AWS Price List API",
        }

    price_item = json.loads(price_list[0])
    on_demand = price_item["terms"]["OnDemand"]
    offer = next(iter(on_demand.values()))
    dimension = next(iter(offer["priceDimensions"].values()))
    hourly = float(dimension["pricePerUnit"]["USD"])
    return {
        "instance_type": instance_type,
        "region": region,
        "hourly_cost_usd": hourly,
        "monthly_cost_usd": round(hourly * _HOURS_PER_MONTH, 2),
    }


@tool
def estimate_instance_cost(instance_type: str, region: str = "us-east-1") -> str:
    """Look up the monthly on-demand Linux price of an EC2 instance type via the AWS Price List API.

    Use this tool to compute exact savings from rightsizing recommendations:
    call it once for the current instance type and once for the recommended
    type, then subtract to get the precise monthly saving rather than relying
    on the precomputed figure in get_rightsizing_recommendations.

    Args:
        instance_type: EC2 instance type string, e.g. 'm5.2xlarge', 'c5.large'.
        region: AWS region code, e.g. 'us-east-1' (default), 'eu-west-1'.

    Returns JSON with instance_type, region, hourly_cost_usd, monthly_cost_usd.
    Returns an 'error' field if pricing data is unavailable for the requested type.
    """
    return json.dumps(_estimate_instance_cost(instance_type, region))
