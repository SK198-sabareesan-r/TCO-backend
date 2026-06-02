import os
import json
import boto3
from functools import lru_cache
from dotenv import load_dotenv
from config.secrets import get_secret, get_aws_session

load_dotenv()

# =========================================================
# AWS PRICING CLIENT
# =========================================================
# Credentials resolved via: Secrets Manager → .env → default chain
_session = get_aws_session()
pricing_client      = _session.client("pricing",      region_name="us-east-1")
savingsplans_client = _session.client("savingsplans", region_name="us-east-1")
ec2_client          = _session.client("ec2",          region_name="us-east-1")

HOURS_PER_MONTH = 730


# =========================================================
# INSTANCE SPECS MAPPING (vCPU + Memory)
# =========================================================
INSTANCE_SPECS = {
    # T3 - Burstable
    "t3.nano":    {"vcpu": 2, "memory": 0.5},
    "t3.micro":   {"vcpu": 2, "memory": 1},
    "t3.small":   {"vcpu": 2, "memory": 2},
    "t3.medium":  {"vcpu": 2, "memory": 4},
    "t3.large":   {"vcpu": 2, "memory": 8},
    "t3.xlarge":  {"vcpu": 4, "memory": 16},
    "t3.2xlarge": {"vcpu": 8, "memory": 32},

    # T3a - Burstable AMD
    "t3a.nano":    {"vcpu": 2, "memory": 0.5},
    "t3a.micro":   {"vcpu": 2, "memory": 1},
    "t3a.small":   {"vcpu": 2, "memory": 2},
    "t3a.medium":  {"vcpu": 2, "memory": 4},
    "t3a.large":   {"vcpu": 2, "memory": 8},
    "t3a.xlarge":  {"vcpu": 4, "memory": 16},
    "t3a.2xlarge": {"vcpu": 8, "memory": 32},

    # M5 - General Purpose
    "m5.large":    {"vcpu": 2,  "memory": 8},
    "m5.xlarge":   {"vcpu": 4,  "memory": 16},
    "m5.2xlarge":  {"vcpu": 8,  "memory": 32},
    "m5.4xlarge":  {"vcpu": 16, "memory": 64},
    "m5.8xlarge":  {"vcpu": 32, "memory": 128},
    "m5.12xlarge": {"vcpu": 48, "memory": 192},
    "m5.16xlarge": {"vcpu": 64, "memory": 256},
    "m5.24xlarge": {"vcpu": 96, "memory": 384},

    # M6i - General Purpose (Intel)
    "m6i.large":   {"vcpu": 2,  "memory": 8},
    "m6i.xlarge":  {"vcpu": 4,  "memory": 16},
    "m6i.2xlarge": {"vcpu": 8,  "memory": 32},
    "m6i.4xlarge": {"vcpu": 16, "memory": 64},
    "m6i.8xlarge": {"vcpu": 32, "memory": 128},

    # C5 - Compute Optimized
    "c5.large":    {"vcpu": 2,  "memory": 4},
    "c5.xlarge":   {"vcpu": 4,  "memory": 8},
    "c5.2xlarge":  {"vcpu": 8,  "memory": 16},
    "c5.4xlarge":  {"vcpu": 16, "memory": 32},
    "c5.9xlarge":  {"vcpu": 36, "memory": 72},
    "c5.12xlarge": {"vcpu": 48, "memory": 96},
    "c5.18xlarge": {"vcpu": 72, "memory": 144},
    "c5.24xlarge": {"vcpu": 96, "memory": 192},

    # R5 - Memory Optimized
    "r5.large":    {"vcpu": 2,  "memory": 16},
    "r5.xlarge":   {"vcpu": 4,  "memory": 32},
    "r5.2xlarge":  {"vcpu": 8,  "memory": 64},
    "r5.4xlarge":  {"vcpu": 16, "memory": 128},
    "r5.8xlarge":  {"vcpu": 32, "memory": 256},
    "r5.12xlarge": {"vcpu": 48, "memory": 384},
    "r5.16xlarge": {"vcpu": 64, "memory": 512},
    "r5.24xlarge": {"vcpu": 96, "memory": 768},
}


# =========================================================
# REGION CODE MAPPING (for Savings Plans API)
# =========================================================
REGION_NAME_TO_CODE = {
    "US East (N. Virginia)":   "us-east-1",
    "US East (Ohio)":          "us-east-2",
    "US West (N. California)": "us-west-1",
    "US West (Oregon)":        "us-west-2",
    "Asia Pacific (Mumbai)":   "ap-south-1",
    "Asia Pacific (Singapore)":"ap-southeast-1",
    "Asia Pacific (Sydney)":   "ap-southeast-2",
    "Asia Pacific (Tokyo)":    "ap-northeast-1",
    "Asia Pacific (Seoul)":    "ap-northeast-2",
    "Europe (Ireland)":        "eu-west-1",
    "Europe (Frankfurt)":      "eu-central-1",
    "Europe (London)":         "eu-west-2",
    "Europe (Paris)":          "eu-west-3",
    "Canada (Central)":        "ca-central-1",
    "South America (Sao Paulo)":"sa-east-1",
}


# =========================================================
# FETCH INSTANCE SPECS FROM AWS
# =========================================================
@lru_cache(maxsize=512)
def get_instance_specs(instance_type: str):
    """
    Get vCPU and memory for an instance type.
    First checks INSTANCE_SPECS, then fetches from AWS EC2 API.
    """
    if instance_type in INSTANCE_SPECS:
        return INSTANCE_SPECS[instance_type]

    try:
        response = ec2_client.describe_instance_types(InstanceTypes=[instance_type])
        if response["InstanceTypes"]:
            info = response["InstanceTypes"][0]
            specs = {
                "vcpu":   info["VCpuInfo"]["DefaultVCpus"],
                "memory": info["MemoryInfo"]["SizeInMiB"] / 1024,
            }
            print(f"Fetched specs for {instance_type}: {specs}")
            return specs
    except Exception as e:
        print(f"Error fetching instance specs for {instance_type}: {str(e)}")

    return None


# =========================================================
# ON-DEMAND PRICE
# =========================================================
@lru_cache(maxsize=256)
def get_ondemand_price(instance_type: str, region: str, operating_system: str = "Linux", tenancy: str = "Shared"):
    """
    Get on-demand pricing for EC2 instances.
    
    Parameters:
    - instance_type: EC2 instance type (e.g., t3.medium)
    - region: AWS region name (e.g., "US East (N. Virginia)")
    - operating_system: Linux, Windows, RHEL, SUSE (default: Linux)
    - tenancy: Shared, Dedicated, Host (default: Shared)
    """
    try:
        response = pricing_client.get_products(
            ServiceCode="AmazonEC2",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType",    "Value": instance_type},
                {"Type": "TERM_MATCH", "Field": "location",        "Value": region},
                {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
                {"Type": "TERM_MATCH", "Field": "tenancy",         "Value": tenancy},
                {"Type": "TERM_MATCH", "Field": "capacitystatus",  "Value": "Used"},
                {"Type": "TERM_MATCH", "Field": "preInstalledSw",  "Value": "NA"},
            ],
            MaxResults=1,
        )

        if not response["PriceList"]:
            return None

        price_item = json.loads(response["PriceList"][0])
        for term in price_item["terms"]["OnDemand"].values():
            for dim in term["priceDimensions"].values():
                return float(dim["pricePerUnit"]["USD"])

    except Exception as e:
        print("On-Demand pricing error:", str(e))

    return None


