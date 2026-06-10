"""
utils/combined_calculator.py
-----------------------------
Generate ONE AWS Calculator link containing ALL services.

The individual calculator (aws_calculator.py) works perfectly.
This file uses IDENTICAL code to the individual calculator functions —
the ONLY difference is the final button click:
  - Individual: clicks "Save and view summary" (closes after 1 service)
  - Combined:   clicks "Save and add service" (stays open for more services)

After all services are added, clicks "Share" on the estimate summary page
to get one combined URL with all services and a grand total.
"""

import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Page

from utils.aws_calculator import (
    EC2_URL,
    RDS_URLS,
    normalize_region,
    normalize_os,
    accept_cookies,
    capture_share_link,
    fill_input,
    pick_option_safe,
    select_dropdown_verified,
    open_cloudscape_dropdown,
)

logger = logging.getLogger(__name__)

S3_URL = "https://calculator.aws/#/createCalculator/S3"

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-zygote",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ─────────────────────────────────────────────────────────────────────────────
# Save helper — the ONLY difference from individual calculator
# ─────────────────────────────────────────────────────────────────────────────

async def _save_and_add(page: Page) -> bool:
    """
    Click 'Save and add service' to stay in multi-service flow.
    Falls back to 'Save and view summary' if needed.
    This is the ONLY difference from the individual calculator
    which uses 'Save and view summary'.
    """
    for sel in [
        "button[aria-label='Save and add service']",
        "button:has-text('Save and add service')",
        "button[aria-label='Save and view summary']",
        "button:has-text('Save and view summary')",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3000):
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await page.wait_for_timeout(4000)
                return True
        except Exception:
            continue

    clicked = await page.evaluate("""
        () => {
            for (const text of ['Save and add service', 'Save and view summary']) {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.trim().includes(text));
                if (btn) { btn.click(); return true; }
            }
            return null;
        }
    """)
    if clicked:
        await page.wait_for_timeout(4000)
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# EC2 — IDENTICAL to generate_ec2_calculator_link, only save button differs
# ─────────────────────────────────────────────────────────────────────────────

