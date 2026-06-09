"""
utils/combined_calculator.py
-----------------------------
Generate ONE AWS Calculator link that contains ALL services.

Strategy:
  1. Open calculator.aws in a headless browser
  2. For each service, click "Add service", fill details, click "Save and add service"
  3. After all services are added, click "Share" → capture the single combined estimate URL

The resulting URL looks like:
  https://calculator.aws/#/estimate?id=<uuid>

When opened, it shows ALL services in a single estimate with a grand-total monthly cost.
"""

import asyncio
import logging
import re
from typing import Optional
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from utils.aws_calculator import (
    normalize_region,
    normalize_os,
    accept_cookies,
    capture_share_link,
    fill_input,
    pick_option_safe,
    select_dropdown_verified,
)

logger = logging.getLogger(__name__)

CALCULATOR_HOME = "https://calculator.aws/#/"
ADD_SERVICE_URL = "https://calculator.aws/#/addService"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _click_add_service(page: Page):
    """Click 'Add service' or 'Create estimate' to reach service picker."""
    for selector in [
        "button:has-text('Add service')",
        "button[data-testid='add-service-button']",
        "a:has-text('Add service')",
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            continue
    return False


async def _select_service_card(page: Page, service_name: str) -> bool:
    """Search for and select a service card using the search box first, then click."""
    # Step 1: Type in the search box to filter results
    try:
        search = page.locator(
            "input[placeholder*='search' i], "
            "input[aria-label*='search' i], "
            "input[aria-label='Find Service'], "
            "input[placeholder*='Find' i]"
        ).first
        if await search.is_visible(timeout=3000):
            await search.clear()
            await search.fill(service_name)
            await page.wait_for_timeout(1500)
    except Exception:
        pass

    # Step 2: After filtering, click the first visible result card
    # Use :has-text which checks if text is contained anywhere in the element
    for selector in [
        f"button:has-text('{service_name}')",
        f"li:has-text('{service_name}') button",
        f"[role='option']:has-text('{service_name}')",
        f"a:has-text('{service_name}')",
        f"div[class*='card']:has-text('{service_name}')",
        f"li[class*='service']:has-text('{service_name}')",
    ]:
        try:
            card = page.locator(selector).first
            if await card.is_visible(timeout=2000):
                await card.click()
                await page.wait_for_timeout(2500)
                return True
        except Exception:
            continue

    # Step 3: JS fallback — find first visible element containing the service name
    clicked = await page.evaluate("""
        (serviceName) => {
            // After search box filtering, find any visible element with the service name
            const all = [...document.querySelectorAll('button, li, a, [role="option"]')];
            for (const el of all) {
                if (el.offsetParent !== null && el.textContent.includes(serviceName)) {
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """, service_name)
    if clicked:
        await page.wait_for_timeout(2500)
        return True

    return False


async def _save_and_add(page: Page) -> bool:
    """Click 'Save and add service' or 'Save and view summary'."""
    for selector in [
        "button[aria-label='Save and add service']",
        "button:has-text('Save and add service')",
        "button[aria-label='Save and view summary']",
        "button:has-text('Save and view summary')",
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                await page.wait_for_timeout(3000)
                return True
        except Exception:
            continue

    # JS fallback
    clicked = await page.evaluate("""
        () => {
            const targets = ['Save and add service', 'Save and view summary'];
            for (const text of targets) {
                const btn = [...document.querySelectorAll('button')]
                    .find(b => b.textContent.trim().includes(text));
                if (btn) { btn.click(); return true; }
            }
            return false;
        }
    """)
    await page.wait_for_timeout(3000)
    return bool(clicked)


# ─────────────────────────────────────────────────────────────────────────────
# Per-service adders
# ─────────────────────────────────────────────────────────────────────────────

async def _add_ec2(page: Page, svc: dict, is_last: bool):
    """Add an EC2 service to the open estimate."""
    await _click_add_service(page)
    if not await _select_service_card(page, "Amazon EC2"):
        logger.warning(f"  ⚠️ Could not select EC2 card for {svc['name']}")
        return

    region    = normalize_region(svc["region"])
    os_name   = normalize_os(svc["os"])
    instance  = svc["instance"]
    num       = str(svc.get("num_instances", 1))

    # Description
    try:
        await fill_input(page, "input[aria-label='Description - optional']", svc["name"])
    except Exception:
        pass

    # Region
    await select_dropdown_verified(page, "Choose a Region", region)
    await page.wait_for_timeout(800)

    # OS
    await select_dropdown_verified(page, "Operating system", os_name)

    # Tenancy
    tenancy_raw = svc.get("tenancy", "Shared")
    tenancy_val = tenancy_raw if "Instances" in tenancy_raw else f"{tenancy_raw} Instances"
    try:
        await select_dropdown_verified(page, "Tenancy", tenancy_val)
    except Exception:
        pass

    # Workload — consistent usage
    try:
        radio = page.locator("input[type='radio'][value='consistent']").first
        if await radio.count() > 0:
            await radio.check()
    except Exception:
        pass

    # Number of instances
    try:
        await fill_input(page, "input[aria-label*='Number of instances']", num)
    except Exception:
        pass

    # Instance type search + select
    try:
        search = page.locator("input[aria-label*='Search instance types']").first
        await search.scroll_into_view_if_needed()
        await search.click(force=True)
        await search.fill(instance)
        await page.wait_for_timeout(2000)

        row_radio = page.locator(
            f"tr:has-text('{instance}') input[type='radio']"
        ).first
        if await row_radio.count() > 0:
            await row_radio.scroll_into_view_if_needed()
            await row_radio.check()
            await page.wait_for_timeout(600)
    except Exception as e:
        logger.debug(f"Instance type select error: {e}")

    await _save_and_add(page)
    logger.info(f"  ✅ EC2 added: {instance} ({region})")


async def _add_rds(page: Page, svc: dict, is_last: bool):
    """Add an RDS service to the open estimate."""
    engine = svc.get("database_engine", "MySQL")

    # Map engine to calculator service name
    engine_map = {
        "MySQL":      "Amazon RDS for MySQL",
        "PostgreSQL": "Amazon RDS for PostgreSQL",
        "MariaDB":    "Amazon RDS for MariaDB",
        "SQL Server": "Amazon RDS for SQL Server",
        "Oracle":     "Amazon RDS for Oracle",
        "Aurora MySQL":     "Amazon Aurora MySQL-Compatible",
        "Aurora PostgreSQL":"Amazon Aurora PostgreSQL-Compatible",
    }
    service_name = engine_map.get(engine, "Amazon RDS for MySQL")

    await _click_add_service(page)
    if not await _select_service_card(page, service_name):
        # Fallback: search just "RDS"
        await _click_add_service(page)
        await _select_service_card(page, "Amazon RDS")

    region   = normalize_region(svc["region"])
    instance = svc["instance"]

    try:
        await fill_input(page, "input[aria-label='Description - optional']", svc["name"])
    except Exception:
        pass

    # Region
    await select_dropdown_verified(page, "Choose a Region", region)
    await page.wait_for_timeout(800)

    # Instance class search
    try:
        inputs = await page.locator("input[type='text'], input[type='search']").all()
        for inp in inputs:
            aria = await inp.get_attribute("aria-label") or ""
            ph   = await inp.get_attribute("placeholder") or ""
            if "instance" in aria.lower() or "class" in aria.lower() or "instance" in ph.lower():
                await inp.scroll_into_view_if_needed()
                await inp.click()
                await inp.fill(instance)
                await page.wait_for_timeout(1500)
                await pick_option_safe(page, instance)
                break
    except Exception as e:
        logger.debug(f"RDS instance class error: {e}")

    await _save_and_add(page)
    logger.info(f"  ✅ RDS added: {instance} ({engine}, {region})")


async def _add_s3(page: Page, svc: dict, is_last: bool):
    """Add an S3 service to the open estimate."""
    await _click_add_service(page)
    if not await _select_service_card(page, "Amazon S3"):
        logger.warning(f"  ⚠️ Could not select S3 card for {svc['name']}")
        return

    region  = normalize_region(svc["region"])
    storage = svc.get("storage_gb", 100)

    try:
        await fill_input(page, "input[aria-label='Description - optional']", svc["name"])
    except Exception:
        pass

    # Region
    await select_dropdown_verified(page, "Choose a Region", region)
    await page.wait_for_timeout(800)

    # Storage amount
    try:
        await fill_input(page, "input[aria-label*='S3 Standard storage']", str(storage))
    except Exception:
        try:
            await fill_input(page, "input[aria-label*='storage amount']", str(storage))
        except Exception:
            pass

    await _save_and_add(page)
    logger.info(f"  ✅ S3 added: {storage} GB ({region})")


async def _add_lambda(page: Page, svc: dict, is_last: bool):
    """Add a Lambda service to the open estimate."""
    await _click_add_service(page)
    if not await _select_service_card(page, "AWS Lambda"):
        logger.warning(f"  ⚠️ Could not select Lambda card for {svc['name']}")
        return

    try:
        await fill_input(page, "input[aria-label='Description - optional']", svc["name"])
    except Exception:
        pass

    region = normalize_region(svc["region"])
    await select_dropdown_verified(page, "Choose a Region", region)

    await _save_and_add(page)
    logger.info(f"  ✅ Lambda added ({region})")


# ─────────────────────────────────────────────────────────────────────────────
# Main combined generator
# ─────────────────────────────────────────────────────────────────────────────

async def generate_combined_calculator_link(
    results: list[dict],
    headless: bool = True,
) -> str:
    """
    Open AWS Calculator once, add every service, then save the estimate and
    return the single shareable link that contains ALL services.

    Args:
        results:  Full pipeline results list (one entry per service row)
        headless: Run Chromium headless (set False only for local debugging)

    Returns:
        A URL like https://calculator.aws/#/estimate?id=<uuid>
        or "" if something went wrong.
    """
    # Build a clean list of services to add
    services: list[dict] = []
    for r in results:
        best = r.get("best_match", {})
        inp  = r.get("input", {})
        itype = best.get("instance_type") or ""

        svc_type = str(inp.get("service_type", "ec2")).lower()

        # S3 doesn't have a real instance_type — still include it
        if not itype and svc_type not in ("s3", "storage", "lambda", "vpc"):
            continue

        services.append({
            "name":            inp.get("service_name") or inp.get("instance_type") or f"Service-{len(services)+1}",
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
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                    "--no-zygote",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-sync",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            # ── 1. Open calculator home ──────────────────────────────────────
            logger.info("🌐 Opening AWS Calculator home page...")
            await page.goto(CALCULATOR_HOME, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(3000)
            await accept_cookies(page)
            logger.info("✅ Calculator home loaded")

            # Click "Create estimate" on the landing page if present
            for sel in [
                "a:has-text('Create estimate')",
                "button:has-text('Create estimate')",
                "a:has-text('Get started')",
            ]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        await page.wait_for_timeout(2000)
                        logger.info(f"✅ Clicked '{sel}'")
                        break
                except Exception:
                    pass

            # ── 2. Add each service ──────────────────────────────────────────
            for idx, svc in enumerate(services):
                is_last = idx == len(services) - 1
                svc_type = svc["type"]
                logger.info(f"  [{idx+1}/{len(services)}] Adding: {svc['name']} ({svc_type}: {svc.get('instance','')})")

                try:
                    if svc_type in ("ec2", "vm"):
                        await _add_ec2(page, svc, is_last)
                    elif svc_type == "rds":
                        await _add_rds(page, svc, is_last)
                    elif svc_type in ("s3", "storage"):
                        await _add_s3(page, svc, is_last)
                    elif svc_type in ("lambda", "function"):
                        await _add_lambda(page, svc, is_last)
                    else:
                        # Default: treat as EC2
                        await _add_ec2(page, svc, is_last)
                except Exception as e:
                    logger.warning(f"  ⚠️ Failed to add {svc['name']}: {e}")
                    # Try to get back to the estimate page and continue
                    try:
                        await page.go_back(wait_until="domcontentloaded", timeout=10000)
                        await page.wait_for_timeout(1500)
                    except Exception:
                        pass
                    continue

            # ── 3. We are now on the "My estimate" summary page ──────────────
            # Make sure we're on the estimate summary, not still on a service page
            try:
                my_estimate = page.locator("a:has-text('My estimate'), button:has-text('My estimate')").first
                if await my_estimate.is_visible(timeout=3000):
                    await my_estimate.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

            # ── 4. Capture the combined share link ───────────────────────────
            logger.info("📋 Saving combined estimate to get shareable link...")
            share_link = await capture_share_link(page)

            await browser.close()

        if share_link:
            logger.info(f"✅ Combined calculator link generated ({len(services)} services): {share_link[:80]}...")
        else:
            logger.warning("⚠️ Could not capture combined calculator link")

        return share_link

    except Exception as e:
        logger.error(f"❌ Error generating combined calculator link: {e}", exc_info=True)
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Synchronous wrapper (called from orchestrator.py which may have a running loop)
# ─────────────────────────────────────────────────────────────────────────────

def generate_combined_calculator_link_sync(results: list[dict]) -> str:
    """
    Synchronous entry point.  Runs the async generator in a dedicated thread
    so it works whether or not an event loop is already running (FastAPI context).
    """
    import concurrent.futures

    # ── Pre-flight: verify Playwright + Chromium are available ───────────────
    try:
        from playwright.sync_api import sync_playwright as _swp  # noqa: F401
    except ImportError:
        logger.error("❌ Playwright is not installed. Run: pip install playwright && playwright install chromium")
        return ""

    def _run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(generate_combined_calculator_link(results))
        except Exception as exc:
            logger.error(f"❌ combined_calculator async error: {exc}", exc_info=True)
            return ""
        finally:
            loop.close()

    try:
        # Always run in a fresh thread to avoid event-loop conflicts
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_run_in_thread)
            return future.result(timeout=600)   # 10-minute hard timeout
    except concurrent.futures.TimeoutError:
        logger.error("❌ Combined calculator link generation timed out (600 s)")
        return ""
    except Exception as e:
        logger.error(f"❌ Combined calculator sync wrapper error: {e}", exc_info=True)
        return ""
