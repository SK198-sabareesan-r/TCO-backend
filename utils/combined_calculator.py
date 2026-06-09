"""
utils/combined_calculator.py
-----------------------------
Generate ONE AWS Calculator link containing ALL services.
"""

import asyncio
import logging
from playwright.async_api import async_playwright
from utils.aws_calculator import normalize_region, normalize_os, accept_cookies, capture_share_link

logger = logging.getLogger(__name__)

EC2_URL = "https://calculator.aws/#/addService"
RDS_URL = "https://calculator.aws/#/addService"
S3_URL = "https://calculator.aws/#/addService"


async def generate_combined_calculator_link(results: list[dict], headless: bool = True) -> str:
    """
    Generate ONE AWS Calculator link containing ALL services.

    Args:
        results: List of all service results from pipeline
        headless: Run browser in headless mode

    Returns:
        Single calculator link with all services
    """
    try:
        # Filter results that have valid matches
        valid_services = []
        for r in results:
            best = r.get("best_match", {})
            inp = r.get("input", {})
            if best.get("instance_type"):
                valid_services.append({
                    "name": inp.get("service_name", "Service"),
                    "type": inp.get("service_type", "ec2").lower(),
                    "instance": best.get("instance_type"),
                    "region": best.get("regioncode") or best.get("location") or inp.get("region", "US East (N. Virginia)"),
                    "os": best.get("operatingsystem") or inp.get("operating_system", "Linux"),
                    "tenancy": best.get("tenancy") or inp.get("tenancy", "Shared"),
                    "database_engine": best.get("databaseengine") or inp.get("database_engine"),
                    "storage_gb": inp.get("storage_gb", 100),
                })

        if not valid_services:
            logger.warning("No valid services to add to calculator")
            return ""

        logger.info(f"🔗 Generating COMBINED calculator link for {len(valid_services)} services")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})
            page = await context.new_page()

            # Start with blank calculator
            await page.goto("https://calculator.aws/#/", wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(3000)
            await accept_cookies(page)

            # Add each service
            for idx, svc in enumerate(valid_services, 1):
                logger.info(f"  [{idx}/{len(valid_services)}] Adding {svc['name']} ({svc['type']})...")

                try:
                    if svc['type'] == 'ec2':
                        await add_ec2_service(page, svc)
                    elif svc['type'] == 'rds':
                        await add_rds_service(page, svc)
                    elif svc['type'] == 's3':
                        await add_s3_service(page, svc)

                    logger.info(f"    ✅ Added {svc['name']}")
                except Exception as e:
                    logger.warning(f"    ⚠️ Failed to add {svc['name']}: {e}")
                    continue

            # Get the share link
            logger.info("📋 Saving combined estimate...")
            share_link = await capture_share_link(page)

            await browser.close()

            if share_link:
                logger.info(f"✅ Generated combined calculator link with {len(valid_services)} services")
            else:
                logger.warning("⚠️ Failed to generate combined calculator link")

            return share_link

    except Exception as e:
        logger.error(f"❌ Error generating combined calculator link: {e}")
        return ""


async def add_ec2_service(page, svc):
    """Add EC2 service to calculator."""
    # Click "Add Service" if not on service selection page
    try:
        add_btn = page.locator("button:has-text('Add service')").first
        if await add_btn.is_visible(timeout=2000):
            await add_btn.click()
            await page.wait_for_timeout(1000)
    except:
        pass

    # Select EC2
    try:
        ec2_card = page.locator("button:has-text('Amazon EC2')").first
        await ec2_card.click()
        await page.wait_for_timeout(2000)
    except:
        pass

    # Fill basic info (simplified - just instance type and save)
    try:
        # Description
        desc_input = page.locator("input[aria-label='Description - optional']").first
        await desc_input.fill(svc['name'])

        # Instance type search
        search = page.locator("input[aria-label*='Search instance types']").first
        await search.fill(svc['instance'])
        await page.wait_for_timeout(1500)

        # Select from table
        row_radio = page.locator(f"tr:has-text('{svc['instance']}') input[type='radio']").first
        await row_radio.check()
        await page.wait_for_timeout(500)

        # Save and add
        save_btn = page.locator("button:has-text('Save and add service')").first
        await save_btn.click()
        await page.wait_for_timeout(2000)

    except Exception as e:
        logger.debug(f"EC2 add details error: {e}")


async def add_rds_service(page, svc):
    """Add RDS service to calculator."""
    try:
        add_btn = page.locator("button:has-text('Add service')").first
        if await add_btn.is_visible(timeout=2000):
            await add_btn.click()
            await page.wait_for_timeout(1000)
    except:
        pass

    try:
        # Select RDS
        rds_card = page.locator("button:has-text('Amazon RDS')").first
        await rds_card.click()
        await page.wait_for_timeout(2000)

        # Description
        desc_input = page.locator("input[aria-label='Description - optional']").first
        await desc_input.fill(svc['name'])

        # Save and add
        save_btn = page.locator("button:has-text('Save and add service')").first
        await save_btn.click()
        await page.wait_for_timeout(2000)

    except Exception as e:
        logger.debug(f"RDS add details error: {e}")


async def add_s3_service(page, svc):
    """Add S3 service to calculator."""
    try:
        add_btn = page.locator("button:has-text('Add service')").first
        if await add_btn.is_visible(timeout=2000):
            await add_btn.click()
            await page.wait_for_timeout(1000)
    except:
        pass

    try:
        # Select S3
        s3_card = page.locator("button:has-text('Amazon S3')").first
        await s3_card.click()
        await page.wait_for_timeout(2000)

        # Description
        desc_input = page.locator("input[aria-label='Description - optional']").first
        await desc_input.fill(svc['name'])

        # Save and add
        save_btn = page.locator("button:has-text('Save and add service')").first
        await save_btn.click()
        await page.wait_for_timeout(2000)

    except Exception as e:
        logger.debug(f"S3 add details error: {e}")


def generate_combined_calculator_link_sync(results: list[dict]) -> str:
    """Synchronous wrapper for combined calculator link generation."""
    import concurrent.futures

    def run_async_in_thread(coro):
        def _run():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_run)
            return future.result(timeout=300)  # 5 minute timeout

    try:
        coro = generate_combined_calculator_link(results)

        # Check if event loop is running
        try:
            loop = asyncio.get_running_loop()
            return run_async_in_thread(coro)
        except RuntimeError:
            return asyncio.run(coro)
    except Exception as e:
        logger.error(f"Error generating combined calculator link: {e}")
        return ""