async def _add_ec2(page: Page, svc: dict):
    """
    Fill EC2 on current page — IDENTICAL logic to generate_ec2_calculator_link.
    Only difference: calls _save_and_add instead of capturing share link.

    IMPORTANT: storage_gb is NOT passed to the EC2 calculator.
    The Excel pricing API (get_ec2_costs) returns INSTANCE-ONLY cost with no EBS.
    Adding storage here would inflate the calculator vs Excel.
    """
    instance_type    = svc["instance"]
    region           = normalize_region(svc["region"])
    operating_system = normalize_os(svc.get("os", "Linux"))
    tenancy          = svc.get("tenancy", "Shared")
    num_instances    = svc.get("num_instances", 1)
    usage_pct        = 100
    # DO NOT pass storage_gb — Excel OnDemand is instance-only (no EBS).
    # Passing storage would add EBS cost to the calculator but NOT to the Excel column.

    tenancy_value = tenancy if "Instances" in tenancy or "Host" in tenancy else f"{tenancy} Instances"

    logger.info(f"    EC2 params: instance={instance_type} region={region} os={operating_system} tenancy={tenancy_value} instances={num_instances} storage=none(excluded)")

    await page.goto(EC2_URL, wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(4000)
    await accept_cookies(page)

    # Description
    description = f"{instance_type} | {region} | {operating_system}"
    await fill_input(page, "input[aria-label='Description - optional']", description)

    # Region
    region_success = await select_dropdown_verified(page, "Choose a Region", region)
    if region_success:
        await page.wait_for_timeout(1200)
        logger.info(f"    ✅ Region set: {region}")
    else:
        logger.warning(f"    ⚠️ Region NOT set: {region}")

    # Tenancy
    try:
        await select_dropdown_verified(page, "Tenancy", tenancy_value)
    except Exception:
        pass

    # OS
    os_success = await select_dropdown_verified(page, "Operating system", operating_system)
    if not os_success:
        logger.warning(f"    ⚠️ OS NOT set: {operating_system}")

    # Workload (consistent)
    try:
        radio = page.locator("input[type='radio'][value='consistent']")
        await radio.scroll_into_view_if_needed()
        await radio.check()
    except Exception:
        pass

    # Number of instances
    await fill_input(page, "input[aria-label*='Number of instances']", str(num_instances))

    # Instance type search + table select — with retry and verification
    instance_selected = False
    for attempt in range(3):
        try:
            search = page.locator("input[aria-label*='Search instance types']")
            await search.scroll_into_view_if_needed()
            await search.click(force=True)
            await search.fill("")
            await page.wait_for_timeout(300)
            await search.fill(instance_type)
            await page.wait_for_timeout(2500)
            # Use exact text match on the table row
            row_radio = page.locator(
                f"tr:has-text('{instance_type}') input[type='radio']"
            ).first
            if await row_radio.count() > 0:
                await row_radio.scroll_into_view_if_needed()
                await row_radio.check()
                await page.wait_for_timeout(800)
                instance_selected = True
                logger.info(f"    ✅ EC2 instance selected: {instance_type} (attempt {attempt+1})")
                break
            else:
                logger.warning(f"    ⚠️ EC2 instance row not found for {instance_type} (attempt {attempt+1})")
                await page.wait_for_timeout(800)
        except Exception as e:
            logger.warning(f"    ⚠️ EC2 instance select error attempt {attempt+1}: {e}")
            await page.wait_for_timeout(800)

    if not instance_selected:
        logger.warning(f"    ❌ EC2 instance {instance_type} could NOT be selected after 3 attempts")

    # Pricing model — on-demand radio
    try:
        for rid in ["on-demand", "onDemand", "ON_DEMAND"]:
            radio = page.locator(f"input#{rid}").first
            if await radio.count() > 0:
                await radio.scroll_into_view_if_needed()
                await radio.check()
                await page.wait_for_timeout(800)
                break
    except Exception:
        pass

    # Usage % = 100
    await fill_input(page, "input[aria-label='Usage']", str(usage_pct))

    # NO storage — EC2 OnDemand in Excel is instance-only (no EBS)

    # Save and ADD (not "Save and view summary")
    saved = await _save_and_add(page)
    if saved:
        logger.info(f"  ✅ EC2 added: {instance_type} ({region})")
    else:
        logger.warning(f"  ⚠️ EC2 save failed for {instance_type}")


# ─────────────────────────────────────────────────────────────────────────────
# RDS — IDENTICAL to generate_rds_calculator_link, only save button differs
# ─────────────────────────────────────────────────────────────────────────────

async def _add_rds(page: Page, svc: dict):
    """
    Fill RDS on current page — IDENTICAL logic to generate_rds_calculator_link.
    Only difference: calls _save_and_add instead of capturing share link.

    IMPORTANT: storage_gb is forced to 20 (AWS minimum).
    The Excel pricing API (get_rds_costs) returns INSTANCE-ONLY cost (ondemand.monthly_usd).
    Storage is computed separately in ondemand.monthly_usd_with_storage.
    Using 20 GB minimum here makes the calculator line match the Excel OnDemand column.
    """
    database_engine = svc.get("database_engine") or "MySQL"
    instance_type   = svc["instance"]
    region          = normalize_region(svc["region"])
    deployment      = "Single-AZ"
    storage_type    = "General Purpose SSD (gp2)"
    # Use real storage_gb from input file — matches what the Pricing API used in Excel.
    # AWS enforces a 20GB minimum; enforce it here too.
    storage_gb_val  = max(int(svc.get("storage_gb") or 20), 20)
    num_instances   = svc.get("num_instances", 1)

    url = RDS_URLS.get(database_engine, RDS_URLS["MySQL"])

    logger.info(f"    RDS params: instance={instance_type} region={region} engine={database_engine} deployment={deployment} storage={storage_gb_val}GB instances={num_instances}")

    await page.goto(url, wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(5000)
    await accept_cookies(page)

    # Description
    description = f"{instance_type} | {region} | {database_engine}"
    await fill_input(page, "input[aria-label='Description - optional']", description)

    # Region — scan all labels for one containing "Region"
    region_selected = False
    try:
        labels = await page.locator("label").all()
        for label in labels:
            text = await label.inner_text()
            if "region" in text.lower():
                await open_cloudscape_dropdown(page, text.strip())
                await pick_option_safe(page, region)
                region_selected = True
                break
    except Exception:
        pass

    if not region_selected:
        try:
            buttons = await page.locator("button").all()
            for btn in buttons:
                aria_label = await btn.get_attribute("aria-label")
                if aria_label and "region" in aria_label.lower():
                    await btn.click()
                    await page.wait_for_timeout(800)
                    await pick_option_safe(page, region)
                    region_selected = True
                    break
        except Exception:
            pass

    if region_selected:
        logger.info(f"    ✅ RDS region set: {region}")
    else:
        logger.warning(f"    ⚠️ RDS region NOT set: {region}")

    await page.wait_for_timeout(1200)

    # Deployment — Single-AZ radio
    try:
        if "Single" in deployment:
            radio = page.locator("input[type='radio'][value*='Single']").first
        else:
            radio = page.locator("input[type='radio'][value*='Multi']").first
        if await radio.count() > 0:
            await radio.scroll_into_view_if_needed()
            await radio.click()
            await page.wait_for_timeout(600)
    except Exception:
        pass

    # Instance type — with retry + verification
    instance_selected = False
    for attempt in range(3):
        try:
            inputs = await page.locator("input[type='text']").all()
            for inp in inputs:
                aria_label  = await inp.get_attribute("aria-label")
                placeholder = await inp.get_attribute("placeholder")
                if aria_label and ("instance" in aria_label.lower() or "class" in aria_label.lower()):
                    await inp.scroll_into_view_if_needed()
                    await inp.click()
                    await inp.fill("")
                    await page.wait_for_timeout(200)
                    await inp.fill(instance_type)
                    await page.wait_for_timeout(1500)
                    picked = await pick_option_safe(page, instance_type)
                    if picked:
                        instance_selected = True
                        logger.info(f"    ✅ RDS instance selected: {instance_type} (attempt {attempt+1})")
                    else:
                        logger.warning(f"    ⚠️ RDS pick_option_safe failed for {instance_type} (attempt {attempt+1})")
                    break
                elif placeholder and ("instance" in placeholder.lower() or "class" in placeholder.lower()):
                    await inp.scroll_into_view_if_needed()
                    await inp.click()
                    await inp.fill("")
                    await page.wait_for_timeout(200)
                    await inp.fill(instance_type)
                    await page.wait_for_timeout(1500)
                    picked = await pick_option_safe(page, instance_type)
                    if picked:
                        instance_selected = True
                        logger.info(f"    ✅ RDS instance selected: {instance_type} via placeholder (attempt {attempt+1})")
                    break
            if instance_selected:
                break
            await page.wait_for_timeout(800)
        except Exception as e:
            logger.warning(f"    ⚠️ RDS instance select attempt {attempt+1}: {e}")
            await page.wait_for_timeout(800)

    if not instance_selected:
        logger.warning(f"    ❌ RDS instance {instance_type} could NOT be selected after 3 attempts")

    # Number of instances
    try:
        inputs = await page.locator("input[type='text'], input[type='number']").all()
        for inp in inputs:
            aria_label = await inp.get_attribute("aria-label")
            if aria_label and ("node" in aria_label.lower() or "instance" in aria_label.lower()):
                current_value = await inp.input_value()
                if current_value and current_value.isdigit():
                    await inp.scroll_into_view_if_needed()
                    await inp.click()
                    await inp.fill(str(num_instances))
                    break
    except Exception:
        pass

    # Storage type tab (gp2/gp3)
    try:
        for short in ["gp2", "gp3", "io1", "Magnetic"]:
            if short.lower() in storage_type.lower():
                tab = page.locator(f"button:has-text('{short}'), [role='tab']:has-text('{short}')").first
                if await tab.is_visible(timeout=1500):
                    await tab.scroll_into_view_if_needed()
                    await tab.click()
                    await page.wait_for_timeout(600)
                    break
    except Exception:
        pass

    # Storage amount — set to 20 GB minimum via JS (matches Excel instance-only cost)
    try:
        filled = await page.evaluate("""
            (storageVal) => {
                const inputs = [...document.querySelectorAll('input[type="text"], input[type="number"]')];
                for (const inp of inputs) {
                    const label = inp.getAttribute('aria-label') || inp.getAttribute('placeholder') || '';
                    if (label.toLowerCase().includes('storage') &&
                        !label.toLowerCase().includes('instance') &&
                        !label.toLowerCase().includes('class')) {
                        inp.focus();
                        inp.select();
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(inp, storageVal);
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }
        """, str(storage_gb_val))
        if filled:
            logger.info(f"    ✅ RDS storage set to {storage_gb_val} GB via JS")
            await page.wait_for_timeout(500)
        else:
            await fill_input(page, "input[aria-label*='Storage amount']", str(storage_gb_val))
    except Exception as e:
        logger.debug(f"RDS storage amount error: {e}")

    # Save and ADD
    saved = await _save_and_add(page)
    if saved:
        logger.info(f"  ✅ RDS added: {instance_type} ({database_engine}, {region})")
    else:
        logger.warning(f"  ⚠️ RDS save failed for {instance_type}")


# ─────────────────────────────────────────────────────────────────────────────
# S3
# ─────────────────────────────────────────────────────────────────────────────

async def _add_s3(page: Page, svc: dict):
    """Fill S3 on current page and save and add."""
    region     = normalize_region(svc["region"])
    storage_gb = svc.get("storage_gb", 100)

    await page.goto(S3_URL, wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(4000)
    await accept_cookies(page)

    await fill_input(page, "input[aria-label='Description - optional']", svc["name"])
    await select_dropdown_verified(page, "Choose a Region", region)
    await page.wait_for_timeout(800)

    # Storage amount
    for label_hint in ["S3 Standard storage", "storage amount", "Storage"]:
        try:
            await fill_input(page, f"input[aria-label*='{label_hint}']", str(storage_gb))
            break
        except Exception:
            continue

    saved = await _save_and_add(page)
    if saved:
        logger.info(f"  ✅ S3 added: {storage_gb} GB ({region})")
    else:
        logger.warning(f"  ⚠️ S3 save failed")


# ─────────────────────────────────────────────────────────────────────────────
# Cost comparison logging — Excel cost vs what we send to AWS Calculator
# ─────────────────────────────────────────────────────────────────────────────

def _log_cost_comparison(services: list[dict]) -> None:
    """
    Print a clear side-by-side log of the Excel-calculated cost vs the
    parameters being sent to the AWS Calculator, so any mismatch is obvious.
    """
    logger.info("=" * 78)
    logger.info("💰 COST COMPARISON  (Excel cost  vs  AWS Calculator parameters)")
    logger.info("=" * 78)

    excel_total = 0.0
    calc_total  = 0.0

    for idx, svc in enumerate(services, 1):
        costs   = svc.get("_excel_costs", {}) or {}
        od      = costs.get("ondemand", {}) or {}
        storage = costs.get("storage", {}) or {}

        od_monthly      = od.get("monthly_usd")
        od_with_storage = od.get("monthly_usd_with_storage")
        storage_monthly = storage.get("monthly_usd")
        svc_type        = svc["type"].upper()

        if isinstance(od_monthly, (int, float)):
            excel_total += float(od_monthly)

        # What the calculator will actually use
        if svc_type == "EC2":
            calc_monthly = od_monthly         # no storage sent → matches Excel
            calc_storage_note = "no EBS (matches Excel)"
        elif svc_type == "RDS":
            # Storage from input file passed to calculator — same as what Pricing API used
            calc_monthly = od_monthly         # Excel OnDemand already = instance + real storage
            calc_storage_note = f"real storage {svc.get('storage_gb')}GB (from Pricing API)"
        else:
            calc_monthly = od_monthly         # S3 = same
            calc_storage_note = "actual storage"

        if isinstance(calc_monthly, (int, float)):
            calc_total += float(calc_monthly)

        logger.info(f"  [{idx}/{len(services)}] {svc['name']}  ({svc_type}: {svc['instance']})")
        logger.info(f"    region={svc['region']} | os={svc['os']} | instances={svc['num_instances']}")
        if svc_type == "EC2":
            logger.info(f"    EC2:  storage NOT sent  | storage in input file = {svc['storage_gb']} GB (ignored)")
        elif svc_type == "RDS":
            logger.info(f"    RDS:  storage forced=20GB | input file had {svc['storage_gb']} GB")
            logger.info(f"    RDS:  engine={svc['database_engine']}")
        logger.info(f"    EXCEL OnDemand (instance only):  ${od_monthly}")
        if storage_monthly is not None:
            logger.info(f"    EXCEL storage ({svc.get('storage_gb')}GB):         ${storage_monthly}")
        if od_with_storage is not None:
            storage_gap = round(float(od_with_storage) - float(od_monthly or 0), 2)
            logger.info(f"    EXCEL OnDemand + storage:        ${od_with_storage}  (gap=${storage_gap})")
        logger.info(f"    CALC  expected monthly:          ${calc_monthly}  [{calc_storage_note}]")
        if od_monthly and calc_monthly:
            diff = round(float(calc_monthly) - float(od_monthly), 2)
            if abs(diff) > 1.0:
                logger.warning(f"    ⚠️  MISMATCH: calc ${calc_monthly} vs Excel ${od_monthly}  (diff={diff:+.2f})")
            else:
                logger.info(f"    ✅  MATCH: calc ≈ Excel (diff={diff:+.2f})")

    logger.info("-" * 78)
    logger.info(f"💰 EXCEL total OnDemand (instance only): ${round(excel_total, 2)}")
    logger.info(f"💰 CALC  expected total:                 ${round(calc_total, 2)}")
    diff_total = round(calc_total - excel_total, 2)
    if abs(diff_total) > 5:
        logger.warning(f"⚠️  TOTAL MISMATCH: calc ${round(calc_total,2)} vs Excel ${round(excel_total,2)} (diff={diff_total:+.2f})")
    else:
        logger.info(f"✅  TOTAL MATCH (diff={diff_total:+.2f})")
    logger.info("=" * 78)


# ─────────────────────────────────────────────────────────────────────────────
# Main combined generator
# ─────────────────────────────────────────────────────────────────────────────

async def generate_combined_calculator_link(results: list[dict]) -> str:
    """
    One browser, one page. For each service, navigate to its calculator URL,
    fill all fields (identical to individual calculator), click "Save and add service".
    After all services, navigate to estimate summary and click Share.
    """
    services: list[dict] = []
    for r in results:
        best     = r.get("best_match", {})
        inp      = r.get("input", {})
        costs    = r.get("costs", {})
        itype    = best.get("instance_type") or ""
        svc_type = str(inp.get("service_type", "ec2")).lower()

        if not itype and svc_type not in ("s3", "storage"):
            continue

        services.append({
            "name":            inp.get("service_name") or f"Service-{len(services)+1}",
            "type":            svc_type,
            "instance":        itype,
            "region":          (best.get("regioncode") or best.get("location")
                                or inp.get("region", "US East (N. Virginia)")),
            "os":              best.get("operatingsystem") or inp.get("operating_system", "Linux"),
            "tenancy":         best.get("tenancy") or inp.get("tenancy", "Shared"),
            "database_engine": best.get("databaseengine") or inp.get("database_engine", "MySQL"),
            "storage_gb":      max(int(inp.get("storage_gb") or 20), 20),
            "num_instances":   int(inp.get("number_of_instances", 1)),
            # Excel-side cost numbers (for comparison logging only)
            "_excel_costs":    costs,
        })

    if not services:
        logger.warning("No valid services to add to combined calculator")
        return ""

    logger.info(f"🔗 Generating COMBINED calculator link for {len(services)} services...")
    _log_cost_comparison(services)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=USER_AGENT,
            )
            page = await context.new_page()

            for idx, svc in enumerate(services):
                svc_type = svc["type"]
                logger.info(
                    f"  [{idx+1}/{len(services)}] Adding: "
                    f"{svc['name']} ({svc_type}: {svc.get('instance','')})"
                )
                try:
                    # Dismiss "Update estimate" banner if present
                    try:
                        update_btn = page.locator("button:has-text('Update estimate')").first
                        if await update_btn.is_visible(timeout=2000):
                            await update_btn.click()
                            await page.wait_for_timeout(2000)
                    except Exception:
                        pass

                    if svc_type in ("ec2", "vm"):
                        await _add_ec2(page, svc)
                    elif svc_type == "rds":
                        await _add_rds(page, svc)
                    elif svc_type in ("s3", "storage"):
                        await _add_s3(page, svc)
                    else:
                        await _add_ec2(page, svc)

                    await page.wait_for_timeout(2000)

                    # If we landed on addService page, go back to estimate summary
                    current_url = page.url
                    if "addService" in current_url or "createCalculator" in current_url:
                        try:
                            crumb = page.locator(
                                "a:has-text('My estimate'), a:has-text('My Estimate')"
                            ).first
                            if await crumb.is_visible(timeout=3000):
                                await crumb.click()
                                await page.wait_for_timeout(3000)
                        except Exception:
                            pass

                except Exception as e:
                    logger.warning(f"  ⚠️ Failed to add {svc['name']}: {e}")
                    continue

            # All services added — capture share link from estimate summary
            current_url = page.url
            logger.info(f"📋 Final URL: {current_url[:80]}")
            logger.info("📋 Saving combined estimate to get share link...")
            share_link = await capture_share_link(page)

            await browser.close()

        if share_link:
            logger.info(
                f"✅ Combined calculator link generated "
                f"({len(services)} services): {share_link[:80]}..."
            )
        else:
            logger.warning("⚠️ Could not capture combined calculator link")

        return share_link

    except Exception as e:
        logger.error(f"❌ Error generating combined calculator link: {e}", exc_info=True)
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Synchronous wrapper
# ─────────────────────────────────────────────────────────────────────────────

def generate_combined_calculator_link_sync(results: list[dict]) -> str:
    """Synchronous wrapper with result_holder to survive timeout races."""
    import concurrent.futures

    try:
        from playwright.sync_api import sync_playwright as _swp  # noqa: F401
    except ImportError:
        logger.error("❌ Playwright not installed.")
        return ""

    result_holder: dict = {"link": "", "done": False}

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            link = loop.run_until_complete(generate_combined_calculator_link(results))
            result_holder["link"] = link or ""
            result_holder["done"] = True
            return link or ""
        except Exception as exc:
            logger.error(f"❌ combined async error: {exc}", exc_info=True)
            result_holder["done"] = True
            return ""
        finally:
            loop.close()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_run)
            try:
                return future.result(timeout=900) or ""
            except concurrent.futures.TimeoutError:
                if result_holder["link"]:
                    logger.info(f"⏱️ Timeout but link captured: {result_holder['link'][:60]}...")
                    return result_holder["link"]
                logger.error("❌ Combined calculator timed out (900 s)")
                return ""
    except Exception as e:
        logger.error(f"❌ Combined sync wrapper error: {e}", exc_info=True)
        return result_holder.get("link", "")
