# Strands Agent 2: Cost calculation + optimisation
"""
agents/cost_agent.py
---------------------
Strands Agent 2: Cost Calculation, Optimisation & Comparison Agent

Responsibilities:
  1. For each matched AWS instance, call the pricing API (via cost_client)
  2. Identify the lowest cost option with equivalent or better specs
  3. Compare AWS cost vs current provider cost
  4. Return structured cost results + optimised recommendation

Strands is used here because:
  - Multi-step reasoning: calculate → compare → rank → explain
  - It picks the best savings plan per instance type
  - It explains WHY a particular instance is the optimised choice
"""

import logging
from typing import Optional
from strands import Agent

from utils.cost_client import get_costs_for_match

logger = logging.getLogger(__name__)

COST_AGENT_SYSTEM_PROMPT = """
You are a FinOps (Cloud Financial Operations) expert specialising in AWS cost optimisation.

You receive:
1. A list of matched AWS instances (with specs)
2. The user's current cloud cost (from GCP or Azure)
3. The service type

Your tasks:
1. For each matched instance, retrieve and calculate:
   - On-Demand cost (hourly, monthly, annual)
   - Best savings plan (Compute Savings Plan or Reserved Instance)
   - Spot instance price if applicable

2. Identify the OPTIMISED option:
   - Lowest effective monthly cost that still meets the spec requirements
   - Consider the best savings plan as the optimised cost

3. Compare with current provider cost:
   - Monthly savings = current_cost - optimised_aws_cost
   - Annual savings = monthly_savings × 12
   - Savings percentage

4. Return a clear recommendation with reasoning.

Always show: hourly / monthly / annual costs for transparency.
"""


# ─────────────────────────────────────────────────────────────────────────────
# TENANCY VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_tenancy(instance_type: str, tenancy: str, service_type: str) -> str:
    """
    Validate and correct tenancy based on service type and instance family.
    
    Rules:
    1. RDS always uses Shared tenancy (no Dedicated support)
    2. T family (burstable) not recommended for Dedicated (cost inefficient)
    3. S3, Lambda, VPC don't have tenancy concept
    
    Args:
        instance_type: AWS instance type (e.g., "t3.large", "db.m6i.large")
        tenancy: Requested tenancy ("Shared" or "Dedicated")
        service_type: Service type ("ec2", "rds", "s3", etc.)
    
    Returns:
        Validated tenancy value
    """
    # RDS doesn't support Dedicated tenancy
    if service_type == "rds":
        if tenancy and tenancy.lower() == "dedicated":
            logger.warning(f"RDS does not support Dedicated tenancy. Using Shared for {instance_type}")
        return "Shared"
    
    # S3, Lambda, VPC don't have tenancy concept
    if service_type in ["s3", "lambda", "vpc"]:
        return "Shared"
    
    # EC2: T family not recommended for Dedicated (burstable + dedicated = cost inefficient)
    if service_type == "ec2" and tenancy and tenancy.lower() == "dedicated":
        family = instance_type.split('.')[0] if '.' in instance_type else ""
        if family.startswith('t'):
            logger.warning(
                f"T family ({instance_type}) with Dedicated tenancy is not cost-efficient. "
                f"Recommend using Shared tenancy or M family for Dedicated workloads."
            )
            # Still allow it but warn
    
    return tenancy or "Shared"


# ─────────────────────────────────────────────────────────────────────────────
# COST ENRICHMENT (non-agent helper)
# ─────────────────────────────────────────────────────────────────────────────

def enrich_match_with_costs(match: dict, service_type: str, input_row: dict) -> dict:
    """
    Call the pricing API for a single AWS instance match and attach cost data.
    Validates tenancy before calling pricing API.
    Returns the match dict enriched with a 'costs' key.
    """
    # Validate and correct tenancy
    instance_type = match.get("instance_type", "")
    requested_tenancy = input_row.get("tenancy", "Shared")
    validated_tenancy = validate_tenancy(instance_type, requested_tenancy, service_type)
    
    # Update match with validated tenancy
    match["tenancy"] = validated_tenancy
    
    # Update input_row for cost calculation
    input_row_with_validated_tenancy = input_row.copy()
    input_row_with_validated_tenancy["tenancy"] = validated_tenancy
    
    costs = get_costs_for_match(service_type, match, input_row_with_validated_tenancy)

    if not costs:
        match["costs"] = {}
        match["cost_error"] = "Pricing API unavailable"
        return match

    match["costs"] = costs
    return match


# ─────────────────────────────────────────────────────────────────────────────
# OPTIMISED PICK
# ─────────────────────────────────────────────────────────────────────────────

