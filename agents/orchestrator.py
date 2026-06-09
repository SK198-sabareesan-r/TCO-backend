# Strands Orchestrator: full pipeline
"""
agents/orchestrator.py
----------------------
Strands Orchestrator Agent — the top-level coordinator.

Flow:
  Input XLSX
    ↓
  [Orchestrator] reads each service row
    ↓
  [Mapping Agent]  → SQL match → LLM fallback if needed
    ↓
  [Cost Agent]     → price API → optimised pick → comparison
    ↓
  Output XLSX (3 sheets: Summary / All Matches / Cost Comparison)

The Orchestrator uses Strands to manage the multi-step pipeline,
handle errors gracefully, and produce a final structured output.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from strands import Agent

from agents.sql_generator_agent import generate_and_execute_sql
from agents.cost_agent import calculate_and_compare_costs
from utils.excel import read_input_xlsx, write_output_xlsx
from utils.token_tracker import print_token_summary, get_token_stats

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM_PROMPT = """
You are the orchestrator for a cloud migration cost estimation pipeline.

Your role is to coordinate:
1. Reading each cloud service from the input file
2. Mapping it to AWS equivalents (via SQL then LLM fallback)
3. Calculating costs (On-Demand, Savings Plan, comparison vs current provider)
4. Writing results back to the output XLSX

You manage the full pipeline end-to-end, handle failures gracefully,
and ensure every service gets processed even if some steps fail.

