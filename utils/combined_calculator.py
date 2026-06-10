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
    """
    instance_type    = svc["instance"]
    region           = normalize_region(svc["region"])
    operating_system = normalize_os(svc.get("os", "Linux"))
    tenancy          = svc.get("tenancy", "Shared")
    num_instances    = svc.get("num_instances", 1)
    pricing_model    = "on-demand"
    usage_pct        = 100
    storage_gb       = svc.get("storage_gb")

    tenancy_value = tenancy if "Instances" in tenancy or "Host" in tenancy else f"{tenancy} Instances"

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

    # Tenancy
    try:
        await select_dropdown_verified(page, "Tenancy", tenancy_value)
    except Exception:
        pass

    # OS
    await select_dropdown_verified(page, "Operating system", operating_system)

    # Workload (consistent)
    try:
        radio = page.locator("input[type='radio'][value='consistent']")
        await radio.scroll_into_view_if_needed()
        await radio.check()
    except Exception:
        pass

    # Number of instances
    await fill_input(page, "input[aria-label*='Number of instances']", str(num_instances))

    # Instance type search + table select
    try:
        search = page.locator("input[aria-label*='Search instance types']")
        await search.scroll_into_view_if_needed()
        await search.click(force=True)
        await search.fill(instance_type)
        await page.wait_for_timeout(2500)
        row_radio = page.locator(f"tr:has-text('{instance_type}') input[type='radio']").first
        await row_radio.scroll_into_view_if_needed()
        await row_radio.check()
        await page.wait_for_timeout(600)
    except Exception as e:
        logger.debug(f"EC2 instance select error: {e}")

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

    # Storage (optional)
    if storage_gb:
        try:
            await fill_input(page, "input[aria-label*='Storage amount']", str(storage_gb))
        except Exception:
            pass

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
    """
    database_engine = svc.get("database_engine") or "MySQL"
    instance_type   = svc["instance"]
    region          = normalize_region(svc["region"])
    deployment      = "Single-AZ"
    storage_type    = "General Purpose SSD (gp2)"
    storage_gb      = svc.get("storage_gb", 20)
    num_instances   = svc.get("num_instances", 1)

    url = RDS_URLS.get(database_engine, RDS_URLS["MySQL"])

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
                    break
        except Exception:
            pass

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

    # Instance type — find text input with "instance" or "class" in label
    try:
        inputs = await page.locator("input[type='text']").all()
        for inp in inputs:
            aria_label  = await inp.get_attribute("aria-label")
            placeholder = await inp.get_attribute("placeholder")
            if aria_label and ("instance" in aria_label.lower() or "class" in aria_label.lower()):
                await inp.scroll_into_view_if_needed()
                await inp.click()
                await inp.fill(instance_type)
                await page.wait_for_timeout(1500)
                await pick_option_safe(page, instance_type)
                break
            elif placeholder and ("instance" in placeholder.lower() or "class" in placeholder.lower()):
                await inp.scroll_into_view_if_needed()
                await inp.click()
                await inp.fill(instance_type)
                await page.wait_for_timeout(1500)
                await pick_option_safe(page, instance_type)
                break
    except Exception:
        pass

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

    # Storage amount — use JS to find the right input reliably
    # The RDS calculator storage label is "Storage amount (GiB)" or similar
    storage_gb_val = max(int(storage_gb) if storage_gb else 20, 20)
    try:
        filled = await page.evaluate("""
            (storageVal) => {
                // Find all number/text inputs and look for storage-related ones
                const inputs = [...document.querySelectorAll('input[type="text"], input[type="number"]')];
                for (const inp of inputs) {
                    const label = inp.getAttribute('aria-label') || inp.getAttribute('placeholder') || '';
                    if (label.toLowerCase().includes('storage') && 
                        !label.toLowerCase().includes('instance') &&
                        !label.toLowerCase().includes('class')) {
                        // Clear and fill
                        inp.focus();
                        inp.select();
                        // Use React-compatible value setter
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
            await page.wait_for_timeout(500)
            logger.debug(f"RDS storage set to {storage_gb_val} GB via JS")
        else:
            # Fallback: try aria-label selector directly
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
