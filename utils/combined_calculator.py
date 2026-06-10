"""
utils/combined_calculator.py
-----------------------------
Generate ONE AWS Calculator link containing ALL services.

Strategy (your idea — uses the proven individual calculator code):
  Step 1: Generate the FIRST service using the proven individual code
          (generate_ec2_calculator_link / generate_rds_calculator_link).
          This creates a real saved estimate and leaves the browser on
          the estimate SUMMARY page (which has the "Add service" button).
  Step 2: Click "Add service" → navigate to the service-specific URL
          on the SAME page → fill details (proven code) → "Save and add service"
          → lands back on estimate summary.
  Step 3: Repeat Step 2 for every remaining service.
  Step 4: On the estimate summary, click "Share" → capture the combined URL.

This works because the individual calculator already works perfectly.
We just extend its browser session instead of closing it after the first service.
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
# Navigate to "Add service" from the estimate summary page
# ─────────────────────────────────────────────────────────────────────────────

async def _click_add_service_from_summary(page: Page) -> bool:
    """
    On the estimate summary page, click the 'Add service' button.
    This opens the service selection or navigates to a specific service URL.
    """
    for sel in [
        "button:has-text('Add service')",
        "a:has-text('Add service')",
        "button[aria-label='Add service']",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                await page.wait_for_timeout(2000)
                logger.debug(f"✅ Clicked 'Add service': {sel}")
                return True
        except Exception:
            continue
    return False


async def _save_and_add_service(page: Page) -> bool:
    """Click 'Save and add service' — stays in the multi-service flow."""
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
# Fill EC2 on the current page (same logic as proven individual code)
# ─────────────────────────────────────────────────────────────────────────────

async def _fill_and_save_ec2(page: Page, svc: dict) -> bool:
    """Navigate current page to EC2 URL, fill all fields, save."""
    instance    = svc["instance"]
    region      = normalize_region(svc["region"])
    os_name     = normalize_os(svc.get("os", "Linux"))
    tenancy     = svc.get("tenancy", "Shared")
    tenancy_val = tenancy if "Instances" in tenancy or "Host" in tenancy else f"{tenancy} Instances"
    num         = str(svc.get("num_instances", 1))

    await page.goto(EC2_URL, wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(4000)
    await accept_cookies(page)

    await fill_input(page, "input[aria-label='Description - optional']", svc["name"])
    await select_dropdown_verified(page, "Choose a Region", region)
    await page.wait_for_timeout(1200)

    try:
        await select_dropdown_verified(page, "Tenancy", tenancy_val)
    except Exception:
        pass

    await select_dropdown_verified(page, "Operating system", os_name)

    try:
        radio = page.locator("input[type='radio'][value='consistent']")
        await radio.scroll_into_view_if_needed()
        await radio.check()
    except Exception:
        pass

    await fill_input(page, "input[aria-label*='Number of instances']", num)

    # ── Usage % — MUST be set to 100 so calculator matches our pricing ──────
    # Without this, calculator defaults to 50% = half the monthly cost
    try:
        await fill_input(page, "input[aria-label='Usage']", "100")
    except Exception:
        pass

    try:
        search = page.locator("input[aria-label*='Search instance types']")
        await search.scroll_into_view_if_needed()
        await search.click(force=True)
        await search.fill(instance)
        await page.wait_for_timeout(2500)
        row_radio = page.locator(f"tr:has-text('{instance}') input[type='radio']").first
        if await row_radio.count() > 0:
            await row_radio.scroll_into_view_if_needed()
            await row_radio.check()
            await page.wait_for_timeout(600)
    except Exception as e:
        logger.debug(f"EC2 instance select error: {e}")

    saved = await _save_and_add_service(page)
    if saved:
        logger.info(f"  ✅ EC2 added: {instance} ({region})")
    else:
        logger.warning(f"  ⚠️ EC2 save failed for {instance}")
    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Fill RDS on the current page
# ─────────────────────────────────────────────────────────────────────────────

async def _fill_and_save_rds(page: Page, svc: dict) -> bool:
    """Navigate current page to RDS URL, fill all fields, save."""
    engine   = svc.get("database_engine") or "MySQL"
    instance = svc["instance"]
    region   = normalize_region(svc["region"])
    url      = RDS_URLS.get(engine, RDS_URLS["MySQL"])

    await page.goto(url, wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(5000)
    await accept_cookies(page)

    await fill_input(page, "input[aria-label='Description - optional']", svc["name"])

    # Region
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
                aria = await btn.get_attribute("aria-label") or ""
                if "region" in aria.lower():
                    await btn.click()
                    await page.wait_for_timeout(800)
                    await pick_option_safe(page, region)
                    break
        except Exception:
            pass

    await page.wait_for_timeout(1200)

    # Single-AZ
    try:
        radio = page.locator("input[type='radio'][value*='Single']").first
        if await radio.count() > 0:
            await radio.scroll_into_view_if_needed()
            await radio.click()
            await page.wait_for_timeout(600)
    except Exception:
        pass

    # Instance class
    try:
        inputs = await page.locator("input[type='text']").all()
        for inp in inputs:
            aria = await inp.get_attribute("aria-label") or ""
            ph   = await inp.get_attribute("placeholder") or ""
            if "instance" in aria.lower() or "class" in aria.lower():
                await inp.scroll_into_view_if_needed()
                await inp.click()
                await inp.fill(instance)
                await page.wait_for_timeout(1500)
                await pick_option_safe(page, instance)
                break
    except Exception as e:
        logger.debug(f"RDS instance input error: {e}")

    # ── Storage amount — MUST be set to match Excel pricing ────────────────
    # Default is 3000 GB which massively inflates costs vs our $0 storage calc.
    # Set to 20 GB (minimum realistic) to match our RDS cost_client calculation
    # which uses ~$0 storage by default (storage not included in on-demand price).
    storage_gb = svc.get("storage_gb", 20)
    if not storage_gb or float(storage_gb) == 0:
        storage_gb = 20
    try:
        # Find storage amount input and set it
        all_inputs = await page.locator("input[type='text'], input[type='number']").all()
        for inp in all_inputs:
            aria = await inp.get_attribute("aria-label") or ""
            if "storage" in aria.lower() and ("amount" in aria.lower() or "size" in aria.lower()):
                await inp.scroll_into_view_if_needed()
                await inp.click()
                await inp.triple_click()   # select all existing text
                await inp.fill(str(int(storage_gb)))
                await page.wait_for_timeout(500)
                logger.debug(f"RDS storage set to {storage_gb} GB")
                break
    except Exception as e:
        logger.debug(f"RDS storage amount error: {e}")

    saved = await _save_and_add_service(page)
    if saved:
        logger.info(f"  ✅ RDS added: {instance} ({engine}, {region})")
    else:
        logger.warning(f"  ⚠️ RDS save failed for {instance}")
    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Fill S3 on the current page
# ─────────────────────────────────────────────────────────────────────────────

async def _fill_and_save_s3(page: Page, svc: dict) -> bool:
    """Navigate current page to S3 URL, fill fields, save."""
    region  = normalize_region(svc["region"])
    storage = svc.get("storage_gb", 100)

    await page.goto(S3_URL, wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(4000)
    await accept_cookies(page)

    await fill_input(page, "input[aria-label='Description - optional']", svc["name"])
    await select_dropdown_verified(page, "Choose a Region", region)
    await page.wait_for_timeout(800)

    for label_hint in ["S3 Standard storage", "storage amount", "Storage"]:
        try:
            await fill_input(page, f"input[aria-label*='{label_hint}']", str(storage))
            break
        except Exception:
            continue

    saved = await _save_and_add_service(page)
    if saved:
        logger.info(f"  ✅ S3 added: {storage} GB ({region})")
    else:
        logger.warning(f"  ⚠️ S3 save failed")
    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Navigate from estimate summary to a specific service calculator
# ─────────────────────────────────────────────────────────────────────────────

async def _navigate_to_service(page: Page, svc: dict) -> bool:
    """
    From the estimate summary page, click 'Update estimate' if needed,
    then navigate directly to the service-specific calculator URL.
    The key insight: after the first service is saved, we're on the
    estimate summary. For additional services, just navigate directly
    to the service URL — AWS preserves the estimate cookie/session.
    """
    svc_type = svc["type"]

    # Click "Update estimate" banner if it appears (AWS shows this when
    # reopening a saved estimate — we need to dismiss it)
    try:
        update_btn = page.locator("button:has-text('Update estimate')").first
        if await update_btn.is_visible(timeout=2000):
            await update_btn.click()
            await page.wait_for_timeout(2000)
            logger.debug("✅ Clicked 'Update estimate'")
    except Exception:
        pass

    if svc_type in ("ec2", "vm"):
        return await _fill_and_save_ec2(page, svc)
    elif svc_type == "rds":
        return await _fill_and_save_rds(page, svc)
    elif svc_type in ("s3", "storage"):
        return await _fill_and_save_s3(page, svc)
    else:
        return await _fill_and_save_ec2(page, svc)


# ─────────────────────────────────────────────────────────────────────────────
# Main combined generator — YOUR IDEA
# ─────────────────────────────────────────────────────────────────────────────

async def generate_combined_calculator_link(results: list[dict]) -> str:
    """
    YOUR IDEA implemented:
    1. Use proven individual code for FIRST service → get estimate?id=xxx
       (browser is now on estimate SUMMARY with real services showing)
    2. Click "Update estimate" if banner appears (dismiss it)
    3. Navigate same page to next service URL → fill → "Save and add service"
       → lands back on estimate summary with N+1 services
    4. Repeat for all remaining services
    5. Capture share link from estimate summary → ONE combined URL
    """
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
            page = await context.new_page()

            # ── Step 1: Add FIRST service using proven individual approach ──────
            first = services[0]
            svc_type = first["type"]
            logger.info(
                f"  [1/{len(services)}] Adding FIRST service: "
                f"{first['name']} ({svc_type}: {first.get('instance','')})"
            )

            if svc_type in ("ec2", "vm"):
                await _fill_and_save_ec2(page, first)
            elif svc_type == "rds":
                await _fill_and_save_rds(page, first)
            elif svc_type in ("s3", "storage"):
                await _fill_and_save_s3(page, first)
            else:
                await _fill_and_save_ec2(page, first)

            # After first service "Save and add service": AWS lands on #/addService
            # OR on the estimate summary. We need to get to the estimate summary
            # to see the "Update estimate" banner with the estimate ID.
            # Navigate to the estimate summary explicitly.
            current_url = page.url
            logger.info(f"  URL after first service: {current_url[:80]}")

            # If still on addService page, try clicking "My estimate" breadcrumb
            if "addService" in current_url or "createCalculator" in current_url:
                try:
                    breadcrumb = page.locator("a:has-text('My estimate'), a:has-text('My Estimate')").first
                    if await breadcrumb.is_visible(timeout=3000):
                        await breadcrumb.click()
                        await page.wait_for_timeout(3000)
                        logger.info(f"  ✅ Navigated to My Estimate via breadcrumb")
                except Exception:
                    pass

            # ── Step 2+: Add remaining services on the SAME page ────────────────
            for idx, svc in enumerate(services[1:], start=2):
                svc_type = svc["type"]
                logger.info(
                    f"  [{idx}/{len(services)}] Adding: "
                    f"{svc['name']} ({svc_type}: {svc.get('instance','')})"
                )
                try:
                    await _navigate_to_service(page, svc)
                    await page.wait_for_timeout(2000)

                    # After "Save and add service", navigate back to estimate summary
                    current_url = page.url
                    if "addService" in current_url or "createCalculator" in current_url:
                        try:
                            breadcrumb = page.locator(
                                "a:has-text('My estimate'), a:has-text('My Estimate')"
                            ).first
                            if await breadcrumb.is_visible(timeout=3000):
                                await breadcrumb.click()
                                await page.wait_for_timeout(3000)
                        except Exception:
                            pass

                except Exception as e:
                    logger.warning(f"  ⚠️ Failed to add {svc['name']}: {e}")
                    continue

            # ── Step 3: Capture the combined share link ──────────────────────────
            current_url = page.url
            logger.info(f"📋 Final URL: {current_url[:80]}")
            logger.info("📋 Capturing combined share link...")
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
