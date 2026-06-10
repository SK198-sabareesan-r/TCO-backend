# XLSX reader + writer
"""
utils/excel.py
--------------
Read input XLSX (user's current cloud services + specs) and write
enriched output XLSX with AWS matches, cost estimates and comparison.
"""

import logging
from pathlib import Path
from typing import Any, Optional
import openpyxl
from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette
# ─────────────────────────────────────────────────────────────────────────────
HEADER_FILL   = PatternFill("solid", fgColor="1F3864")   # dark navy
SECTION_FILL  = PatternFill("solid", fgColor="2E75B6")   # AWS blue
MATCH_FILL    = PatternFill("solid", fgColor="D9E1F2")   # light blue
OPT_FILL      = PatternFill("solid", fgColor="E2EFDA")   # light green
WARN_FILL     = PatternFill("solid", fgColor="FCE4D6")   # light orange
WHITE_FONT    = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
BOLD_FONT     = Font(name="Calibri", bold=True, size=10)
NORMAL_FONT   = Font(name="Calibri", size=10)
MONEY_FORMAT  = '#,##0.00'
PCT_FORMAT    = '0.00"%"'

THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ─────────────────────────────────────────────────────────────────────────────
# INPUT READER
# ─────────────────────────────────────────────────────────────────────────────

# Expected columns in the user-supplied XLSX.
# Column names are normalised (lower, strip, replace space→_).
REQUIRED_COLUMNS = ["service_type", "current_provider"]

COLUMN_ALIASES = {
    # service identification
    "service":              "service_type",
    "service type":         "service_type",
    "service_type":         "service_type",
    # provider
    "cloud":                "current_provider",
    "provider":             "current_provider",
    "current cloud":        "current_provider",
    "current_provider":     "current_provider",
    # ── compute ──────────────────────────────────────────────────────────────
    "vcpu":                 "vcpus",
    "vcpus":                "vcpus",
    "cpu":                  "vcpus",
    "cpu_cores":            "vcpus",
    "cores":                "vcpus",
    "number of vcpus":      "vcpus",       # GCP Cloud Console
    "virtual cpus":         "vcpus",
    "memory":               "memory_gib",
    "memory (gib)":         "memory_gib",
    "memory_gb":            "memory_gib",
    "memory (gb)":          "memory_gib",  # GCP Cloud Console
    "ram":                  "memory_gib",
    "ram (gib)":            "memory_gib",
    "instance":             "instance_type",
    "instance type":        "instance_type",
    "instance_type":        "instance_type",
    "machine type":         "instance_type",   # GCP Compute Engine export
    "machine_type":         "instance_type",   # GCP programmatic
    "machine series":       "instance_type",   # GCP
    "vm size":              "instance_type",
    "vm_size":              "instance_type",
    # ── Azure-specific ───────────────────────────────────────────────────────
    "size":                 "instance_type",    # Azure VM Size
    "name":                 "service_name",     # Azure resource Name
    "location":             "region",           # Azure Location
    "sku":                  "instance_type",    # Azure SKU
    "capacity":             "vcpus",            # Azure SQL vCore capacity
    "datamaxsizegb":        "storage_gb",       # Azure SQL storage
    "storagesizegb":        "storage_gb",       # Azure PostgreSQL storage
    "osname":               "operating_system", # Azure OS Name
    "tier":                 "tier",             # Azure tier
    # ── GCP-specific ─────────────────────────────────────────────────────────
    "machine_series":       "instance_type",    # GCP n2, e2, c3 series
    "provisioning_model":   "tenancy",          # GCP standard/preemptible
    "database_version":     "database_engine",  # GCP Cloud SQL version
    "database version":     "database_engine",
    "db_version":           "database_engine",
    "database_type":        "database_engine",
    "database type":        "database_engine",
    "engine":               "database_engine",
    "zone":                 "region",           # GCP zone → region
    "availability_zone":    "region",
    # ── region / tenancy ─────────────────────────────────────────────────────
    "region":               "region",
    "region_preference":    "region",
    "tenancy":              "tenancy",
    # ── OS ───────────────────────────────────────────────────────────────────
    "os":                   "operating_system",
    "operating system":     "operating_system",
    "operating_system":     "operating_system",
    "platform":             "operating_system",  # GCP
    "image":                "operating_system",  # GCP boot image
    # ── cost columns ─────────────────────────────────────────────────────────
    "current monthly cost": "current_monthly_cost_usd",
    "current_monthly_cost": "current_monthly_cost_usd",
    "monthly cost":         "current_monthly_cost_usd",
    "cost (usd)":           "current_monthly_cost_usd",
    "cost":                 "current_monthly_cost_usd",
    "total price":          "current_monthly_cost_usd",   # GCP TCO tool
    "total_price":          "current_monthly_cost_usd",   # GCP TCO tool
    "total cost":           "current_monthly_cost_usd",
    "monthly_cost":         "current_monthly_cost_usd",
    "price":                "current_monthly_cost_usd",
    "amount":               "current_monthly_cost_usd",
    # ── storage ──────────────────────────────────────────────────────────────
    "storage (gb)":         "storage_gb",
    "storage":              "storage_gb",
    "storage_gb":           "storage_gb",
    "disk_size":            "storage_gb",
    "disk size":            "storage_gb",
    "disk size (gb)":       "storage_gb",
    "data disk size":       "storage_gb",
    "volume size":          "storage_gb",
    "capacity (gb)":        "storage_gb",
    # ── quantity ─────────────────────────────────────────────────────────────
    "count":                "number_of_instances",
    "quantity":             "number_of_instances",
    "instances":            "number_of_instances",
    "number of instances":  "number_of_instances",
    "number_of_instances":  "number_of_instances",
    "instance count":       "number_of_instances",
    "vm count":             "number_of_instances",
    # ── misc ─────────────────────────────────────────────────────────────────
    "workload":             "workload",
    "notes":                "notes",
    "service_name":         "service_name",
    "server_name":          "service_name",
    "server name":          "service_name",
    "resource name":        "service_name",   # GCP/Azure resource name
    "resource_name":        "service_name",
    "application":          "application",
    "environment":          "environment",
    "description":          "service_name",   # GCP service description
}