# =========================================================
# SPOT INSTANCE PRICE
# =========================================================
@lru_cache(maxsize=256)
def get_spot_price(instance_type: str, region: str):
    """
    Get current spot instance price from AWS EC2 API.
    Returns the latest spot price for Linux instances.
    """
    try:
        region_code = REGION_NAME_TO_CODE.get(region)
        if not region_code:
            print(f"Region code not found for: {region}")
            return None

        # Build a per-region EC2 client using the same resolved session
        ec2_regional = _session.client("ec2", region_name=region_code)

        response = ec2_regional.describe_spot_price_history(
            InstanceTypes=[instance_type],
            ProductDescriptions=["Linux/UNIX"],
            MaxResults=1,
        )

        if response["SpotPriceHistory"]:
            spot_price = float(response["SpotPriceHistory"][0]["SpotPrice"])
            print(f"Spot price for {instance_type} in {region_code}: ${spot_price}/hr")
            return spot_price

        print(f"No spot price found for {instance_type} in {region_code}")
        return None

    except Exception as e:
        print(f"Spot pricing error: {str(e)}")
        return None


# =========================================================
# COMPUTE SAVINGS PLAN RATE
# =========================================================
@lru_cache(maxsize=256)
def get_csp_rate(instance_type: str, region: str, plan_type: str):
    """
    Get real Compute Savings Plan rate from AWS Savings Plans API.
    Matches offers by instance type directly.
    Returns tuple: (hourly_rate, upfront_fee, offering_id)
    """
    try:
        print(f"Looking for CSP rate: {instance_type} in {region}")

        payment_map = {
            "no_upfront":      "No Upfront",
            "partial_upfront": "Partial Upfront",
            "all_upfront":     "All Upfront",
        }

        term, payment = plan_type.split("_", 1)
        payment_option = payment_map.get(payment)

        if not payment_option:
            print(f"Invalid plan_type: {plan_type}")
            return None

        region_code = REGION_NAME_TO_CODE.get(region)
        if not region_code:
            print(f"Region code not found for: {region}")
            return None

        best_rate   = None
        best_offering = None
        next_token  = None
        total_checked = 0

        while True:
            params = {
                "savingsPlanTypes":          ["Compute"],
                "products":                  ["EC2"],
                "savingsPlanPaymentOptions": [payment_option],
                "filters": [
                    {"name": "region", "values": [region_code]},
                    {"name": "tenancy", "values": ["shared"]},
                    {"name": "productDescription", "values": ["Linux/UNIX"]},
                    {"name": "instanceType", "values": [instance_type]},
                ],
                "maxResults": 1000,
            }

            if next_token:
                params["nextToken"] = next_token

            response = savingsplans_client.describe_savings_plans_offering_rates(**params)

            for offer in response.get("searchResults", []):
                total_checked += 1
                properties = offer.get("properties", [])
                prop_dict  = {p["name"]: p["value"] for p in properties}

                # Verify instance type matches
                offer_instance_type = prop_dict.get("instanceType")
                if offer_instance_type != instance_type:
                    continue

                # Check if this offer matches the desired term (1yr or 3yr)
                offering_details = offer.get("savingsPlanOffering", {})
                offer_duration = offering_details.get("durationSeconds")
                if offer_duration:
                    duration_years = int(offer_duration) / 31536000
                    expected_years = 3 if term == "3yr" else 1
                    if abs(duration_years - expected_years) > 0.1:
                        continue

                rate = float(offer.get("rate", 0))
                if rate > 0:
                    if best_rate is None or rate < best_rate:
                        best_rate = rate
                        best_offering = offer
                        print(f"  Found matching offer: {instance_type}, {term} = ${rate}/hr")

            next_token = response.get("nextToken")
            if not next_token:
                break

        print(f"Checked {total_checked} CSP offers")

        if best_rate and best_offering:
            print(f"✅ Best CSP rate for {instance_type} in {region_code}: ${best_rate}/hr")
            
            # Get offering ID to fetch upfront details
            offering_id = best_offering.get("savingsPlanOffering", {}).get("offeringId")
            
            # Try to get upfront fee from offering details
            upfront_fee = 0
            if offering_id:
                try:
                    offering_response = savingsplans_client.describe_savings_plans_offerings(
                        offeringIds=[offering_id]
                    )
                    if offering_response.get("searchResults"):
                        offering_info = offering_response["searchResults"][0]
                        # Upfront fee is typically in the properties
                        for prop in offering_info.get("properties", []):
                            if prop.get("name") == "upfrontFee":
                                upfront_fee = float(prop.get("value", 0))
                                break
                except Exception as e:
                    print(f"Could not fetch upfront fee: {str(e)}")
            
            return (best_rate, upfront_fee, offering_id)
        else:
            print(f"❌ No matching CSP rate found for {instance_type}")
            return None

    except Exception as e:
        print(f"CSP API error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


# =========================================================
# RESERVED INSTANCES PRICING (for Dedicated tenancy)
# =========================================================
@lru_cache(maxsize=256)
def get_reserved_instance_price(
    instance_type: str,
    region: str,
    term: str = "1yr",
    payment_option: str = "No Upfront",
    offering_class: str = "standard",
    operating_system: str = "Linux",
    tenancy: str = "Dedicated",
):
    """
    Get Reserved Instance pricing from AWS Pricing API.
    
    Parameters:
    - term: "1yr" or "3yr"
    - payment_option: "No Upfront", "Partial Upfront", "All Upfront"
    - offering_class: "standard" or "convertible"
    """
    try:
        # Map term to lease contract length
        lease_length_map = {
            "1yr": "1yr",
            "3yr": "3yr",
        }
        
        lease_length = lease_length_map.get(term, "1yr")
        offering_class_value = offering_class.capitalize()
        
        response = pricing_client.get_products(
            ServiceCode="AmazonEC2",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                {"Type": "TERM_MATCH", "Field": "location", "Value": region},
                {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
                {"Type": "TERM_MATCH", "Field": "tenancy", "Value": tenancy},
                {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            ],
            MaxResults=1,
        )

        if not response["PriceList"]:
            print(f"No RI pricing found for {instance_type} in {region}")
            return None

        price_item = json.loads(response["PriceList"][0])
        
        # Look for Reserved terms
        reserved_terms = price_item.get("terms", {}).get("Reserved", {})
        
        for term_key, term_data in reserved_terms.items():
            term_attributes = term_data.get("termAttributes", {})
            
            # Match lease length, payment option, and offering class
            if (term_attributes.get("LeaseContractLength") == lease_length and
                term_attributes.get("PurchaseOption") == payment_option and
                term_attributes.get("OfferingClass") == offering_class_value):
                
                # Extract pricing dimensions
                upfront_fee = 0
                hourly_rate = 0
                
                for dimension in term_data.get("priceDimensions", {}).values():
                    unit = dimension.get("unit", "")
                    price = float(dimension.get("pricePerUnit", {}).get("USD", 0))
                    
                    if unit == "Quantity":  # Upfront fee
                        upfront_fee = price
                    elif unit == "Hrs":  # Hourly rate
                        hourly_rate = price
                
                print(f"Found RI: {instance_type} {term} {payment_option} {offering_class_value} - ${hourly_rate}/hr + ${upfront_fee} upfront")
                return {
                    "hourly_rate": hourly_rate,
                    "upfront_fee": upfront_fee,
                    "term": term,
                    "payment_option": payment_option,
                    "offering_class": offering_class_value,
                }
        
        print(f"No matching RI found for {instance_type} {term} {payment_option} {offering_class_value}")
        return None

    except Exception as e:
        print(f"RI pricing error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


# =========================================================
# RESERVED INSTANCES CALCULATION (for Dedicated tenancy)
# =========================================================
def calculate_reserved_instances(
    instance_type: str,
    region: str,
    od_hourly: float,
    number_of_instances: int,
    operating_system: str = "Linux",
    tenancy: str = "Dedicated",
):
    """
    Calculate Reserved Instance pricing for Dedicated tenancy using real AWS pricing.
    
    RI Types:
    - Standard RI: Higher discount, cannot change instance type
    - Convertible RI: Lower discount, can change instance type
    """
    
    od_monthly = round(od_hourly * HOURS_PER_MONTH * number_of_instances, 2)
    
    result = {
        "standard": {},
        "convertible": {},
        "note": "Reserved Instances for Dedicated tenancy. Standard RI offers higher discounts but less flexibility. Convertible RI allows instance type changes."
    }
    
    payment_option_map = {
        "no_upfront": "No Upfront",
        "partial_upfront": "Partial Upfront",
        "all_upfront": "All Upfront",
    }
    
    for ri_type in ["standard", "convertible"]:
        for term in ["1yr", "3yr"]:
            for payment_key, payment_value in payment_option_map.items():
                
                # Fetch real RI pricing from AWS
                ri_pricing = get_reserved_instance_price(
                    instance_type=instance_type,
                    region=region,
                    term=term,
                    payment_option=payment_value,
                    offering_class=ri_type,
                    operating_system=operating_system,
                    tenancy=tenancy,
                )
                
                if not ri_pricing:
                    # Fallback to estimated pricing if API fails
                    print(f"Using estimated pricing for {term} {payment_key} {ri_type}")
                    discount_map = {
                        "1yr_no_upfront_standard": 0.30,
                        "1yr_partial_upfront_standard": 0.35,
                        "1yr_all_upfront_standard": 0.40,
                        "1yr_no_upfront_convertible": 0.25,
                        "1yr_partial_upfront_convertible": 0.30,
                        "1yr_all_upfront_convertible": 0.33,
                        "3yr_no_upfront_standard": 0.50,
                        "3yr_partial_upfront_standard": 0.55,
                        "3yr_all_upfront_standard": 0.60,
                        "3yr_no_upfront_convertible": 0.40,
                        "3yr_partial_upfront_convertible": 0.45,
                        "3yr_all_upfront_convertible": 0.50,
                    }
                    discount = discount_map.get(f"{term}_{payment_key}_{ri_type}", 0.30)
                    ri_hourly = od_hourly * (1 - discount)
                    upfront_fee = 0
                else:
                    ri_hourly = ri_pricing["hourly_rate"]
                    upfront_fee = ri_pricing["upfront_fee"]
                
                plan_years = 3 if term == "3yr" else 1
                total_hours = HOURS_PER_MONTH * 12 * plan_years
                
                # Calculate costs
                upfront_total = round(upfront_fee * number_of_instances, 2)
                recurring_monthly = round(ri_hourly * HOURS_PER_MONTH * number_of_instances, 2)
                
                # Effective monthly includes upfront amortized
                effective_monthly = round((upfront_fee / (12 * plan_years) + ri_hourly * HOURS_PER_MONTH) * number_of_instances, 2)
                
                monthly_savings = round(od_monthly - effective_monthly, 2)
                annual_savings = round(monthly_savings * 12, 2)
                discount_pct = round((monthly_savings / od_monthly) * 100, 2) if od_monthly > 0 else 0
                
                plan_name = f"{term}_{payment_key}"
                
                result[ri_type][plan_name] = {
                    "plan_type": plan_name,
                    "offering_class": ri_type.capitalize(),
                    "hourly_usd": round(ri_hourly * number_of_instances, 6),
                    "effective_monthly_usd": effective_monthly,
                    "discount_percent": discount_pct,
                    "monthly_savings_usd": monthly_savings,
                    "annual_savings_usd": annual_savings,
                    "plan_term_total": {
                        "years": plan_years,
                        "commitment_usd": round(effective_monthly * 12 * plan_years, 2),
                        "total_savings_usd": round(monthly_savings * 12 * plan_years, 2),
                    },
                }
                
                if upfront_total > 0 or payment_key in ["partial_upfront", "all_upfront"]:
                    result[ri_type][plan_name]["payment_breakdown"] = {
                        "upfront_usd": upfront_total,
                        "monthly_recurring_usd": recurring_monthly,
                        "note": f"Upfront: ${upfront_total} + Monthly: ${recurring_monthly}/month"
                    }
    
    return result


# =========================================================
# RESERVED INSTANCES CALCULATION (for Dedicated tenancy) - OLD VERSION


# =========================================================
# CSP DISCOUNT CALCULATION (NEW)
# =========================================================
def calculate_csp_discount(
    od_hourly: float,
    csp_hourly: float,
    number_of_instances: int,
    plan_type: str,
    upfront_fee: float = 0,
):
    """
    Calculate CSP discount %, monthly savings, and annual savings.
    
    Note: The csp_hourly rate from AWS API is the effective hourly rate
    that already includes the upfront payment amortized over the term.
    
    For partial/all upfront plans:
    - AWS Calculator shows: Upfront + Monthly recurring
    - AWS API returns: Effective hourly rate (upfront amortized into hourly)
    
    We need to back-calculate the upfront and monthly components.
    """
    term = plan_type.split("_")[0]  # "1yr" or "3yr"
    plan_years = 3 if term == "3yr" else 1
    total_hours = HOURS_PER_MONTH * 12 * plan_years
    
    # The API rate is effective rate = (upfront / total_hours) + recurring_hourly
    # For partial upfront: typically 50% upfront, 50% recurring
    # For all upfront: 100% upfront, 0% recurring
    # For no upfront: 0% upfront, 100% recurring
    
    payment_type = plan_type.split("_", 1)[1]  # "no_upfront", "partial_upfront", "all_upfront"
    
    if payment_type == "all_upfront":
        # All upfront: entire cost paid upfront, $0/month recurring
        upfront_per_instance = csp_hourly * total_hours
        recurring_hourly = 0
    elif payment_type == "partial_upfront":
        # Partial upfront: approximately 50% upfront, 50% recurring
        # The effective rate includes both components
        upfront_per_instance = csp_hourly * total_hours * 0.5
        recurring_hourly = csp_hourly * 0.5
    else:  # no_upfront
        # No upfront: $0 upfront, 100% recurring
        upfront_per_instance = 0
        recurring_hourly = csp_hourly
    
    # Calculate costs
    upfront_total = round(upfront_per_instance * number_of_instances, 2)
    recurring_monthly = round(recurring_hourly * HOURS_PER_MONTH * number_of_instances, 2)
    
    # Effective monthly cost (upfront amortized + recurring)
    effective_monthly = round(csp_hourly * HOURS_PER_MONTH * number_of_instances, 2)
    
    # On-demand comparison
    od_monthly_total = round(od_hourly * HOURS_PER_MONTH * number_of_instances, 2)
    
    # Savings calculations
    hourly_savings = od_hourly - csp_hourly
    discount_pct = round((hourly_savings / od_hourly) * 100, 2)
    monthly_savings = round(od_monthly_total - effective_monthly, 2)
    annual_savings = round(monthly_savings * 12, 2)
    
    # Total commitment over the plan term
    total_commitment = round(effective_monthly * 12 * plan_years, 2)
    total_savings = round(monthly_savings * 12 * plan_years, 2)

    result = {
        "plan_type": plan_type,
        "hourly_usd": round(csp_hourly * number_of_instances, 6),
        "effective_monthly_usd": effective_monthly,
        "discount_percent": discount_pct,
        "monthly_savings_usd": monthly_savings,
        "annual_savings_usd": annual_savings,
        "plan_term_total": {
            "years": plan_years,
            "commitment_usd": total_commitment,
            "total_savings_usd": total_savings,
        },
    }
    
    # Add payment breakdown for partial/all upfront
    if payment_type in ["partial_upfront", "all_upfront"]:
        result["payment_breakdown"] = {
            "upfront_usd": upfront_total,
            "monthly_recurring_usd": recurring_monthly,
            "note": f"Upfront: ${upfront_total} + Monthly: ${recurring_monthly}/month"
        }
    
    return result


# =========================================================
# MAIN EC2 ESTIMATION ENGINE (UPDATED)
# =========================================================
def estimate_ec2_cost(
    instance_type: str,
    region: str,
    plan_type: str = None,
    number_of_instances: int = 1,
    storage_gb: float = 0,
    throughput_mbs: float = 125,
    iops: int = 3000,
    include_spot: bool = True,
    operating_system: str = "Linux",
    tenancy: str = "Shared",
):
    od_hourly = get_ondemand_price(instance_type, region, operating_system, tenancy)
    if od_hourly is None:
        return None

    od_monthly_total = round(od_hourly * HOURS_PER_MONTH * number_of_instances, 2)

    result = {
        "instance_type":       instance_type,
        "region":              region,
        "number_of_instances": number_of_instances,
        "operating_system":    operating_system,
        "tenancy":             tenancy,
        "ondemand": {
            "hourly_usd":  round(od_hourly * number_of_instances, 6),
            "monthly_usd": od_monthly_total,
        },
    }

    # ── Compute Savings Plan ──────────────────────────────────
    if plan_type:
        csp_result = get_csp_rate(instance_type, region, plan_type)

        if csp_result:
            csp_hourly, upfront_fee, offering_id = csp_result
            if csp_hourly and od_hourly and csp_hourly > 0:
                result["compute_savings_plan"] = calculate_csp_discount(
                    od_hourly=od_hourly,
                    csp_hourly=csp_hourly,
                    number_of_instances=number_of_instances,
                    plan_type=plan_type,
                    upfront_fee=upfront_fee,
                )
            else:
                result["compute_savings_plan"] = {
                    "plan_type": plan_type,
                    "error": "CSP rate not found for this instance type / region combination",
                }
        else:
            result["compute_savings_plan"] = {
                "plan_type": plan_type,
                "error": "CSP rate not found for this instance type / region combination",
            }

    # ── Spot Instance ─────────────────────────────────────────
    if include_spot and tenancy.lower() == "shared":
        spot_hourly = get_spot_price(instance_type, region)
        if spot_hourly:
            spot_savings_pct   = round(((od_hourly - spot_hourly) / od_hourly) * 100, 2)
            spot_monthly_total = round(spot_hourly * HOURS_PER_MONTH * number_of_instances, 2)
            spot_annual_total  = round(spot_monthly_total * 12, 2)
            
            monthly_savings = round(od_monthly_total - spot_monthly_total, 2)
            annual_savings = round(monthly_savings * 12, 2)

            result["spot_instance"] = {
                "hourly_usd": round(spot_hourly * number_of_instances, 6),
                "monthly_usd": spot_monthly_total,
                "annual_usd": spot_annual_total,
                "savings_vs_ondemand": {
                    "discount_percent": spot_savings_pct,
                    "monthly_savings_usd": monthly_savings,
                    "annual_savings_usd": annual_savings,
                },
                "note": "Current spot price - subject to availability and price fluctuations",
            }
    elif include_spot and tenancy.lower() == "dedicated":
        result["spot_instance"] = {
            "available": False,
            "note": "Spot instances are not available for Dedicated tenancy"
        }

    # ── EBS Storage ───────────────────────────────────────────
    if storage_gb > 0:
        storage_monthly  = storage_gb * 0.08
        throughput_cost  = (throughput_mbs - 125) * 0.04 if throughput_mbs > 125 else 0
        iops_cost        = (iops - 3000) * 0.005        if iops > 3000        else 0
        total_storage    = round(
            (storage_monthly + throughput_cost + iops_cost) * number_of_instances, 2
        )

        result["ebs_storage"] = {
            "storage_gb":      storage_gb,
            "throughput_mbs":  throughput_mbs,
            "iops":            iops,
            "breakdown": {
                "storage_cost_monthly":    round(storage_monthly,  2),
                "throughput_cost_monthly": round(throughput_cost,  2),
                "iops_cost_monthly":       round(iops_cost,        2),
            },
            "total_monthly_usd": total_storage,
            "note": "EBS gp3 pricing: $0.08/GB, $0.04/MB/s above 125, $0.005/IOPS above 3000",
        }

        result["ondemand"]["monthly_usd_with_storage"] = round(
            od_monthly_total + total_storage, 2
        )

        if "compute_savings_plan" in result and "monthly_usd" in result["compute_savings_plan"]:
            result["compute_savings_plan"]["monthly_usd_with_storage"] = round(
                result["compute_savings_plan"]["monthly_usd"] + total_storage, 2
            )

        if "spot_instance" in result:
            result["spot_instance"]["monthly_usd_with_storage"] = round(
                result["spot_instance"]["monthly_usd"] + total_storage, 2
            )

    return result


# =========================================================
# RDS PRICING
# =========================================================
@lru_cache(maxsize=256)
def get_rds_ondemand_price(instance_type: str, region: str, database_engine: str, multi_az: bool):
    deployment = "Multi-AZ" if multi_az else "Single-AZ"
    try:
        response = pricing_client.get_products(
            ServiceCode="AmazonRDS",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType",     "Value": instance_type},
                {"Type": "TERM_MATCH", "Field": "location",         "Value": region},
                {"Type": "TERM_MATCH", "Field": "databaseEngine",   "Value": database_engine},
                {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": deployment},
            ],
            MaxResults=1,
        )
        if not response["PriceList"]:
            return None

        price_item = json.loads(response["PriceList"][0])
        for term in price_item["terms"]["OnDemand"].values():
            for dim in term["priceDimensions"].values():
                return float(dim["pricePerUnit"]["USD"])

    except Exception as e:
        print(f"RDS On-Demand pricing error: {str(e)}")

    return None


def calculate_rds_reserved_price(ondemand_price: float, term: str, payment_option: str):
    """
    Calculate RDS Reserved Instance pricing using typical discount rates.
    """
    discount_map = {
        "1yr_no_upfront":      0.30,
        "1yr_partial_upfront": 0.35,
        "1yr_all_upfront":     0.38,
        "3yr_no_upfront":      0.50,
        "3yr_partial_upfront": 0.55,
        "3yr_all_upfront":     0.60,
    }
    discount        = discount_map.get(f"{term}_{payment_option}", 0.30)
    effective_hourly = ondemand_price * (1 - discount)
    return round(effective_hourly, 6), round(discount * 100, 2)


def estimate_rds_cost(
    instance_type: str,
    region: str,
    database_engine: str = "MySQL",
    pricing_model: str = "ondemand",
    multi_az: bool = False,
    storage_gb: float = 20,
    storage_type: str = "gp3",
    read_replicas: int = 0,
    rds_proxy: bool = False,
    utilization_hours_per_month: float = 730,
    term: str = "1yr",
    payment_option: str = "no_upfront",
    number_of_nodes: int = 1,
    performance_insights: bool = False,
    performance_insights_retention_days: int = 7,
    backup_storage_gb: float = 0,
    snapshot_export_gb: float = 0,
    extended_support: bool = False,
    cloudwatch_logs: bool = False,
    cloudwatch_logs_gb: float = 0,
):
    od_hourly = get_rds_ondemand_price(instance_type, region, database_engine, multi_az)
    if od_hourly is None:
        return None

    od_monthly_primary = round(od_hourly * utilization_hours_per_month, 2)

    result = {
        "instance_type":              instance_type,
        "region":                     region,
        "database_engine":            database_engine,
        "pricing_model":              pricing_model,
        "multi_az":                   multi_az,
        "utilization_hours_per_month": utilization_hours_per_month,
        "primary_instance": {
            "ondemand": {
                "hourly_usd":  od_hourly,
                "monthly_usd": od_monthly_primary,
            },
        },
    }

    if pricing_model == "reserved":
        ri_hourly, savings_pct = calculate_rds_reserved_price(od_hourly, term, payment_option)
        ri_monthly = round(ri_hourly * utilization_hours_per_month, 2)
        result["primary_instance"]["reserved"] = {
            "term":           term,
            "payment_option": payment_option,
            "hourly_usd":     ri_hourly,
            "monthly_usd":    ri_monthly,
            "estimated_savings_percent": savings_pct,
            "note": "Estimated RI pricing based on typical discount rates",
        }

    if read_replicas > 0:
        replica_od_hourly = get_rds_ondemand_price(instance_type, region, database_engine, False)
        if replica_od_hourly:
            replica_monthly_each  = round(replica_od_hourly * utilization_hours_per_month, 2)
            replica_monthly_total = round(replica_monthly_each * read_replicas, 2)
            result["read_replicas"] = {
                "count":             read_replicas,
                "hourly_usd_each":   replica_od_hourly,
                "monthly_usd_each":  replica_monthly_each,
                "monthly_usd_total": replica_monthly_total,
            }

    if storage_gb > 0:
        storage_price_per_gb = {"gp3": 0.115, "gp2": 0.115, "io1": 0.125, "io2": 0.125}
        storage_monthly = round(storage_gb * storage_price_per_gb.get(storage_type, 0.115), 2)
        if multi_az:
            storage_monthly *= 2
        if read_replicas > 0:
            storage_monthly += round(
                storage_gb * storage_price_per_gb.get(storage_type, 0.115) * read_replicas, 2
            )
        result["storage"] = {
            "storage_gb":   storage_gb,
            "storage_type": storage_type,
            "monthly_usd":  storage_monthly,
            "note": f"Includes primary{' (Multi-AZ)' if multi_az else ''}"
                    f"{f' + {read_replicas} replicas' if read_replicas > 0 else ''}",
        }

    if rds_proxy:
        vcpus = 2
        if "large"   in instance_type: vcpus = 4
        if "xlarge"  in instance_type: vcpus = 8
        proxy_hourly  = vcpus * 0.015
        proxy_monthly = round(proxy_hourly * utilization_hours_per_month, 2)
        result["rds_proxy"] = {
            "enabled":         True,
            "estimated_vcpus": vcpus,
            "hourly_usd":      proxy_hourly,
            "monthly_usd":     proxy_monthly,
            "note": "RDS Proxy pricing estimated at $0.015/vCPU/hour",
        }

    if performance_insights:
        pi_cost = 0
        if performance_insights_retention_days > 7:
            vcpus = 2
            if "large"   in instance_type: vcpus = 4
            if "xlarge"  in instance_type: vcpus = 8
            if "2xlarge" in instance_type: vcpus = 16
            pi_cost = round(vcpus * 0.01 * utilization_hours_per_month * number_of_nodes, 2)
        result["performance_insights"] = {
            "enabled":         True,
            "retention_days":  performance_insights_retention_days,
            "monthly_usd":     pi_cost,
            "note": "First 7 days free, $0.01/vCPU-hour for long-term retention",
        }

    if backup_storage_gb > 0:
        backup_cost = round(backup_storage_gb * 0.095, 2)
        result["backup_storage"] = {
            "storage_gb":   backup_storage_gb,
            "price_per_gb": 0.095,
            "monthly_usd":  backup_cost,
            "note": "Backup storage beyond free tier (free tier = provisioned storage size)",
        }

    if snapshot_export_gb > 0:
        snapshot_cost = round(snapshot_export_gb * 0.010, 2)
        result["snapshot_export"] = {
            "export_gb":    snapshot_export_gb,
            "price_per_gb": 0.010,
            "monthly_usd":  snapshot_cost,
            "note": "Snapshot export to S3 pricing",
        }

    if extended_support:
        extended_support_cost = round(od_monthly_primary * 0.50 * number_of_nodes, 2)
        result["extended_support"] = {
            "enabled":       True,
            "rate_percent":  50,
            "monthly_usd":   extended_support_cost,
            "note": "RDS Extended Support for older engine versions (Year 1 rate: 50%)",
        }

    if cloudwatch_logs and cloudwatch_logs_gb > 0:
        logs_ingestion_cost = round(cloudwatch_logs_gb * 0.50, 2)
        logs_storage_cost   = round(cloudwatch_logs_gb * 0.03, 2)
        result["cloudwatch_logs"] = {
            "enabled":                  True,
            "logs_gb":                  cloudwatch_logs_gb,
            "ingestion_cost_monthly":   logs_ingestion_cost,
            "storage_cost_monthly":     logs_storage_cost,
            "total_monthly_usd":        logs_ingestion_cost + logs_storage_cost,
            "note": "CloudWatch Logs: $0.50/GB ingestion + $0.03/GB storage",
        }

    # Total
    total_monthly = od_monthly_primary * number_of_nodes
    if pricing_model == "reserved" and "reserved" in result["primary_instance"]:
        total_monthly = result["primary_instance"]["reserved"]["monthly_usd"] * number_of_nodes
    if read_replicas > 0 and "read_replicas" in result:
        total_monthly += result["read_replicas"]["monthly_usd_total"]
    if storage_gb > 0:
        total_monthly += result["storage"]["monthly_usd"]
    if rds_proxy:
        total_monthly += result["rds_proxy"]["monthly_usd"]
    if performance_insights and "performance_insights" in result:
        total_monthly += result["performance_insights"]["monthly_usd"]
    if backup_storage_gb > 0:
        total_monthly += result["backup_storage"]["monthly_usd"]
    if snapshot_export_gb > 0:
        total_monthly += result["snapshot_export"]["monthly_usd"]
    if extended_support and "extended_support" in result:
        total_monthly += result["extended_support"]["monthly_usd"]
    if cloudwatch_logs and cloudwatch_logs_gb > 0:
        total_monthly += result["cloudwatch_logs"]["total_monthly_usd"]

    result["number_of_nodes"]    = number_of_nodes
    result["total_monthly_usd"]  = round(total_monthly, 2)

    return result


# =========================================================
# S3 PRICING
# =========================================================
@lru_cache(maxsize=256)
def get_s3_storage_price(region: str, storage_class: str = "General Purpose"):
    try:
        filters = [
            {"Type": "TERM_MATCH", "Field": "location",     "Value": region},
            {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"},
            {"Type": "TERM_MATCH", "Field": "storageClass",  "Value": storage_class},
        ]
        response = pricing_client.get_products(
            ServiceCode="AmazonS3", Filters=filters, MaxResults=10
        )
        if not response["PriceList"]:
            return None

        prices = []
        for item in response["PriceList"]:
            price_item = json.loads(item)
            attributes = price_item.get("product", {}).get("attributes", {})
            if attributes.get("storageClass") != storage_class:
                continue
            for term in price_item.get("terms", {}).get("OnDemand", {}).values():
                for dim in term["priceDimensions"].values():
                    if "GB-Mo" in dim.get("unit", ""):
                        price = float(dim["pricePerUnit"]["USD"])
                        if price > 0:
                            prices.append({"price": price, "description": dim.get("description","").lower()})

        if not prices:
            return None

        for p in prices:
            if "first" in p["description"]:
                return p["price"]

        return max(prices, key=lambda x: x["price"])["price"]

    except Exception as e:
        print(f"S3 storage pricing error: {str(e)}")

    return None


def estimate_s3_cost(
    region: str,
    storage_gb: float,
    storage_class: str = "General Purpose",
    requests_put: int = 0,
    requests_get: int = 0,
    enable_vectors: bool = False,
    number_of_indexes: int = 1,
    number_of_vectors_per_index: int = 0,
    vector_dimensions: int = 1536,
    filterable_metadata_kb_per_vector: float = 0,
    non_filterable_metadata_kb_per_vector: float = 0,
    percentage_vectors_overwritten_per_month: float = 0,
    vector_queries_per_month: int = 0,
    enable_object_lambda: bool = False,
    object_lambda_requests_per_month: int = 0,
    object_lambda_gb_returned: float = 0,
    enable_storage_lens: bool = False,
    storage_lens_metrics_monitored: int = 0,
    enable_inventory: bool = False,
    inventory_objects_listed_millions: float = 0,
    enable_analytics: bool = False,
    analytics_objects_monitored_millions: float = 0,
    enable_access_grants: bool = False,
    access_grants_requests_per_month: int = 0,
    data_transfer_out_gb: float = 0,
    data_transfer_in_gb: float = 0,
    enable_express_one_zone: bool = False,
    express_storage_gb: float = 0,
    express_requests_per_month: int = 0,
):
    storage_class_map = {
        "Standard":                   "General Purpose",
        "General Purpose":            "General Purpose",
        "Intelligent-Tiering":        "Intelligent-Tiering",
        "Standard-IA":                "Infrequent Access",
        "Infrequent Access":          "Infrequent Access",
        "One Zone-IA":                "Non-Critical Data",
        "One Zone - Infrequent Access":"Non-Critical Data",
        "Non-Critical Data":          "Non-Critical Data",
        "Glacier Instant Retrieval":  "Archive Instant Retrieval",
        "Archive Instant Retrieval":  "Archive Instant Retrieval",
        "Glacier Flexible Retrieval": "Archive",
        "Glacier Deep Archive":       "Archive",
        "Archive":                    "Archive",
    }

    mapped_class  = storage_class_map.get(storage_class, storage_class)
    storage_price = get_s3_storage_price(region, mapped_class)

    if storage_price is None:
        return {
            "error": "S3 storage price not available from AWS API",
            "region": region,
            "storage_class": storage_class,
        }

    storage_monthly = round(storage_gb * storage_price, 2)
    put_cost        = round((requests_put / 1000) * 0.005,  4)
    get_cost        = round((requests_get / 1000) * 0.0004, 4)

    result = {
        "region":                  region,
        "storage_class":           storage_class,
        "storage_gb":              storage_gb,
        "storage_price_per_gb":    storage_price,
        "storage_cost_monthly_usd": storage_monthly,
        "requests": {
            "put_requests":       requests_put,
            "get_requests":       requests_get,
            "put_cost_monthly_usd": put_cost,
            "get_cost_monthly_usd": get_cost,
        },
        "total_monthly_usd": round(storage_monthly + put_cost + get_cost, 2),
    }

    if enable_vectors and number_of_vectors_per_index > 0:
        # Calculate total vectors across all indexes
        total_vectors = number_of_indexes * number_of_vectors_per_index
        
        # Calculate storage per vector
        bytes_per_vector     = vector_dimensions * 4  # 4 bytes per dimension (float32)
        metadata_bytes       = (filterable_metadata_kb_per_vector + non_filterable_metadata_kb_per_vector) * 1024
        total_bytes_per_vector = bytes_per_vector + metadata_bytes
        
        # Calculate total storage
        vector_storage_gb    = (total_vectors * total_bytes_per_vector) / (1024 ** 3)
        vector_storage_cost  = round(vector_storage_gb * storage_price, 2)
        
        # Calculate overwrite costs (PUT requests)
        vectors_overwritten  = int(total_vectors * (percentage_vectors_overwritten_per_month / 100))
        overwrite_cost       = round((vectors_overwritten / 1000) * 0.005, 4)
        
        # Calculate query costs (GET requests)
        query_cost           = round((vector_queries_per_month / 1000) * 0.0004, 4)

        result["vector_storage"] = {
            "enabled": True,
            "configuration": {
                "number_of_indexes":              number_of_indexes,
                "number_of_vectors_per_index":    number_of_vectors_per_index,
                "total_vectors":                  total_vectors,
                "vector_dimensions":              vector_dimensions,
                "filterable_metadata_kb_per_vector": filterable_metadata_kb_per_vector,
                "non_filterable_metadata_kb_per_vector": non_filterable_metadata_kb_per_vector,
                "percentage_vectors_overwritten_per_month": percentage_vectors_overwritten_per_month,
                "total_storage_gb":               round(vector_storage_gb, 4),
            },
            "costs": {
                "storage_monthly_usd":            vector_storage_cost,
                "overwrite_cost_monthly_usd":     overwrite_cost,
                "query_cost_monthly_usd":         query_cost,
                "total_monthly_usd":              round(vector_storage_cost + overwrite_cost + query_cost, 2),
            },
            "note": f"Vector storage across {number_of_indexes} index(es) with {number_of_vectors_per_index:,} vectors each",
        }
        result["total_monthly_usd"] = round(
            result["total_monthly_usd"] + result["vector_storage"]["costs"]["total_monthly_usd"], 2
        )

    if enable_object_lambda and object_lambda_requests_per_month > 0:
        lambda_request_cost = round((object_lambda_requests_per_month / 1000) * 0.005, 4)
        lambda_data_cost    = round(object_lambda_gb_returned * 0.0004, 4)
        result["object_lambda"] = {
            "enabled":          True,
            "total_monthly_usd": round(lambda_request_cost + lambda_data_cost, 2),
        }
        result["total_monthly_usd"] = round(
            result["total_monthly_usd"] + result["object_lambda"]["total_monthly_usd"], 2
        )

    management_cost = 0
    if enable_storage_lens and storage_lens_metrics_monitored > 0:
        management_cost += round((storage_lens_metrics_monitored / 1000000) * 0.20, 4)
    if enable_inventory and inventory_objects_listed_millions > 0:
        management_cost += round(inventory_objects_listed_millions * 0.0025, 4)
    if enable_analytics and analytics_objects_monitored_millions > 0:
        management_cost += round(analytics_objects_monitored_millions * 0.10, 4)
    if management_cost > 0:
        result["management_insights"] = {"total_monthly_usd": round(management_cost, 2)}
        result["total_monthly_usd"]   = round(result["total_monthly_usd"] + management_cost, 2)

    if enable_access_grants and access_grants_requests_per_month > 0:
        grants_cost = round((access_grants_requests_per_month / 10000) * 0.025, 4)
        result["access_grants"] = {"monthly_usd": grants_cost}
        result["total_monthly_usd"] = round(result["total_monthly_usd"] + grants_cost, 2)

    # Data Transfer - Always include if either inbound or outbound is specified
    if data_transfer_out_gb > 0 or data_transfer_in_gb > 0:
        transfer_out_cost = round(data_transfer_out_gb * 0.09, 2) if data_transfer_out_gb > 0 else 0.0
        transfer_in_cost = 0.0  # Inbound data transfer is always free
        
        result["data_transfer"] = {
            "inbound_data_transfer_gb":      data_transfer_in_gb,
            "outbound_data_transfer_gb":     data_transfer_out_gb,
            "inbound_cost_monthly_usd":      transfer_in_cost,
            "outbound_cost_monthly_usd":     transfer_out_cost,
            "total_monthly_usd":             transfer_out_cost,
            "note": "Inbound data transfer is FREE. Outbound: ~$0.09/GB (first 10TB)",
        }
        result["total_monthly_usd"] = round(result["total_monthly_usd"] + transfer_out_cost, 2)

    if enable_express_one_zone and express_storage_gb > 0:
        express_storage_cost = round(express_storage_gb * 0.16, 2)
        express_request_cost = round((express_requests_per_month / 1000) * 0.0008, 4)
        result["express_one_zone"] = {
            "enabled":           True,
            "total_monthly_usd": round(express_storage_cost + express_request_cost, 2),
        }
        result["total_monthly_usd"] = round(
            result["total_monthly_usd"] + result["express_one_zone"]["total_monthly_usd"], 2
        )

    return result


# =========================================================
# VPC PRICING
# =========================================================
@lru_cache(maxsize=256)
def get_nat_gateway_price(region: str):
    try:
        response = pricing_client.get_products(
            ServiceCode="AmazonEC2",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "location",      "Value": region},
                {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "NAT Gateway"},
                {"Type": "TERM_MATCH", "Field": "operation",     "Value": "NatGateway"},
            ],
            MaxResults=1,
        )
        if not response["PriceList"]:
            return None
        price_item = json.loads(response["PriceList"][0])
        for term in price_item["terms"]["OnDemand"].values():
            for dim in term["priceDimensions"].values():
                if "hour" in dim["unit"].lower():
                    return float(dim["pricePerUnit"]["USD"])
    except Exception as e:
        print(f"NAT Gateway pricing error: {str(e)}")
    return None


@lru_cache(maxsize=256)
def get_data_transfer_price(region: str, transfer_type: str = "out"):
    try:
        if transfer_type == "out":
            response = pricing_client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "location",     "Value": region},
                    {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Data Transfer"},
                    {"Type": "TERM_MATCH", "Field": "transferType",  "Value": "AWS Outbound"},
                ],
                MaxResults=10,
            )
            if response["PriceList"]:
                price_item = json.loads(response["PriceList"][0])
                for term in price_item["terms"]["OnDemand"].values():
                    for dim in term["priceDimensions"].values():
                        if "GB" in dim["unit"]:
                            price = float(dim["pricePerUnit"]["USD"])
                            if price > 0:
                                return price
    except Exception as e:
        print(f"Data transfer pricing error: {str(e)}")
    return 0.09