Log progress clearly at each stage.
"""


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE SERVICE PROCESSOR
# ─────────────────────────────────────────────────────────────────────────────

def process_single_service(service_row: dict) -> dict:
    """
    Process one service row through the full pipeline:
    SQL Generator Agent → Cost Agent → return enriched result.
    """
    svc_name = service_row.get("service_name") or service_row.get("instance_type") or "Unknown"
    logger.info(f"Processing: {svc_name} ({service_row.get('service_type','?')} / {service_row.get('current_provider','?')})")

    result = {
        "input":          service_row,
        "aws_matches":    [],
        "best_match":     {},
        "optimised":      {},
        "costs":          {},
        "comparison":     {},
        "mapping_method": "FAILED",
        "notes":          "",
    }

    try:
        # ── Step 1: Map to AWS using SQL Generator Agent ─────────────────────
        # SMART FALLBACK MODE:
        # 1. Try SQL with exact parameters
        # 2. If SQL fails (0 matches) → LLM normalizes unusual specs to next higher standard AWS specs
        # 3. Retry SQL with corrected specs
        # 4. Continue with pricing if SQL succeeds
        mapping = generate_and_execute_sql(
            service_type=service_row.get("service_type", "ec2"),
            provider=service_row.get("current_provider", "AWS"),
            instance_type=service_row.get("instance_type"),
            vcpus=service_row.get("vcpus"),
            memory_gib=service_row.get("memory_gib"),
            region=service_row.get("region"),
            tenancy=service_row.get("tenancy", "Shared"),
            operating_system=service_row.get("operating_system", "Linux"),
            database_engine=service_row.get("database_engine"),
            use_llm_fallback=True  # ENABLED: Smart fallback - LLM fixes query and retries SQL
        )
        
        result["mapping_method"] = mapping.get("method", "FAILED")
        result["notes"]          = mapping.get("notes", "")

        if not mapping.get("matches"):
            logger.warning(f"No AWS match for {svc_name}")
            result["notes"] = mapping.get("notes", "No matching AWS instance found.")
            return result

        # ── Step 2: Calculate costs ───────────────────────────────────────────
        cost_result = calculate_and_compare_costs(service_row, mapping)

        # Enrich best_match with input parameters for Excel mapping details
        best_match = cost_result.get("best_match", {})
        if best_match and mapping.get("specs_used"):
            specs = mapping["specs_used"]
            # Add input parameters to best_match for Excel output
            best_match["input_operating_system"] = specs.get("operating_system")
            best_match["input_tenancy"] = specs.get("tenancy")
            best_match["input_database_engine"] = specs.get("database_engine")
            best_match["input_region"] = specs.get("region")
            best_match["input_vcpus"] = specs.get("vcpus")
            best_match["input_memory_gib"] = specs.get("memory_gib")

        result.update({
            "aws_matches":  cost_result.get("aws_matches", []),
            "best_match":   best_match,
            "optimised":    cost_result.get("optimised", {}),
            "costs":        cost_result.get("costs", {}),
            "comparison":   cost_result.get("comparison", {}),
            "notes":        cost_result.get("notes", result["notes"]),
        })

        # ── Step 3: Generate AWS Calculator Link ──────────────────────────────
        calculator_link = ""
        if best_match.get("instance_type"):
            try:
                from utils.aws_calculator import generate_calculator_link_sync
                
                service_type = service_row.get("service_type", "ec2")
                instance_type = best_match.get("instance_type")
                region = best_match.get("location") or best_match.get("regioncode") or service_row.get("region", "US East (N. Virginia)")
                
                # Prepare parameters based on service type
                # Use AWS best_match OS (already in AWS format), fallback to normalized input OS
                aws_os = best_match.get("operatingsystem")
                if not aws_os:
                    # If AWS data doesn't have OS, normalize the input OS to AWS format
                    from utils.aws_calculator import normalize_os
                    input_os = service_row.get("operating_system", "Linux")
                    aws_os = normalize_os(input_os)
                    logger.debug(f"OS not in best_match, normalized '{input_os}' -> '{aws_os}'")
                else:
                    logger.debug(f"Using AWS OS from best_match: '{aws_os}'")
                
                calc_params = {
                    "operating_system": aws_os,
                    "tenancy": best_match.get("tenancy") or service_row.get("tenancy", "Shared"),
                    "num_instances": 1,
                    "pricing_model": "on-demand",
                    "usage_pct": 100,
                }
                
                # Add service-specific parameters
                if service_type.lower() == "rds":
                    calc_params["database_engine"] = best_match.get("databaseengine") or service_row.get("database_engine", "MySQL")
                    calc_params["deployment"] = "Single-AZ"
                    calc_params["storage_type"] = "General Purpose SSD (gp2)"
                    calc_params["storage_gb"] = int(service_row.get("storage_gb", 100))
                elif service_type.lower() == "ec2":
                    storage = service_row.get("storage_gb")
                    if storage:
                        calc_params["storage_gb"] = int(storage)
                
                logger.info(f"🔗 Generating calculator link for {instance_type}...")
                calculator_link = generate_calculator_link_sync(
                    service_type=service_type,
                    instance_type=instance_type,
                    region=region,
                    **calc_params
                )
                
                if calculator_link:
                    result["calculator_link"] = calculator_link
                    logger.info(f"  ✅ Calculator link generated")
                else:
                    logger.warning(f"  ⚠️ Calculator link generation failed")
                    result["calculator_link"] = ""
                    
            except Exception as e:
                logger.warning(f"Calculator link generation error: {e}")
                result["calculator_link"] = ""
        else:
            result["calculator_link"] = ""

        # Log quick summary
        opt = result.get("optimised", {})
        comp = result.get("comparison", {})
        savings = comp.get("savings", {})
        savings_pct = (
            savings.get("percent")
            or opt.get("discount_percent")
            or "?"
        )
        logger.info(
            f"  ✅ {svc_name} → {result['best_match'].get('instance_type','?')} | "
            f"OnDemand: ${result['costs'].get('ondemand',{}).get('monthly_usd','?')}/mo | "
            f"Optimised: ${opt.get('monthly_usd','?')}/mo | "
            f"Savings: {savings_pct}%"
        )

    except Exception as e:
        logger.error(f"Pipeline error for {svc_name}: {e}", exc_info=True)
        result["notes"] = f"Processing error: {str(e)}"

    return result


# ─────────────────────────────────────────────────────────────────────────────
# BATCH PROCESSOR
# ─────────────────────────────────────────────────────────────────────────────

def process_all_services(services: list[dict], output_path: str = None, limit: int = None, progress_callback=None) -> list[dict]:
    """
    Process all services from input XLSX and return enriched results.
    Saves incrementally after each service to avoid data loss.

    Args:
        services: List of service dictionaries to process
        output_path: Path to save incremental results (optional)
        limit: Maximum number of services to process (optional, for testing)
        progress_callback: Callback function(message, progress_pct) for UI updates
    """
    results = []

    # Apply limit if specified
    if limit and limit > 0:
        services = services[:limit]
        logger.info(f"⚠️ LIMIT ENABLED: Processing only first {limit} services (out of {len(services)} total)")

    total = len(services)

    for idx, service_row in enumerate(services, 1):
        # Calculate progress: 30% to 95% range (25% already used for loading)
        base_progress = 30 + int((idx / total) * 65)

        service_name = service_row.get('service_name') or service_row.get('Service Name') or service_row.get('instance_type') or f"Service-{idx}"

        # Phase 1: Start processing
        logger.info(f"🔄 ─── [{idx}/{total}] ({round((idx/total)*100,1)}%) Processing service ───")
        logger.info(f"📋 Service: {service_name}")
        if progress_callback:
            progress_callback(f"🔄 [{idx}/{total}] Starting: {service_name}", base_progress)

        # Phase 2: Finding AWS matches
        if progress_callback:
            progress_callback(f"🔍 [{idx}/{total}] Finding AWS matches: {service_name}", base_progress + 1)

        # Phase 3: Execute mapping and cost calculation
        if progress_callback:
            progress_callback(f"💰 [{idx}/{total}] Calculating costs: {service_name}", base_progress + 2)

        result = process_single_service(service_row)
        results.append(result)

        # Phase 4: Generating calculator link
        if progress_callback:
            progress_callback(f"🔗 [{idx}/{total}] Generating calculator link: {service_name}", base_progress + 3)

        # Phase 5: Service complete
        if progress_callback:
            progress_callback(f"✅ [{idx}/{total}] Completed: {service_name}", base_progress + 4)

        logger.info(f"✅ [{idx}/{total}] Service processed successfully")

        # Incremental save after each service
        if output_path:
            try:
                write_output_xlsx(results, output_path)
                logger.info(f"💾 Incremental save: {idx}/{total} services saved to {output_path}")
            except Exception as e:
                logger.warning(f"⚠️ Incremental save failed: {e}")

    logger.info(f"Processed {total} services.")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# PRINT SUMMARY TO CONSOLE
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(results: list[dict]):
    """Print a quick cost summary to console."""
    print("\n" + "=" * 80)
    print("  CLOUD MIGRATION COST ESTIMATION SUMMARY")
    print("=" * 80)
    print(f"  {'Service':<20} {'Provider':<10} {'AWS Match':<20} {'Current/mo':<14} {'AWS Opt/mo':<14} {'Savings'}")
    print("  " + "-" * 78)

    total_current = 0
    total_opt     = 0

    for r in results:
        inp    = r.get("input", {})
        best   = r.get("best_match", {})
        opt    = r.get("optimised", {})
        comp   = r.get("comparison", {})
        sav    = comp.get("savings", {})

        name     = str(inp.get("service_name") or "Unknown")[:18]
        provider = str(inp.get("current_provider") or "")[:8]
        match    = str(best.get("instance_type") or "No match")[:18]
        cur_m    = inp.get("current_monthly_cost_usd")
        opt_m    = opt.get("monthly_usd")
        sav_p    = sav.get("percent")

        cur_str = f"${float(cur_m):.2f}" if cur_m else "N/A"
        opt_str = f"${float(opt_m):.2f}" if opt_m else "N/A"
        sav_str = f"{sav_p:.1f}%" if sav_p is not None else "N/A"

        print(f"  {name:<20} {provider:<10} {match:<20} {cur_str:<14} {opt_str:<14} {sav_str}")

        if cur_m: total_current += float(cur_m)
        if opt_m: total_opt     += float(opt_m)

    print("  " + "-" * 78)
    total_sav = total_current - total_opt
    total_pct = (total_sav / total_current * 100) if total_current else 0
    print(f"  {'TOTAL':<20} {'':<10} {'':<20} ${total_current:.2f}{'':>8} ${total_opt:.2f}{'':>8} {total_pct:.1f}%")
    print("=" * 80 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def run_migration_pipeline(input_xlsx: str, output_xlsx: Optional[str] = None, source_provider: Optional[str] = None, limit: int = None, progress_callback=None) -> str:
    """
    Full end-to-end pipeline:
      Read XLSX → Map → Cost → Write XLSX

    Args:
        input_xlsx:  Path to user's input XLSX with current cloud services.
        output_xlsx: Path for output XLSX (defaults to input_filename_aws_estimate.xlsx)
        source_provider: Source cloud provider (Azure or GCP) - overrides filename detection
        limit: Maximum number of services to process (optional, for testing)
        progress_callback: Callback function(message, progress_pct) for UI updates

    Returns:
        Path to the output XLSX file.
    """
    input_path  = Path(input_xlsx)
    output_path = output_xlsx or str(input_path.parent / f"{input_path.stem}_aws_estimate.xlsx")

    logger.info(f"Starting migration pipeline: {input_xlsx}")
    if source_provider:
        logger.info(f"Source provider: {source_provider} (from user input)")
    if limit:
        logger.info(f"⚠️ TEST MODE: Will process only first {limit} services")

    # ── 1. Read input ─────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback("📖 Reading Excel file...", 25)

    services = read_input_xlsx(input_xlsx, source_provider=source_provider)
    logger.info(f"Loaded {len(services)} services from {input_xlsx}")

    if progress_callback:
        progress_callback(f"✅ Loaded {len(services)} services. Starting analysis...", 30)

    # ── 2. Process all services (with incremental saves) ─────────────────────
    results = process_all_services(services, output_path, limit=limit, progress_callback=progress_callback)

    # ── 3. Generate COMBINED calculator link for ALL services ────────────────
    if progress_callback:
        progress_callback("🔗 Generating combined AWS Calculator link for all services...", 96)

    logger.info("🔗 Generating COMBINED calculator link for all services...")
    combined_link = ""
    try:
        from utils.combined_calculator import generate_combined_calculator_link_sync
        combined_link = generate_combined_calculator_link_sync(results)

        if combined_link:
            logger.info(f"✅ Generated combined calculator link: {combined_link[:80]}...")
            for result in results:
                result["combined_calculator_link"] = combined_link
            # Pass combined link back to API via progress callback (3rd arg)
            if progress_callback:
                try:
                    progress_callback("🔗 Combined AWS Calculator link ready!", 98, combined_link)
                except TypeError:
                    pass  # old callback signature without combined_link arg
        else:
            logger.warning("⚠️ Failed to generate combined calculator link")
            for result in results:
                result["combined_calculator_link"] = ""
    except Exception as e:
        logger.error(f"❌ Error generating combined calculator link: {e}", exc_info=True)
        for result in results:
            result["combined_calculator_link"] = ""

    # ── 4. Print console summary ──────────────────────────────────────────────
    print_summary(results)

    # ── 5. Print token usage summary ──────────────────────────────────────────
    print_token_summary()

    # ── 6. Final write output XLSX ────────────────────────────────────────────
    write_output_xlsx(results, output_path)
    logger.info(f"Final output written to: {output_path}")

    return output_path