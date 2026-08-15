import json
import os

import boto3
from strands import tool

from src.mock_data import (
    MOCK_EBS_PRICES_PER_GIB_MONTH,
    MOCK_EC2_PRICES,
    MOCK_IDLE_RESOURCES,
    MOCK_RIGHTSIZING_RECOMMENDATIONS,
)

MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"
_HOURS_PER_MONTH = 730

# Flat charge for every public IPv4 address (associated or not), all regions,
# since 2024-02: https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/
_PUBLIC_IPV4_HOURLY_USD = 0.005


def _first_on_demand_price(price_list: list) -> float | None:
    """Extract the on-demand USD price from a pricing:GetProducts PriceList."""
    if not price_list:
        return None
    price_item = json.loads(price_list[0])
    on_demand = price_item["terms"]["OnDemand"]
    offer = next(iter(on_demand.values()))
    dimension = next(iter(offer["priceDimensions"].values()))
    return float(dimension["pricePerUnit"]["USD"])


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
    hourly = _first_on_demand_price(resp.get("PriceList", []))
    if hourly is None:
        return {
            "instance_type": instance_type,
            "region": region,
            "monthly_cost_usd": None,
            "error": "No pricing data returned by AWS Price List API",
        }
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


# ---------------------------------------------------------------------------
# estimate_ebs_volume_cost
# ---------------------------------------------------------------------------

def _estimate_ebs_volume_cost(volume_type: str, size_gib: int, region: str = "us-east-1") -> dict:
    if MOCK_MODE:
        per_gib = MOCK_EBS_PRICES_PER_GIB_MONTH.get(volume_type)
        if per_gib is None:
            return {
                "volume_type": volume_type,
                "size_gib": size_gib,
                "region": region,
                "monthly_cost_usd": None,
                "error": f"No mock price available for volume type '{volume_type}'. "
                         f"Known types: {sorted(MOCK_EBS_PRICES_PER_GIB_MONTH)}",
            }
        return {
            "volume_type": volume_type,
            "size_gib": size_gib,
            "region": region,
            "price_per_gib_month_usd": per_gib,
            "monthly_cost_usd": round(per_gib * size_gib, 2),
        }

    client = boto3.client("pricing", region_name="us-east-1")
    resp = client.get_products(
        ServiceCode="AmazonEC2",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"},
            {"Type": "TERM_MATCH", "Field": "volumeApiName",  "Value": volume_type},
            {"Type": "TERM_MATCH", "Field": "regionCode",     "Value": region},
        ],
        MaxResults=1,
    )
    per_gib = _first_on_demand_price(resp.get("PriceList", []))
    if per_gib is None:
        return {
            "volume_type": volume_type,
            "size_gib": size_gib,
            "region": region,
            "monthly_cost_usd": None,
            "error": "No pricing data returned by AWS Price List API",
        }
    return {
        "volume_type": volume_type,
        "size_gib": size_gib,
        "region": region,
        "price_per_gib_month_usd": per_gib,
        "monthly_cost_usd": round(per_gib * size_gib, 2),
    }


@tool
def estimate_ebs_volume_cost(volume_type: str, size_gib: int, region: str = "us-east-1") -> str:
    """Look up the monthly storage cost of an EBS volume via the AWS Price List API.

    Use this to price every unattached volume reported by get_idle_resources
    (deleting an unattached volume saves its full monthly cost).

    Args:
        volume_type: EBS volume type, e.g. 'gp2', 'gp3', 'io1', 'st1'.
        size_gib: Volume size in GiB, as reported in the volume's 'Size' field.
        region: AWS region code, e.g. 'us-east-1' (default).

    Returns JSON with volume_type, size_gib, region, price_per_gib_month_usd,
    monthly_cost_usd. Returns an 'error' field if pricing data is unavailable.
    """
    return json.dumps(_estimate_ebs_volume_cost(volume_type, size_gib, region))


# ---------------------------------------------------------------------------
# estimate_eip_cost
# ---------------------------------------------------------------------------

def _estimate_eip_cost(region: str = "us-east-1") -> dict:
    # AWS bills every public IPv4 address a flat $0.005/hour in all regions
    # (whether or not it is associated), so mock and real mode are identical
    # and no MOCK_MODE branch is needed.
    return {
        "region": region,
        "hourly_cost_usd": _PUBLIC_IPV4_HOURLY_USD,
        "monthly_cost_usd": round(_PUBLIC_IPV4_HOURLY_USD * _HOURS_PER_MONTH, 2),
        "note": "Flat public-IPv4 charge; applies to every allocated Elastic IP, "
                "associated or not, since February 2024.",
    }


@tool
def estimate_eip_cost(region: str = "us-east-1") -> str:
    """Return the monthly cost of one Elastic IP (public IPv4 address).

    AWS charges a flat rate per public IPv4 address in all regions, whether or
    not the address is associated with an instance. Use this to price every
    unassociated Elastic IP reported by get_idle_resources (releasing one saves
    its full monthly cost).

    Args:
        region: AWS region code, e.g. 'us-east-1' (default). Informational only;
            the rate is the same in every region.

    Returns JSON with region, hourly_cost_usd, monthly_cost_usd.
    """
    return json.dumps(_estimate_eip_cost(region))


# ---------------------------------------------------------------------------
# compute_savings_summary
# ---------------------------------------------------------------------------

def _compute_savings_summary(line_items: list[dict]) -> dict:
    items = []
    total = 0.0
    for item in line_items:
        current = float(item.get("current_monthly_cost_usd", 0.0))
        optimized = float(item.get("optimized_monthly_cost_usd", 0.0))
        saving = round(current - optimized, 2)
        total += saving
        items.append({
            "label": item.get("label", ""),
            "current_monthly_cost_usd": round(current, 2),
            "optimized_monthly_cost_usd": round(optimized, 2),
            "monthly_saving_usd": saving,
        })
    return {"items": items, "total_monthly_savings_usd": round(total, 2)}


@tool
def compute_savings_summary(line_items: list[dict]) -> str:
    """Compute per-item and total monthly savings deterministically.

    Always use this tool for dollar arithmetic instead of computing sums or
    differences yourself. Pass one line item per finding, using only figures
    previously returned by the pricing tools:

    Args:
        line_items: List of dicts, each with:
            - label (str): short description, e.g. 'Resize web-server-prod-1
              m5.2xlarge -> m5.xlarge' or 'Delete vol-0a1b2c3d4e5f67890'.
            - current_monthly_cost_usd (float): what the resource costs today.
            - optimized_monthly_cost_usd (float): cost after the action
              (the recommended type's monthly cost for a resize; 0 for a
              deletion or release).

    Returns JSON with 'items' (each including monthly_saving_usd) and
    'total_monthly_savings_usd'.
    """
    return json.dumps(_compute_savings_summary(line_items))
