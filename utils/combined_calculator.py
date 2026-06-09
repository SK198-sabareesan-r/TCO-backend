"""
utils/combined_calculator.py
-----------------------------
Generate ONE AWS Calculator link that contains ALL services.

Strategy (based on the proven individual calculator approach):
- For EC2: go to /createCalculator/ec2-enhancement, fill all fields,
  click "Save and add service" (stays in multi-service flow)
- For RDS: go to /createCalculator/RDS{Engine}, fill all fields,
  click "Save and add service"
- For S3: go to /createCalculator/S3, fill fields, "Save and add service"
- After all services: from the "My estimate" summary page, click Share
  to get ONE combined estimate URL with all services.
"""

import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Page

from utils.aws_calculator import (
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

# Same URLs as the working individual calculator
EC2_URL  = "https://calculator.aws/#/createCalculator/ec2-enhancement"
RDS_URLS = {
    "MySQL":      "https://calculator.aws/#/createCalculator/RDSMySQL",
    "PostgreSQL": "https://calculator.aws/#/createCalculator/RDSPostgreSQL",
    "MariaDB":    "https://calculator.aws/#/createCalculator/RDSMariaDB",
    "SQL Server": "https://calculator.aws/#/createCalculator/RDSSQLServer",
    "Oracle":     "https://calculator.aws/#/createCalculator/RDSOracle",
}
S3_URL     = "https://calculator.aws/#/createCalculator/S3"
LAMBDA_URL = "https://calculator.aws/#/createCalculator/Lambda"

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
# Save-and-add helper  (stays in multi-service flow)
# ─────────────────────────────────────────────────────────────────────────────

async def _save_and_add_service(page: Page) -> bool:
    """
    Click 'Save and add service' to stay in the multi-service estimate flow.
    Falls back to 'Save and view summary' if needed.
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
                await page.wait_for_timeout(3000)
                logger.debug(f"✅ Clicked: {sel}")
                return True
        except Exception:
            continue

    # JS fallback
    clicked = await page.evaluate("""
        () => {
            for (const text of ['Save and add service', 'Save and view summary']) {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.trim().includes(text));
                if (btn) { btn.click(); return text; }
            }
            return null;
        }
    """)
    if clicked:
        await page.wait_for_timeout(3000)
        logger.debug(f"✅ JS clicked: {clicked}")
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# EC2  (exact copy of proven individual logic, but clicks "Save and add")
# ─────────────────────────────────────────────────────────────────────────────

async def _add_ec2(page: Page, context, svc: dict):
    """Add an EC2 service — uses the proven individual EC2 calculator approach."""
    instance = svc["instance"]
    region   = normalize_region(svc["region"])
    os_name  = normalize_os(svc.get("os", "Linux"))
    tenancy  = svc.get("tenancy", "Shared")
    tenancy_val = tenancy if "Instances" in tenancy or "Host" in tenancy else f"{tenancy} Instances"
    num      = str(svc.get("num_instances", 1))

    logger.info(f"    → Loading EC2 calculator page for {instance}...")
    page2 = await context.new_page()
    try:
        await page2.goto(EC2_URL, wait_until="networkidle", timeout=45000)
        await page2.wait_for_timeout(4000)
        await accept_cookies(page2)

        # Description
        await fill_input(page2, "input[aria-label='Description - optional']", svc["name"])

        # Region
        await select_dropdown_verified(page2, "Choose a Region", region)
        await page2.wait_for_timeout(1200)

        # Tenancy
        try:
            await select_dropdown_verified(page2, "Tenancy", tenancy_val)
        except Exception:
            pass

        # OS
        await select_dropdown_verified(page2, "Operating system", os_name)

        # Workload — consistent
        try:
            radio = page2.locator("input[type='radio'][value='consistent']")
            await radio.scroll_into_view_if_needed()
            await radio.check()
        except Exception:
            pass

        # Number of instances
        await fill_input(page2, "input[aria-label*='Number of instances']", num)

        # Instance type search + table select
        try:
            search = page2.locator("input[aria-label*='Search instance types']")
            await search.scroll_into_view_if_needed()
            await search.click(force=True)
            await search.fill(instance)
            await page2.wait_for_timeout(2500)
            row_radio = page2.locator(f"tr:has-text('{instance}') input[type='radio']").first
            if await row_radio.count() > 0:
                await row_radio.scroll_into_view_if_needed()
                await row_radio.check()
                await page2.wait_for_timeout(600)
        except Exception as e:
            logger.debug(f"EC2 instance select error: {e}")

        # Save and add service
        saved = await _save_and_add_service(page2)
        if saved:
            logger.info(f"  ✅ EC2 added: {instance} ({region})")
        else:
            logger.warning(f"  ⚠️ EC2 save failed for {instance}")

    finally:
        await page2.close()


# ─────────────────────────────────────────────────────────────────────────────
# RDS  (exact copy of proven individual logic, but clicks "Save and add")
# ─────────────────────────────────────────────────────────────────────────────

async def _add_rds(page: Page, context, svc: dict):
    """Add an RDS service — uses the proven individual RDS calculator approach."""
    engine   = svc.get("database_engine") or "MySQL"
    instance = svc["instance"]
    region   = normalize_region(svc["region"])
    url      = RDS_URLS.get(engine, RDS_URLS["MySQL"])

    logger.info(f"    → Loading RDS calculator page for {instance} ({engine})...")
    page2 = await context.new_page()
    try:
        await page2.goto(url, wait_until="networkidle", timeout=45000)
        await page2.wait_for_timeout(5000)
        await accept_cookies(page2)

        # Description
        await fill_input(page2, "input[aria-label='Description - optional']", svc["name"])

        # Region — same approach as proven individual code
        region_selected = False
        try:
            labels = await page2.locator("label").all()
            for label in labels:
                text = await label.inner_text()
                if "region" in text.lower():
                    await open_cloudscape_dropdown(page2, text.strip())
                    await pick_option_safe(page2, region)
                    region_selected = True
                    break
        except Exception:
            pass

        if not region_selected:
            try:
                buttons = await page2.locator("button").all()
                for btn in buttons:
                    aria = await btn.get_attribute("aria-label") or ""
                    if "region" in aria.lower():
                        await btn.click()
                        await page2.wait_for_timeout(800)
                        await pick_option_safe(page2, region)
                        break
            except Exception:
                pass

        await page2.wait_for_timeout(1200)

        # Deployment — Single-AZ radio
        try:
            radio = page2.locator("input[type='radio'][value*='Single']").first
            if await radio.count() > 0:
                await radio.scroll_into_view_if_needed()
                await radio.click()
                await page2.wait_for_timeout(600)
        except Exception:
            pass

        # Instance class — same as proven individual: find text input with "instance" in label
        try:
            inputs = await page2.locator("input[type='text']").all()
            for inp in inputs:
                aria = await inp.get_attribute("aria-label") or ""
                ph   = await inp.get_attribute("placeholder") or ""
                if "instance" in aria.lower() or "class" in aria.lower():
                    await inp.scroll_into_view_if_needed()
                    await inp.click()
                    await inp.fill(instance)
                    await page2.wait_for_timeout(1500)
                    await pick_option_safe(page2, instance)
                    break
        except Exception as e:
            logger.debug(f"RDS instance input error: {e}")

        # Save and add service
        saved = await _save_and_add_service(page2)
        if saved:
            logger.info(f"  ✅ RDS added: {instance} ({engine}, {region})")
        else:
            logger.warning(f"  ⚠️ RDS save failed for {instance}")

    finally:
        await page2.close()


# ─────────────────────────────────────────────────────────────────────────────
# S3
# ─────────────────────────────────────────────────────────────────────────────

async def _add_s3(page: Page, context, svc: dict):
    """Add S3 storage to the estimate."""
    region  = normalize_region(svc["region"])
    storage = svc.get("storage_gb", 100)

    logger.info(f"    → Loading S3 calculator page ({storage} GB)...")
    page2 = await context.new_page()
    try:
        await page2.goto(S3_URL, wait_until="networkidle", timeout=45000)
        await page2.wait_for_timeout(4000)
        await accept_cookies(page2)

        await fill_input(page2, "input[aria-label='Description - optional']", svc["name"])

        # Region
        await select_dropdown_verified(page2, "Choose a Region", region)
        await page2.wait_for_timeout(800)

        # Storage amount
        for label_hint in ["S3 Standard storage", "storage amount", "Storage"]:
            try:
                await fill_input(page2, f"input[aria-label*='{label_hint}']", str(storage))
                break
            except Exception:
                continue

        saved = await _save_and_add_service(page2)
        if saved:
            logger.info(f"  ✅ S3 added: {storage} GB ({region})")
        else:
            logger.warning(f"  ⚠️ S3 save failed")

    finally:
        await page2.close()


# ─────────────────────────────────────────────────────────────────────────────
# Main combined generator
# ─────────────────────────────────────────────────────────────────────────────

async def generate_combined_calculator_link(results: list[dict]) -> str:
    """
    Open ONE browser context, add every service using the proven individual
    calculator URLs, then share the combined estimate.

    Each service opens a new page tab within the same browser context
    (so all services go into the same estimate), fills in its details using
    the exact same logic as the working individual calculator, clicks
    "Save and add service", then closes that tab.

    After all services: navigate to the estimate summary, click Share,
    capture and return the single combined estimate URL.
    """
    # Build the service list
    services: list[dict] = []
    for r in results:
        best     = r.get("best_match", {})
        inp      = r.get("input", {})
        itype    = best.get("instance_type") or ""
        svc_type = str(inp.get("service_type", "ec2")).lower()

        if not itype and svc_type not in ("s3", "storage", "lambda"):
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
            "storage_gb":      inp.get("storage_gb", 100),
            "num_instances":   int(inp.get("number_of_instances", 1)),
        })

    if not services:
        logger.warning("No valid services to add to combined calculator")
        return ""

    logger.info(f"🔗 Generating COMBINED calculator link for {len(services)} services...")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=USER_AGENT,
            )

            # Open a placeholder page — we need at least one page in context
            base_page = await context.new_page()
            await base_page.goto("about:blank")

            for idx, svc in enumerate(services):
                svc_type = svc["type"]
                logger.info(
                    f"  [{idx+1}/{len(services)}] Adding: "
                    f"{svc['name']} ({svc_type}: {svc.get('instance','')})"
                )
                try:
                    if svc_type in ("ec2", "vm"):
                        await _add_ec2(base_page, context, svc)
                    elif svc_type == "rds":
                        await _add_rds(base_page, context, svc)
                    elif svc_type in ("s3", "storage"):
                        await _add_s3(base_page, context, svc)
                    else:
                        await _add_ec2(base_page, context, svc)
                except Exception as e:
                    logger.warning(f"  ⚠️ Failed to add {svc['name']}: {e}")
                    continue

            # All services added — now navigate to My Estimate and share
            logger.info("📋 Navigating to estimate summary to get combined link...")
            await base_page.goto(
                "https://calculator.aws/#/estimate",
                wait_until="networkidle",
                timeout=30000,
            )
            await base_page.wait_for_timeout(3000)

            logger.info("📋 Saving combined estimate...")
            share_link = await capture_share_link(base_page)

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
    """
    Synchronous entry point. Runs the async generator in a dedicated thread.
    Uses a result_holder dict to survive ThreadPoolExecutor timeout races.
    """
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