def pick_optimised(matches_with_costs: list[dict]) -> dict:
    """
    From a list of enriched matches, pick the BEST one using weighted scoring.
    
    Scoring criteria:
    1. Cost (40% weight) - Lower is better
    2. Generation (30% weight) - Current generation preferred
    3. Instance Family (30% weight) - Production-ready families preferred
    
    IMPORTANT: Only considers instances with valid pricing (skips instances with no costs).
    
    Returns a summary of the optimised option.
    """
    best_match = None
    best_score = -1
    best_plan_label = "On-Demand"

    # Instance family scoring (production readiness + regional availability)
    FAMILY_SCORES = {
        # Widely available families (high score)
        'm6a': 10, 'm5a': 10, 't3': 9, 't3a': 9, 'm6g': 9,  # Available in most regions
        # General Purpose (good availability)
        'm7i': 8, 'm7': 8, 'm6i': 7, 'm6': 7, 'm5': 7, 'm5ad': 6,
        # Compute Optimized
        'c7': 8, 'c6i': 7, 'c6': 7, 'c5': 6, 'c5a': 6,
        # Memory Optimized
        'r7i': 8, 'r6i': 7, 'r6': 7, 'r5': 6, 'r5a': 6,
        # Burstable
        't4g': 8,
        # Storage Optimized (limited availability)
        'i4i': 6, 'i3': 5, 'i3en': 5, 'm5d': 5, 'm6id': 5,
        # Network optimized (very limited)
        'm6in': 4, 'm6idn': 4, 'm7i-flex': 4,
        # GPU (very limited)
        'g6': 3, 'g5': 3, 'g6f': 3,
        # Old generation (avoid)
        't2': 2, 'm4': 2, 'c4': 2, 'r4': 2, 'm8i': 2, 'm8g': 2, 'm8i-flex': 2,
    }
    
    # Count instances with valid pricing
    valid_count = 0

    for match in matches_with_costs:
        costs = match.get("costs", {})
        
        # Skip instances with no costs (pricing not available)
        if not costs or "cost_error" in match:
            continue
        
        # Get effective monthly cost (prefer savings plan)
        sp = costs.get("best_savings_plan", {})
        od = costs.get("ondemand", {})
        sp_monthly = sp.get("monthly_usd") if sp else None
        od_monthly = od.get("monthly_usd")
        
        effective_monthly = sp_monthly if (sp_monthly and sp_monthly > 0) else od_monthly
        
        # Skip if no valid pricing
        if not effective_monthly or effective_monthly <= 0:
            continue
        
        valid_count += 1
        
        # 1. Cost Score (40% weight) - Inverse of cost (lower cost = higher score)
        cost_score = 1000.0 / float(effective_monthly)
        
        # 2. Generation Score (30% weight)
        current_gen_raw = match.get("current_generation", "")
        if isinstance(current_gen_raw, bool):
            current_gen = "yes" if current_gen_raw else "no"
        else:
            current_gen = str(current_gen_raw).lower()
        gen_score = 10.0 if current_gen == "yes" else 3.0
        
        # 3. Family Score (30% weight)
        instance_type = match.get("instance_type", "")
        family = instance_type.split('.')[0] if '.' in instance_type else instance_type
        family_score = FAMILY_SCORES.get(family, 5.0)  # Default 5.0 for unknown
        
        # Calculate weighted total score
        total_score = (
            cost_score * 0.4 +      # 40% weight on cost
            gen_score * 0.3 +       # 30% weight on generation
            family_score * 0.3      # 30% weight on family
        )
        
        logger.debug(
            f"  {instance_type}: cost_score={cost_score:.2f}, gen_score={gen_score:.1f}, "
            f"family_score={family_score:.1f}, total={total_score:.2f}"
        )

        if total_score > best_score:
            best_score = total_score
            best_match = match
            best_plan_label = sp.get("plan_label", "On-Demand") if sp_monthly else "On-Demand"

    if not best_match:
        logger.warning(f"No instances with valid pricing found (checked {len(matches_with_costs)} matches, {valid_count} had costs)")
        return {}

    costs = best_match.get("costs", {})
    od = costs.get("ondemand", {})
    sp = costs.get("best_savings_plan", {})

    opt_monthly = sp.get("monthly_usd") or od.get("monthly_usd")
    opt_annual = round(float(opt_monthly) * 12, 2) if opt_monthly else None

    # For S3, use storageclass instead of instance_type
    display_name = best_match.get("instance_type")
    if not display_name:
        # S3/Storage services don't have instance_type, use storageclass
        storage_class = best_match.get("storageclass", "S3 Standard")
        display_name = f"S3 {storage_class}"

    logger.info(
        f"Selected: {display_name} (score: {best_score:.2f}) - "
        f"${opt_monthly:.2f}/mo with {best_plan_label} (from {valid_count} instances with valid pricing)"
    )

    return {
        "instance_type": display_name,  # Use display_name for S3
        "vcpus": best_match.get("vcpus"),
        "memory_gib": best_match.get("memory_gib"),
        "region": best_match.get("region"),
        "plan_label": best_plan_label,
        "hourly_usd": sp.get("hourly_usd") or od.get("hourly_usd"),
        "monthly_usd": opt_monthly,
        "annual_usd": opt_annual,
        "discount_percent": sp.get("discount_percent") if sp else None,
        "reasoning": (
            f"Best match based on weighted scoring (cost 40%, generation 30%, family 30%). "
            f"Selected {display_name} at ${opt_monthly:.2f}/mo "
            f"using {best_plan_label}. Score: {best_score:.2f}. "
            f"Validated {valid_count} instances with real AWS pricing."
        ) if opt_monthly else "No cost data available",
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMPARISON BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_cost_comparison(
    current_monthly_cost: Optional[float],
    optimised: dict,
    ondemand: dict,
) -> dict:
    """
    Build the side-by-side comparison:
      Current provider  vs  AWS On-Demand  vs  AWS Optimised
    """
    comparison = {
        "current_provider": {
            "monthly_usd": current_monthly_cost,
            "annual_usd":  round(float(current_monthly_cost) * 12, 2) if current_monthly_cost else None,
        },
        "aws_ondemand": ondemand,
        "aws_optimised": optimised,
    }

    if current_monthly_cost and optimised.get("monthly_usd"):
        sav_m = round(float(current_monthly_cost) - float(optimised["monthly_usd"]), 2)
        sav_a = round(sav_m * 12, 2)
        sav_p = round((sav_m / float(current_monthly_cost)) * 100, 2)
        comparison["savings"] = {
            "monthly_usd":   sav_m,
            "annual_usd":    sav_a,
            "percent":       sav_p,
            "verdict":       (
                "🟢 Great savings" if sav_p > 20 else
                "🟡 Modest savings" if sav_p > 0 else
                "⚪ Break-even" if sav_p == 0 else
                "🔴 Higher cost on AWS"
            ),
        }

    return comparison


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def calculate_and_compare_costs(
    service_row: dict,
    mapping_result: dict,
) -> dict:
    """
    Main entry point for cost calculation + comparison.

    Args:
        service_row:    Original input row from XLSX
        mapping_result: Output from sql_generator_agent.generate_and_execute_sql()

    Returns:
        dict with:
          - aws_matches       : list of matches with costs attached
          - best_match        : the recommended AWS instance (lowest od cost)
          - optimised         : best savings plan / lowest cost option
          - costs             : ondemand costs for best_match
          - comparison        : current vs aws cost comparison
    """
    logger.info(f"💰 [COST] Starting cost calculation")

    matches       = mapping_result.get("matches", [])
    service_type  = str(service_row.get("service_type", "ec2")).lower()
    current_cost  = service_row.get("current_monthly_cost_usd")

    logger.info(f"💰 [COST] Service type: {service_type}, Matches found: {len(matches)}")

    if not matches:
        logger.warning(f"⚠️ [COST] No matches to calculate costs for")
        return {
            "aws_matches":  [],
            "best_match":   {},
            "optimised":    {},
            "costs":        {},
            "comparison":   {},
            "notes":        mapping_result.get("notes", "No matches found"),
        }

    # ── Step 1: Enrich each match with costs ─────────────────────────────────
    enriched = []
    skipped_due_to_availability = []
    
    for idx, match in enumerate(matches):
        try:
            # Check for availability warning
            availability_warning = match.get("availability_warning")
            if availability_warning:
                logger.warning(f"⚠️ Skipping {match.get('instance_type')} due to availability: {availability_warning}")
                skipped_due_to_availability.append(match)
                continue
            
            enriched_match = enrich_match_with_costs(match.copy(), service_type, service_row)
            enriched.append(enriched_match)
            
            # Add delay between API calls to avoid AWS rate limiting (except for last item)
            if idx < len(matches) - 1:
                import time
                time.sleep(0.5)  # 500ms delay - reduced since we only process 3 matches now
        except Exception as e:
            logger.error(f"Cost enrichment failed for {match.get('instance_type')}: {e}")
            match["costs"] = {}
            enriched.append(match)

    # ── Step 2: Check if ANY instance has valid pricing ──────────────────────
    valid_pricing_count = sum(1 for m in enriched if m.get("costs") and "cost_error" not in m and m.get("costs").get("ondemand"))
    
    if valid_pricing_count == 0:
        logger.warning(f"⚠️ No instances with valid pricing found. Skipped {len(skipped_due_to_availability)} due to availability warnings.")
        logger.warning(f"⚠️ Attempting smart retry with alternative families...")
        
        # Try alternative instance families based on specs
        from utils.cost_client import normalize_region
        vcpus = service_row.get("vcpus")
        memory_gib = service_row.get("memory_gib")
        region = normalize_region(service_row.get("region", "ap-south-1"))
        
        # Define fallback instances known to be available in ap-south-1 (Mumbai)
        # Based on AWS availability: t3a, m6i, c6i, r6i are available in Mumbai
        fallback_instances = []
        if vcpus and memory_gib:
            # Map to instances actually available in Mumbai region
            if vcpus <= 2 and memory_gib <= 8:
                fallback_instances = ["t3a.large", "m6i.large", "c6i.large"]
            elif vcpus <= 4 and memory_gib <= 16:
                fallback_instances = ["t3a.xlarge", "m6i.xlarge", "c6i.xlarge"]
            elif vcpus <= 8 and memory_gib <= 32:
                fallback_instances = ["t3a.2xlarge", "m6i.2xlarge", "c6i.2xlarge"]
            elif vcpus <= 16 and memory_gib <= 64:
                fallback_instances = ["m6i.4xlarge", "c6i.4xlarge", "r6i.4xlarge"]
            else:
                fallback_instances = ["m6i.8xlarge", "c6i.8xlarge", "r6i.8xlarge"]
        
        # For RDS, use db. prefix
        if service_type == "rds":
            fallback_instances = [f"db.{inst}" for inst in fallback_instances]
        
        # Try each fallback instance
        for fallback_type in fallback_instances:
            logger.info(f"🔄 Trying fallback instance: {fallback_type}")
            fallback_match = {
                "instance_type": fallback_type,
                "vcpus": vcpus,
                "memory_gib": memory_gib,
                "region": region,
                "current_generation": "Yes",
                "instance_family": fallback_type.split('.')[0] if service_type != "rds" else fallback_type.split('.')[1],
            }
            try:
                enriched_fallback = enrich_match_with_costs(fallback_match.copy(), service_type, service_row)
                if enriched_fallback.get("costs") and enriched_fallback.get("costs").get("ondemand"):
                    logger.info(f"✅ Fallback successful: {fallback_type} has valid pricing")
                    enriched.append(enriched_fallback)
                    valid_pricing_count += 1
                    break
            except Exception as e:
                logger.debug(f"Fallback {fallback_type} failed: {e}")
                continue

    # ── Step 3: Pick optimised (lowest cost with savings plan) ────────────────
    optimised = pick_optimised(enriched)

    # ── Step 4: Best match (lowest On-Demand monthly for 'best' column) ───────
    best_match = None
    best_od    = float("inf")
    for m in enriched:
        od_m = m.get("costs", {}).get("ondemand", {}).get("monthly_usd")
        if od_m and float(od_m) < best_od:
            best_od    = float(od_m)
            best_match = m

    if not best_match and enriched:
        best_match = enriched[0]

    # For S3, add display name if instance_type is missing
    if best_match and not best_match.get("instance_type"):
        storage_class = best_match.get("storageclass", "S3 Standard")
        best_match = best_match.copy()  # Don't modify original
        best_match["instance_type"] = f"S3 {storage_class}"

    best_costs = best_match.get("costs", {}) if best_match else {}
    od_costs   = best_costs.get("ondemand", {})

    # ── Step 5: Build comparison ──────────────────────────────────────────────
    comparison = build_cost_comparison(
        current_monthly_cost=float(current_cost) if current_cost else None,
        optimised=optimised,
        ondemand={
            "hourly_usd":  od_costs.get("hourly_usd"),
            "monthly_usd": od_costs.get("monthly_usd"),
            "annual_usd":  od_costs.get("annual_usd"),
        },
    )

    return {
        "aws_matches":  enriched,
        "best_match":   best_match or {},
        "optimised":    optimised,
        "costs":        best_costs,
        "comparison":   comparison,
        "notes":        mapping_result.get("notes", ""),
        "mapping_method": mapping_result.get("mapping_method", "Unknown"),
        "pricing_validation": {
            "total_matches": len(matches),
            "skipped_due_to_availability": len(skipped_due_to_availability),
            "valid_pricing_count": valid_pricing_count,
            "fallback_used": valid_pricing_count > len(matches) - len(skipped_due_to_availability),
        }
    }