def estimate_vpc_cost(
    region: str,
    data_transfer_out_gb: float = 0,
    data_transfer_in_gb: float = 0,
    nat_gateways: int = 0,
    nat_data_processed_gb: float = 0,
    elastic_ips: int = 0,
    elastic_ip_hours_unused: float = 0,
    # VPN Connection Parameters
    enable_site_to_site_vpn: bool = False,
    site_to_site_vpn_connections: int = 0,
    enable_client_vpn: bool = False,
    client_vpn_subnet_associations: int = 0,
    client_vpn_active_connections: int = 0,
    # Regional NAT Gateway Parameters
    enable_regional_nat_gateway: bool = False,
    regional_nat_gateways: int = 0,
    regional_nat_availability_zones: int = 0,
    regional_nat_data_processed_gb: float = 0,
):
    result = {
        "region":            region,
        "vpc_components":    {},
        "total_monthly_usd": 0,
    }

    if data_transfer_out_gb > 0:
        price         = get_data_transfer_price(region, "out") or 0.09
        transfer_cost = round(data_transfer_out_gb * price, 2)
        result["vpc_components"]["data_transfer_out"] = {
            "data_gb":     data_transfer_out_gb,
            "price_per_gb": price,
            "monthly_usd": transfer_cost,
        }
        result["total_monthly_usd"] += transfer_cost

    if data_transfer_in_gb > 0:
        result["vpc_components"]["data_transfer_in"] = {
            "data_gb":     data_transfer_in_gb,
            "monthly_usd": 0.0,
            "note": "Data transfer IN from internet is FREE",
        }

    if nat_gateways > 0:
        nat_hourly   = get_nat_gateway_price(region) or 0.045
        nat_monthly  = round(nat_hourly * HOURS_PER_MONTH * nat_gateways, 2)
        nat_data_cost = round(nat_data_processed_gb * 0.045, 2)
        total_nat    = nat_monthly + nat_data_cost
        result["vpc_components"]["nat_gateway"] = {
            "count":               nat_gateways,
            "hourly_usd_each":     nat_hourly,
            "monthly_usd_runtime": nat_monthly,
            "data_processed_gb":   nat_data_processed_gb,
            "data_processing_cost": nat_data_cost,
            "total_monthly_usd":   total_nat,
        }
        result["total_monthly_usd"] += total_nat

    if elastic_ips > 0:
        eip_cost = round(elastic_ip_hours_unused * 0.005 * elastic_ips, 2) if elastic_ip_hours_unused > 0 else 0
        result["vpc_components"]["elastic_ip"] = {
            "count":                  elastic_ips,
            "hours_unused_per_month": elastic_ip_hours_unused,
            "monthly_usd":            eip_cost,
            "note": "FREE when associated, $0.005/hour when unused",
        }
        result["total_monthly_usd"] += eip_cost

    # Site-to-Site VPN
    if enable_site_to_site_vpn and site_to_site_vpn_connections > 0:
        vpn_hourly = 0.05  # $0.05/hour per VPN connection
        vpn_monthly = round(vpn_hourly * HOURS_PER_MONTH * site_to_site_vpn_connections, 2)
        result["vpc_components"]["site_to_site_vpn"] = {
            "enabled": True,
            "connections": site_to_site_vpn_connections,
            "hourly_usd_per_connection": vpn_hourly,
            "monthly_usd": vpn_monthly,
            "note": "Site-to-Site VPN: $0.05/hour per connection",
        }
        result["total_monthly_usd"] += vpn_monthly

    # Client VPN
    if enable_client_vpn:
        client_vpn_cost = 0
        
        # Subnet association cost: $0.10/hour per association
        if client_vpn_subnet_associations > 0:
            subnet_hourly = 0.10
            subnet_monthly = round(subnet_hourly * HOURS_PER_MONTH * client_vpn_subnet_associations, 2)
            client_vpn_cost += subnet_monthly
        else:
            subnet_monthly = 0
        
        # Active connection cost: $0.05/hour per connection
        if client_vpn_active_connections > 0:
            connection_hourly = 0.05
            connection_monthly = round(connection_hourly * HOURS_PER_MONTH * client_vpn_active_connections, 2)
            client_vpn_cost += connection_monthly
        else:
            connection_monthly = 0
        
        if client_vpn_cost > 0:
            result["vpc_components"]["client_vpn"] = {
                "enabled": True,
                "subnet_associations": client_vpn_subnet_associations,
                "active_connections": client_vpn_active_connections,
                "breakdown": {
                    "subnet_association_cost_monthly_usd": subnet_monthly,
                    "active_connection_cost_monthly_usd": connection_monthly,
                },
                "total_monthly_usd": round(client_vpn_cost, 2),
                "note": "Client VPN: $0.10/hour per subnet association + $0.05/hour per active connection",
            }
            result["total_monthly_usd"] += client_vpn_cost

    # Regional NAT Gateway
    if enable_regional_nat_gateway and regional_nat_gateways > 0:
        # Regional NAT Gateway pricing (cross-AZ)
        regional_nat_hourly = 0.045  # $0.045/hour per gateway
        regional_nat_monthly = round(regional_nat_hourly * HOURS_PER_MONTH * regional_nat_gateways, 2)
        
        # Data processing cost
        regional_nat_data_cost = round(regional_nat_data_processed_gb * 0.045, 2)
        
        # Cross-AZ data transfer cost (if spanning multiple AZs)
        cross_az_cost = 0
        if regional_nat_availability_zones > 1:
            # Cross-AZ data transfer: $0.01/GB
            cross_az_cost = round(regional_nat_data_processed_gb * 0.01, 2)
        
        total_regional_nat = regional_nat_monthly + regional_nat_data_cost + cross_az_cost
        
        result["vpc_components"]["regional_nat_gateway"] = {
            "enabled": True,
            "count": regional_nat_gateways,
            "availability_zones": regional_nat_availability_zones,
            "hourly_usd_per_gateway": regional_nat_hourly,
            "monthly_usd_runtime": regional_nat_monthly,
            "data_processed_gb": regional_nat_data_processed_gb,
            "breakdown": {
                "runtime_cost_monthly_usd": regional_nat_monthly,
                "data_processing_cost_monthly_usd": regional_nat_data_cost,
                "cross_az_transfer_cost_monthly_usd": cross_az_cost,
            },
            "total_monthly_usd": total_regional_nat,
            "note": f"Regional NAT Gateway: $0.045/hour + $0.045/GB processed{' + $0.01/GB cross-AZ transfer' if regional_nat_availability_zones > 1 else ''}",
        }
        result["total_monthly_usd"] += total_regional_nat

    result["total_monthly_usd"] = round(result["total_monthly_usd"], 2)
    return result