# Sheet name to service type mapping for multi-sheet Excel files
SHEET_SERVICE_MAPPING = {
    "virtual machines": "ec2",
    "virtual machine": "ec2",
    "vms": "ec2",
    "compute": "ec2",
    "sql dbs": "rds",
    "sql databases": "rds",
    "postgresql flexible": "rds",
    "postgresql": "rds",
    "mysql flexible": "rds",
    "mysql": "rds",
    "storage acc": "s3",
    "storage accounts": "s3",
    "storage": "s3",
    "blob storage": "s3",
}


def _normalise(header: str) -> str:
    return str(header).strip().lower()


def read_input_xlsx(filepath: str, source_provider: Optional[str] = None) -> list[dict]:
    """
    Read the user-provided XLSX and return a list of service-row dicts
    with normalised field names.
    
    Supports:
    - Single-sheet files (backward compatible)
    - Multi-sheet files (Azure/GCP exports with multiple service types)
    
    Args:
        filepath: Path to the Excel file
        source_provider: Source cloud provider (Azure or GCP) - if provided, overrides filename detection
    
    Auto-detects provider from filename if not provided:
    - "azure" in filename → Azure
    - "gcp" in filename → GCP
    - Otherwise uses existing logic
    """
    wb = openpyxl.load_workbook(filepath, data_only=True)
    
    # Use provided source_provider, otherwise auto-detect from filename
    if source_provider:
        auto_provider = source_provider
        logger.info(f"Using provider from user input: {auto_provider}")
    else:
        # Auto-detect provider from filename (backward compatibility)
        filename_lower = Path(filepath).stem.lower()
        auto_provider = None
        if "azure" in filename_lower:
            auto_provider = "Azure"
        elif "gcp" in filename_lower:
            auto_provider = "GCP"
        if auto_provider:
            logger.info(f"Auto-detected provider from filename: {auto_provider}")
    
    # Check if multi-sheet file with known service sheets
    sheet_names_lower = [s.lower() for s in wb.sheetnames]
    known_sheets = []
    for sheet_name in wb.sheetnames:
        sheet_lower = sheet_name.lower()
        if sheet_lower in SHEET_SERVICE_MAPPING:
            known_sheets.append(sheet_name)
    
    # If we found known service sheets, process them all
    if known_sheets:
        logger.info(f"Multi-sheet file detected. Processing {len(known_sheets)} sheets: {', '.join(known_sheets)}")
        all_services = []
        for sheet_name in known_sheets:
            services = _read_sheet(wb[sheet_name], sheet_name, auto_provider)
            all_services.extend(services)
            logger.info(f"  - {sheet_name}: {len(services)} services")
        logger.info(f"Total services loaded: {len(all_services)}")
        return all_services
    
    # Otherwise, process active sheet (backward compatible)
    logger.info(f"Single-sheet file detected. Processing active sheet.")
    return _read_sheet(wb.active, None, auto_provider)