# =========================================================
# LAMBDA PRICING
# =========================================================
@lru_cache(maxsize=256)
def get_lambda_price(region: str, architecture: str = "x86"):
    try:
        response = pricing_client.get_products(
            ServiceCode="AWSLambda",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "location", "Value": region},
                {"Type": "TERM_MATCH", "Field": "group",    "Value": "AWS-Lambda-Duration"},
            ],
            MaxResults=10,
        )
        if not response["PriceList"]:
            return None

        for item in response["PriceList"]:
            price_item  = json.loads(item)
            attributes  = price_item.get("product", {}).get("attributes", {})
            if architecture == "arm64" and "ARM" not in attributes.get("groupDescription", ""):
                continue
            for term in price_item.get("terms", {}).get("OnDemand", {}).values():
                for dim in term["priceDimensions"].values():
                    if "GB-Second" in dim.get("unit", ""):
                        price = float(dim["pricePerUnit"]["USD"])
                        if price > 0:
                            return price
    except Exception as e:
        print(f"Lambda pricing error: {str(e)}")
    return None


@lru_cache(maxsize=256)
def get_lambda_request_price(region: str):
    try:
        response = pricing_client.get_products(
            ServiceCode="AWSLambda",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "location", "Value": region},
                {"Type": "TERM_MATCH", "Field": "group",    "Value": "AWS-Lambda-Requests"},
            ],
            MaxResults=1,
        )
        if not response["PriceList"]:
            return None
        price_item = json.loads(response["PriceList"][0])
        for term in price_item["terms"]["OnDemand"].values():
            for dim in term["priceDimensions"].values():
                return float(dim["pricePerUnit"]["USD"])
    except Exception as e:
        print(f"Lambda request pricing error: {str(e)}")
    return None


def estimate_lambda_cost(
    region: str,
    memory_mb: int = 128,
    architecture: str = "x86",
    invocations_per_month: int = 1000000,
    avg_duration_ms: float = 200,
    ephemeral_storage_gb: float = 0.512,
):
    compute_price = get_lambda_price(region, architecture)
    request_price = get_lambda_request_price(region)

    if compute_price is None:
        compute_price = 0.0000133334 if architecture == "arm64" else 0.0000166667
    if request_price is None:
        request_price = 0.20

    memory_gb        = memory_mb / 1024
    duration_seconds = avg_duration_ms / 1000
    total_gb_seconds = memory_gb * duration_seconds * invocations_per_month

    billable_gb_seconds = max(0, total_gb_seconds - 400000)
    compute_cost        = round(billable_gb_seconds * compute_price, 2)

    billable_requests = max(0, invocations_per_month - 1000000)
    request_cost      = round((billable_requests / 1000000) * request_price, 2)

    storage_cost = 0
    if ephemeral_storage_gb > 0.512:
        additional_gb    = ephemeral_storage_gb - 0.512
        storage_seconds  = additional_gb * duration_seconds * invocations_per_month
        storage_cost     = round(storage_seconds * 0.0000000309, 4)

    result = {
        "region": region,
        "configuration": {
            "memory_mb":            memory_mb,
            "architecture":         architecture,
            "avg_duration_ms":      avg_duration_ms,
            "ephemeral_storage_gb": ephemeral_storage_gb,
        },
        "usage": {
            "invocations_per_month":    invocations_per_month,
            "total_compute_gb_seconds": round(total_gb_seconds, 2),
        },
        "pricing": {
            "compute": {
                "total_gb_seconds":    round(total_gb_seconds, 2),
                "free_tier_gb_seconds": 400000,
                "billable_gb_seconds": round(billable_gb_seconds, 2),
                "price_per_gb_second": compute_price,
                "monthly_usd":         compute_cost,
            },
            "requests": {
                "total_requests":    invocations_per_month,
                "free_tier_requests": 1000000,
                "billable_requests": billable_requests,
                "price_per_million": request_price,
                "monthly_usd":       request_cost,
            },
        },
        "total_monthly_usd": round(compute_cost + request_cost + storage_cost, 2),
        "note": f"Includes AWS Free Tier: 1M requests + 400K GB-seconds/month. Architecture: {architecture}",
    }

    if storage_cost > 0:
        result["pricing"]["ephemeral_storage"] = {
            "additional_storage_gb": round(ephemeral_storage_gb - 0.512, 3),
            "monthly_usd":           storage_cost,
        }

    return result