def _read_sheet(ws, sheet_name: str = None, auto_provider: str = None) -> list[dict]:
    """
    Read a single worksheet and return list of service dicts.
    
    Args:
        ws: openpyxl worksheet
        sheet_name: Name of the sheet (used to detect service type)
        auto_provider: Auto-detected provider from filename
    """
    from utils.kpi_loader import normalize_service_name
    
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    raw_headers = [_normalise(h) if h else "" for h in rows[0]]
    headers = [COLUMN_ALIASES.get(h, h.replace(" ", "_")) for h in raw_headers]

    # Detect service type from sheet name using KPI mappings
    auto_service_type = None
    if sheet_name:
        # Try KPI service_name_mappings first
        auto_service_type = normalize_service_name(sheet_name, auto_provider)
        # Fallback to hardcoded mapping if KPI doesn't have it
        if not auto_service_type:
            sheet_lower = sheet_name.lower()
            auto_service_type = SHEET_SERVICE_MAPPING.get(sheet_lower)

    services = []
    for row in rows[1:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        record = {}
        for col_idx, value in enumerate(row):
            if col_idx < len(headers) and headers[col_idx]:
                record[headers[col_idx]] = value
        
        # Auto-detect service_type using KPI mappings
        if "service_type" not in record or not record["service_type"]:
            if auto_service_type:
                record["service_type"] = auto_service_type
            elif record.get("vcpus") or record.get("memory_gib"):
                record["service_type"] = "ec2"
            else:
                record["service_type"] = "ec2"  # default
        else:
            # Normalize the service_type from the record using KPI mappings
            normalized = normalize_service_name(str(record["service_type"]), auto_provider)
            if normalized:
                record["service_type"] = normalized
        
        # Auto-detect provider from filename or existing logic
        if "current_provider" not in record or not record["current_provider"]:
            if auto_provider:
                record["current_provider"] = auto_provider
            else:
                record["current_provider"] = "AWS"  # default
        
        # Defaults
        record.setdefault("number_of_instances", 1)
        record.setdefault("tenancy", "Shared")
        # Set operating_system default - check if it exists and is not None
        if not record.get("operating_system"):
            record["operating_system"] = "Linux"
        
        # Set storage_gb default
        if "storage_gb" not in record or record["storage_gb"] is None:
            record["storage_gb"] = 0
        
        # For S3/Storage services, if storage_gb is 0, use a reasonable default for cost estimation
        # Azure Storage Accounts often don't export actual storage size, so we estimate
        if record.get("service_type") in ("s3", "storage"):
            storage_val = record.get("storage_gb")
            try:
                if storage_val is None or float(storage_val) == 0:
                    record["storage_gb"] = 100  # Default to 100 GB for cost estimation
                    logger.info(f"S3 service '{record.get('service_name', 'unknown')}' has no storage size, defaulting to 100 GB for cost estimation")
            except (ValueError, TypeError):
                record["storage_gb"] = 100
                logger.warning(f"S3 service '{record.get('service_name', 'unknown')}' has invalid storage_gb value '{storage_val}', defaulting to 100 GB")
        
        record.setdefault("current_monthly_cost_usd", None)
        services.append(record)

    return services


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT WRITER
# ─────────────────────────────────────────────────────────────────────────────

def _header_row(ws, cols: list[str], row: int, fill=HEADER_FILL):
    for c, label in enumerate(cols, 1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.font = WHITE_FONT
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = BORDER


def _data_cell(ws, row: int, col: int, value, fmt=None, bold=False, fill=None):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(name="Calibri", bold=bold, size=10)
    cell.border = BORDER
    cell.alignment = Alignment(horizontal="center")
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    return cell


def write_output_xlsx(results: list[dict], output_path: str):
    """
    Write enriched migration results to output XLSX with 5 sheets:
      1. Summary          – one row per input service, best AWS match + cost comparison
      2. All Matches      – all AWS candidates per service with costs
      3. CSP Options      – all 6 Compute Savings Plan options per instance
      4. Cost Comparison  – side-by-side: Current vs AWS OnDemand vs Optimised
      5. Mapping Details  – detailed parameters used for comparison and mapping
    """
    wb = Workbook()

    _write_summary_sheet(wb, results)
    _write_all_matches_sheet(wb, results)
    _write_csp_options_sheet(wb, results)
    _write_comparison_sheet(wb, results)
    _write_mapping_details_sheet(wb, results)

    # Remove default empty sheet if still present
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    wb.save(output_path)
    logger.info(f"Output XLSX saved → {output_path}")


# ── Sheet 1 : Summary ────────────────────────────────────────────────────────

def _write_summary_sheet(wb: Workbook, results: list[dict]):
    ws = wb.create_sheet("Summary", 0)
    ws.sheet_view.showGridLines = False

    NUM_COLS = 13  # total data columns (no longer a separate combined column per row)

    # ── Row 1: Combined calculator link banner ────────────────────────────────
    combined_link = ""
    for r in results:
        combined_link = r.get("combined_calculator_link", "")
        if combined_link:
            break

    # Merge A1 across all columns for the banner
    ws.merge_cells(f"A1:{get_column_letter(NUM_COLS)}1")
    banner = ws["A1"]
    if combined_link:
        banner.value = f"🔗 View ALL {len(results)} Services in AWS Calculator (Combined Estimate)"
        banner.hyperlink = combined_link
        banner.style = "Hyperlink"
        banner.font  = Font(name="Calibri", bold=True, size=12, color="0563C1", underline="single")
        banner.fill  = PatternFill("solid", fgColor="DEEAF1")  # light blue banner
    else:
        banner.value = "ℹ️ Combined AWS Calculator link not available (generated after all services are processed)"
        banner.font  = Font(name="Calibri", italic=True, size=11, color="595959")
        banner.fill  = PatternFill("solid", fgColor="F2F2F2")
    banner.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 28

    # ── Row 2: Column headers ─────────────────────────────────────────────────
    title_cols = [
        "Service Name", "Type", "Provider",
        "Current Instance / Config",
        "Recommended AWS Instance", "AWS Region",
        "AWS OnDemand Hourly", "AWS OnDemand Monthly", "AWS OnDemand Annual",
        "Optimised Plan", "Optimised Monthly", "Optimised Annual",
        "Notes",
    ]
    _header_row(ws, title_cols, row=2)
    ws.row_dimensions[2].height = 36

    # ── Rows 3+: Data ─────────────────────────────────────────────────────────
    od_monthly_total  = 0.0
    od_annual_total   = 0.0
    opt_monthly_total = 0.0
    opt_annual_total  = 0.0

    for r_idx, result in enumerate(results, start=3):
        inp   = result.get("input", {})
        best  = result.get("best_match", {})
        opt   = result.get("optimised", {})
        costs = result.get("costs", {})
        calc_link = result.get("calculator_link", "")

        od_hourly  = costs.get("ondemand", {}).get("hourly_usd")
        od_monthly = costs.get("ondemand", {}).get("monthly_usd")
        od_annual  = costs.get("ondemand", {}).get("annual_usd")
        opt_monthly = opt.get("monthly_usd")
        opt_annual  = opt.get("annual_usd")
        opt_plan    = opt.get("plan_label", "On-Demand")

        row_data = [
            inp.get("service_name", f"Service-{r_idx-2}"),
            inp.get("service_type", ""),
            inp.get("current_provider", ""),
            inp.get("instance_type") or f"{inp.get('vcpus','?')}vCPU / {inp.get('memory_gib','?')}GiB",
            best.get("instance_type", "No match"),
            best.get("regioncode") or best.get("region", inp.get("region", "")),
            od_hourly,
            od_monthly,
            od_annual,
            opt_plan,
            opt_monthly,
            opt_annual,
            result.get("notes", ""),
        ]

        money_cols = {7, 8, 9, 11, 12}

        for c_idx, val in enumerate(row_data, 1):
            fmt  = MONEY_FORMAT if c_idx in money_cols else None
            cell = _data_cell(ws, r_idx, c_idx, val, fmt=fmt)

        # Accumulate totals
        od_monthly_total  += float(od_monthly  or 0)
        od_annual_total   += float(od_annual   or 0)
        opt_monthly_total += float(opt_monthly or 0)
        opt_annual_total  += float(opt_annual  or 0)

    # ── TOTAL row ─────────────────────────────────────────────────────────────
    total_row = len(results) + 3
    _data_cell(ws, total_row, 1, "TOTAL", bold=True, fill=SECTION_FILL)
    for c in range(2, 7):
        _data_cell(ws, total_row, c, "", fill=SECTION_FILL)
    _data_cell(ws, total_row, 7,  "",                             fill=SECTION_FILL)   # hourly — no sum
    _data_cell(ws, total_row, 8,  round(od_monthly_total,  2), fmt=MONEY_FORMAT, bold=True, fill=SECTION_FILL)
    _data_cell(ws, total_row, 9,  round(od_annual_total,   2), fmt=MONEY_FORMAT, bold=True, fill=SECTION_FILL)
    _data_cell(ws, total_row, 10, "",                             fill=SECTION_FILL)   # plan label — no sum
    _data_cell(ws, total_row, 11, round(opt_monthly_total, 2), fmt=MONEY_FORMAT, bold=True, fill=OPT_FILL)
    _data_cell(ws, total_row, 12, round(opt_annual_total,  2), fmt=MONEY_FORMAT, bold=True, fill=OPT_FILL)
    _data_cell(ws, total_row, 13, "",                             fill=SECTION_FILL)

    # Column widths
    widths = [22, 10, 10, 28, 22, 22, 18, 20, 20, 22, 20, 20, 30]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "A3"


# ── Sheet 2 : All Matches ────────────────────────────────────────────────────

def _write_all_matches_sheet(wb: Workbook, results: list[dict]):
    ws = wb.create_sheet("All Matches", 1)
    ws.sheet_view.showGridLines = False

    cols = [
        "Service Name", "Input vCPUs / Storage", "Input Memory (GiB) / Storage GB",
        "AWS Instance Type", "AWS vCPUs", "AWS Memory (GiB)",
        "Region", "Tenancy",
        "OnDemand Hourly", "OnDemand Monthly", "OnDemand Annual",
        "Plan Monthly", "Plan Annual", "Plan Discount %",
        "Spot Hourly", "Spot Monthly", "Spot Annual", "Spot Discount %",
    ]
    _header_row(ws, cols, row=1)
    ws.row_dimensions[1].height = 36

    current_row = 2
    for result in results:
        inp        = result.get("input", {})
        matches    = result.get("aws_matches", [])
        best       = result.get("best_match", {})
        svc_name   = inp.get("service_name", "")

        if not matches:
            _data_cell(ws, current_row, 1, svc_name)
            _data_cell(ws, current_row, 2, inp.get("vcpus"))
            _data_cell(ws, current_row, 3, inp.get("memory_gib"))
            _data_cell(ws, current_row, 4, "❌ No match found", fill=WARN_FILL)
            current_row += 1
            continue

        for match in matches:
            mc = match.get("costs", {})
            od = mc.get("ondemand", {})
            sp = mc.get("best_savings_plan", {})
            spot = mc.get("spot", {})

            is_best  = match.get("instance_type") == best.get("instance_type")
            row_fill = OPT_FILL if is_best else MATCH_FILL

            # For S3, build a display name since there's no instance_type
            display_instance = match.get("instance_type")
            if not display_instance:
                sc = match.get("storageclass") or match.get("storage_class") or "Standard"
                display_instance = f"S3 {sc}"

            # For S3, show storage class info instead of blank vCPUs/memory
            svc_type = inp.get("service_type", "").lower()
            match_vcpus  = match.get("vcpus") if svc_type not in ("s3", "storage") else "—"
            match_memory = match.get("memory_gib") if svc_type not in ("s3", "storage") else "—"

            row_data = [
                svc_name,
                inp.get("vcpus") if svc_type not in ("s3", "storage") else "—",
                inp.get("memory_gib") if svc_type not in ("s3", "storage") else f"{inp.get('storage_gb','?')} GB",
                display_instance,
                match_vcpus, match_memory,
                match.get("regioncode") or match.get("region"), match.get("tenancy"),
                od.get("hourly_usd"), od.get("monthly_usd"), od.get("annual_usd"),
                sp.get("monthly_usd"), sp.get("annual_usd"), sp.get("discount_percent"),
                spot.get("hourly_usd"), spot.get("monthly_usd"), spot.get("annual_usd"), spot.get("discount_percent"),
            ]
            money_cols = {9, 10, 11, 12, 13, 15, 16, 17}
            pct_cols   = {14, 18}
            for c_idx, val in enumerate(row_data, 1):
                fmt = MONEY_FORMAT if c_idx in money_cols else (PCT_FORMAT if c_idx in pct_cols else None)
                # Highlight best match and spot pricing
                cell_fill = row_fill if c_idx in {4,9,10,11,12,13} else None
                if c_idx in {15, 16, 17} and spot.get("monthly_usd"):  # Highlight spot pricing if available
                    cell_fill = PatternFill("solid", fgColor="FFF2CC")  # Light yellow for spot
                _data_cell(ws, current_row, c_idx, val, fmt=fmt, fill=cell_fill)
            current_row += 1

    widths = [18, 12, 15, 20, 12, 15, 22, 12, 16, 18, 18, 16, 16, 12, 14, 16, 16, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


# ── Sheet 3 : CSP Options ─────────────────────────────────────────────────────

def _write_csp_options_sheet(wb: Workbook, results: list[dict]):
    """
    Sheet showing all Compute Savings Plan options + Spot pricing for each instance.
    Shows all 6 CSP combinations + Spot: 1yr/3yr × no_upfront/partial_upfront/all_upfront + Spot
    """
    ws = wb.create_sheet("CSP Options", 2)
    ws.sheet_view.showGridLines = False

    # Title banner
    ws.merge_cells("A1:M1")
    title_cell = ws["A1"]
    title_cell.value = "Compute Savings Plans & Spot Pricing - All Options"
    title_cell.font  = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    title_cell.fill  = HEADER_FILL
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    cols = [
        "Service Name", "AWS Instance Type", "Region",
        "Plan Term", "Payment Option",
        "Upfront Fee (USD)", "Hourly Rate (USD)", "Monthly Cost (USD)", "Annual Cost (USD)",
        "Discount %", "Monthly Savings (USD)", "Annual Savings (USD)",
        "vs OnDemand Monthly",
    ]
    _header_row(ws, cols, row=2, fill=SECTION_FILL)
    ws.row_dimensions[2].height = 36

    current_row = 3
    
    # Plan order for consistent display
    plan_order = [
        "1yr_no_upfront", "1yr_partial_upfront", "1yr_all_upfront",
        "3yr_no_upfront", "3yr_partial_upfront", "3yr_all_upfront",
    ]
    
    for result in results:
        inp = result.get("input", {})
        best = result.get("best_match", {})
        costs = result.get("costs", {})
        svc_name = inp.get("service_name", "")
        instance_type = best.get("instance_type", "")
        region = best.get("regioncode") or best.get("region", "")
        
        # Get CSP plans and OnDemand for comparison
        csp_plans = costs.get("compute_savings_plans", {})
        od = costs.get("ondemand", {})
        od_monthly = od.get("monthly_usd", 0)
        best_sp = costs.get("best_savings_plan", {})
        best_plan_type = best_sp.get("plan_type", "")
        
        if not csp_plans:
            # No CSP available for this instance
            _data_cell(ws, current_row, 1, svc_name)
            _data_cell(ws, current_row, 2, instance_type)
            _data_cell(ws, current_row, 3, region)
            _data_cell(ws, current_row, 4, "N/A", fill=WARN_FILL)
            _data_cell(ws, current_row, 5, "No CSP available", fill=WARN_FILL)
            current_row += 1
            continue
        
        # Write all CSP options for this instance
        for plan_type in plan_order:
            if plan_type not in csp_plans:
                continue
            
            plan = csp_plans[plan_type]
            is_best = (plan_type == best_plan_type)
            row_fill = OPT_FILL if is_best else None
            
            # Parse plan type
            term, payment = plan_type.split("_", 1)
            term_display = term.upper()  # "1YR" or "3YR"
            payment_display = payment.replace("_", " ").title()  # "No Upfront", "Partial Upfront", "All Upfront"
            
            row_data = [
                svc_name,
                instance_type,
                region,
                term_display,
                payment_display,
                plan.get("upfront_fee_usd", 0),
                plan.get("hourly_usd", 0),
                plan.get("monthly_usd", 0),
                plan.get("annual_usd", 0),
                plan.get("discount_percent", 0),
                plan.get("monthly_savings_usd", 0),
                plan.get("annual_savings_usd", 0),
                od_monthly,
            ]
            
            money_cols = {6, 7, 8, 9, 11, 12, 13}
            pct_cols = {10}
            
            for c_idx, val in enumerate(row_data, 1):
                fmt = MONEY_FORMAT if c_idx in money_cols else (PCT_FORMAT if c_idx in pct_cols else None)
                cell_fill = row_fill if c_idx in {8, 9, 11, 12} else None
                _data_cell(ws, current_row, c_idx, val, fmt=fmt, fill=cell_fill)
            
            current_row += 1
        
        # Add Spot pricing row (if available and Shared tenancy)
        spot = costs.get("spot", {})
        tenancy = best.get("tenancy", "Shared")
        if spot and spot.get("monthly_usd") and tenancy.lower() == "shared":
            # Spot pricing row with yellow highlight
            spot_fill = PatternFill("solid", fgColor="FFF2CC")  # Light yellow
            
            row_data = [
                svc_name,
                instance_type,
                region,
                "SPOT",  # Plan Term
                "Variable Pricing",  # Payment Option
                0,  # No upfront fee
                spot.get("hourly_usd", 0),
                spot.get("monthly_usd", 0),
                spot.get("annual_usd", 0),
                spot.get("discount_percent", 0),
                spot.get("monthly_savings_usd", 0),
                spot.get("annual_savings_usd", 0),
                od_monthly,
            ]
            
            money_cols = {6, 7, 8, 9, 11, 12, 13}
            pct_cols = {10}
            
            for c_idx, val in enumerate(row_data, 1):
                fmt = MONEY_FORMAT if c_idx in money_cols else (PCT_FORMAT if c_idx in pct_cols else None)
                # Highlight entire Spot row in yellow
                cell_fill = spot_fill if c_idx in {4, 5, 8, 9, 11, 12} else None
                _data_cell(ws, current_row, c_idx, val, fmt=fmt, fill=cell_fill)
            
            current_row += 1
        
        # Add blank row between services for readability
        current_row += 1

    widths = [18, 20, 22, 12, 18, 18, 18, 20, 20, 12, 22, 22, 22]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A3"


# ── Sheet 4 : Cost Comparison ─────────────────────────────────────────────────

def _write_comparison_sheet(wb: Workbook, results: list[dict]):
    ws = wb.create_sheet("Cost Comparison", 3)
    ws.sheet_view.showGridLines = False

    NUM_COLS = 11

    # ── Row 1: Combined calculator link banner ────────────────────────────────
    combined_link = ""
    for r in results:
        combined_link = r.get("combined_calculator_link", "")
        if combined_link:
            break

    ws.merge_cells(f"A1:{get_column_letter(NUM_COLS)}1")
    banner = ws["A1"]
    if combined_link:
        banner.value = f"🔗 Open ALL {len(results)} Services in AWS Calculator (Combined Estimate) — shows On-Demand prices by default"
        banner.hyperlink = combined_link
        banner.style = "Hyperlink"
        banner.font  = Font(name="Calibri", bold=True, size=12, color="0563C1", underline="single")
        banner.fill  = PatternFill("solid", fgColor="DEEAF1")
    else:
        banner.value = "ℹ️ Combined AWS Calculator link not available"
        banner.font  = Font(name="Calibri", italic=True, size=11, color="595959")
        banner.fill  = PatternFill("solid", fgColor="F2F2F2")
    banner.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 28

    # ── Row 2: Note about cost difference ────────────────────────────────────
    ws.merge_cells(f"A2:{get_column_letter(NUM_COLS)}2")
    note = ws["A2"]
    note.value = (
        "ℹ️ Note: 'AWS Calculator' shows On-Demand prices. "
        "'AWS Optimised' below uses Savings Plans / Reserved Instances — hence lower cost than the calculator total."
    )
    note.font  = Font(name="Calibri", italic=True, size=10, color="595959")
    note.fill  = PatternFill("solid", fgColor="FFFCE6")
    note.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 24

    # ── Row 3: Column headers ─────────────────────────────────────────────────
    cols = [
        "Service", "Current Provider", "Current Instance",
        "AWS OnDemand Hourly", "AWS OnDemand Monthly", "AWS OnDemand Annual",
        "AWS Optimised Plan", "AWS Optimised Monthly", "AWS Optimised Annual",
        "Monthly Savings", "Annual Savings",
    ]
    _header_row(ws, cols, row=3, fill=SECTION_FILL)
    ws.row_dimensions[3].height = 32

    totals = {
        "od_monthly": 0,      "od_annual": 0,
        "opt_monthly": 0,     "opt_annual": 0,
        "savings_monthly": 0, "savings_annual": 0,
    }

    for r_idx, result in enumerate(results, start=4):
        inp   = result.get("input", {})
        best  = result.get("best_match", {})
        opt   = result.get("optimised", {})
        costs = result.get("costs", {})

        cur_monthly = inp.get("current_monthly_cost_usd") or 0
        cur_annual  = round(float(cur_monthly) * 12, 2)
        od_h        = costs.get("ondemand", {}).get("hourly_usd")
        od_m        = costs.get("ondemand", {}).get("monthly_usd") or 0
        od_a        = costs.get("ondemand", {}).get("annual_usd") or 0
        opt_m       = opt.get("monthly_usd") or 0
        opt_a       = opt.get("annual_usd") or 0
        opt_plan    = opt.get("plan_label", "On-Demand")

        sav_m = round(float(cur_monthly) - float(opt_m), 2) if cur_monthly else None
        sav_a = round(float(cur_annual)  - float(opt_a), 2) if cur_monthly else None

        row_data = [
            inp.get("service_name", f"Service-{r_idx-3}"),
            inp.get("current_provider", ""),
            inp.get("instance_type") or f"{inp.get('vcpus','?')}vCPU/{inp.get('memory_gib','?')}GiB",
            od_h, od_m, od_a,
            opt_plan, opt_m, opt_a,
            sav_m, sav_a,
        ]

        money_cols = {4, 5, 6, 8, 9, 10, 11}
        for c_idx, val in enumerate(row_data, 1):
            fmt = MONEY_FORMAT if c_idx in money_cols else None
            fill = None
            if c_idx in {10, 11} and sav_m is not None:
                fill = OPT_FILL if sav_m > 0 else WARN_FILL
            _data_cell(ws, r_idx, c_idx, val, fmt=fmt, fill=fill)

        totals["od_monthly"]      += od_m
        totals["od_annual"]       += od_a
        totals["opt_monthly"]     += opt_m
        totals["opt_annual"]      += opt_a
        totals["savings_monthly"] += sav_m if sav_m else 0
        totals["savings_annual"]  += sav_a if sav_a else 0

    # Totals row
    total_row = len(results) + 4
    _data_cell(ws, total_row, 1, "TOTAL", bold=True, fill=SECTION_FILL)
    _data_cell(ws, total_row, 2, "", fill=SECTION_FILL)
    _data_cell(ws, total_row, 3, "", fill=SECTION_FILL)
    _data_cell(ws, total_row, 4, "", fill=SECTION_FILL)
    _data_cell(ws, total_row, 5, round(totals["od_monthly"],  2), fmt=MONEY_FORMAT, bold=True, fill=SECTION_FILL)
    _data_cell(ws, total_row, 6, round(totals["od_annual"],   2), fmt=MONEY_FORMAT, bold=True, fill=SECTION_FILL)
    _data_cell(ws, total_row, 7, "", fill=SECTION_FILL)
    _data_cell(ws, total_row, 8, round(totals["opt_monthly"], 2), fmt=MONEY_FORMAT, bold=True, fill=SECTION_FILL)
    _data_cell(ws, total_row, 9, round(totals["opt_annual"],  2), fmt=MONEY_FORMAT, bold=True, fill=SECTION_FILL)
    _data_cell(ws, total_row, 10, round(totals["savings_monthly"], 2), fmt=MONEY_FORMAT, bold=True, fill=OPT_FILL)
    _data_cell(ws, total_row, 11, round(totals["savings_annual"],  2), fmt=MONEY_FORMAT, bold=True, fill=OPT_FILL)

    widths = [22, 16, 25, 20, 22, 22, 26, 22, 22, 20, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A4"



# ── Sheet 5 : Mapping Details ─────────────────────────────────────────────────

def _write_mapping_details_sheet(wb: Workbook, results: list[dict]):
    """
    Sheet showing all parameters used for comparison and mapping.
    This helps users understand what criteria were used to match instances.
    """
    ws = wb.create_sheet("Mapping Details", 4)
    ws.sheet_view.showGridLines = False

    # Title banner
    ws.merge_cells("A1:S1")
    title_cell = ws["A1"]
    title_cell.value = "Mapping Parameters & Comparison Details"
    title_cell.font  = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    title_cell.fill  = HEADER_FILL
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    cols = [
        "Service Name",
        # Input parameters
        "Service Type", "Current Provider", "Current Instance Type",
        "Input vCPUs", "Input Memory (GiB)", "Input Storage (GB)",
        "Input Region", "Input OS", "Input Tenancy", "Input DB Engine",
        # Mapped AWS parameters
        "AWS Instance Type", "AWS vCPUs", "AWS Memory (GiB)",
        "AWS Region", "AWS OS", "AWS Tenancy", "AWS DB Engine", "AWS Storage Class",
    ]
    _header_row(ws, cols, row=2, fill=SECTION_FILL)
    ws.row_dimensions[2].height = 36

    for r_idx, result in enumerate(results, start=3):
        inp    = result.get("input", {})
        best   = result.get("best_match", {})

        # Get input parameters (from input or from best_match enriched fields)
        input_os = inp.get("operating_system") or best.get("input_operating_system", "")
        input_tenancy = inp.get("tenancy") or best.get("input_tenancy", "")
        input_region = inp.get("region") or best.get("input_region", "")
        input_vcpus = inp.get("vcpus") or best.get("input_vcpus")
        input_memory = inp.get("memory_gib") or best.get("input_memory_gib")
        input_db_engine = inp.get("database_engine") or best.get("input_database_engine", "")

        # Get AWS mapped values from best_match
        aws_os = best.get("operatingsystem", "")
        aws_tenancy = best.get("tenancy", "")
        aws_region = best.get("regioncode") or best.get("region", "")
        aws_db_engine = best.get("databaseengine", "")
        aws_storage_class = best.get("storageclass", "")

        row_data = [
            inp.get("service_name", f"Service-{r_idx-2}"),
            # Input parameters
            inp.get("service_type", ""),
            inp.get("current_provider", ""),
            inp.get("instance_type", ""),
            input_vcpus,
            input_memory,
            inp.get("storage_gb"),
            input_region,
            input_os,
            input_tenancy,
            input_db_engine,
            # Mapped AWS parameters
            best.get("instance_type", "No match"),
            best.get("vcpus") or best.get("vcpu"),
            best.get("memory_gib") or best.get("memory", "").replace(" GiB", ""),
            aws_region,
            aws_os,
            aws_tenancy,
            aws_db_engine,
            aws_storage_class,
        ]

        for c_idx, val in enumerate(row_data, 1):
            _data_cell(ws, r_idx, c_idx, val)

    widths = [18, 12, 14, 20, 12, 16, 16, 20, 18, 14, 18, 20, 12, 16, 20, 18, 14, 18, 18]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A3"
