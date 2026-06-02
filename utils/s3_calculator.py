"""
utils/s3_calculator.py
----------------------
AWS S3 Pricing Calculator automation - generates shareable calculator links for S3.
"""

import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright, Page

logger = logging.getLogger(__name__)

# AWS S3 Calculator URL
S3_URL = "https://calculator.aws/#/createCalculator/S3"


async def generate_s3_calculator_link(
    region: str = "US East (N. Virginia)",
    storage_class: str = "S3 Standard",
    storage_amount_gb: float = 100,
    put_requests_per_month: int = 10000,
    get_requests_per_month: int = 100000,
    data_transfer_out_gb: float = 10,
    headless: bool = True,
) -> str:
    """
    Generate AWS Calculator link for S3 storage.
    
    Args:
        region: AWS region display name (e.g., "Asia Pacific (Mumbai)")
        storage_class: S3 storage class (S3 Standard, S3 Intelligent-Tiering, S3 Standard-IA, etc.)
        storage_amount_gb: Storage amount in GB
        put_requests_per_month: Number of PUT/COPY/POST/LIST requests per month
        get_requests_per_month: Number of GET/SELECT requests per month
        data_transfer_out_gb: Data transfer out to internet in GB per month
        headless: Run browser in headless mode
    
    Returns:
        Shareable AWS Calculator link or empty string if failed
    """
    try:
        from utils.aws_calculator import normalize_region, accept_cookies, capture_share_link
        
        # Normalize region
        region = normalize_region(region)
        
        logger.debug(f"Generating S3 calculator link for {storage_amount_gb}GB in {region}...")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            # Load S3 calculator page
            logger.debug(f"Loading AWS S3 Calculator...")
            await page.goto(S3_URL, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(4000)
            await accept_cookies(page)
            
            # Fill description
            description = f"S3 {storage_class} | {region} | {storage_amount_gb}GB"
            try:
                desc_input = page.locator("input[aria-label='Description - optional']").first
                await desc_input.scroll_into_view_if_needed()
                await desc_input.click(force=True)
                await desc_input.fill(description)
                logger.debug(f"Description: {description}")
            except Exception as e:
                logger.debug(f"Description field: {e}")
            
            # Select region
            logger.debug(f"Selecting region: {region}")
            try:
                # Try to find and click region dropdown
                region_label = page.locator("label:has-text('Choose a Region')").first
                for_attr = await region_label.get_attribute("for")
                if for_attr:
                    await page.locator(f"#{for_attr}").click()
                    await page.wait_for_timeout(800)
                    
                    # Select region option
                    region_opt = page.get_by_role("option", name=region, exact=True).first
                    if await region_opt.count() > 0:
                        await region_opt.scroll_into_view_if_needed()
                        await region_opt.click()
                        await page.wait_for_timeout(1200)
                        logger.debug(f"✅ Selected region: {region}")
            except Exception as e:
                logger.warning(f"⚠️ Could not select region: {e}")
            
            # Select storage class
            logger.debug(f"Selecting storage class: {storage_class}")
            try:
                # Storage class is usually a dropdown or radio button
                if "Standard" in storage_class and "IA" not in storage_class:
                    # Try to select S3 Standard radio button
                    radio = page.locator("input[type='radio'][value*='standard']").first
                    if await radio.count() > 0:
                        await radio.scroll_into_view_if_needed()
                        await radio.check()
                        logger.debug(f"✅ Selected storage class: {storage_class}")
            except Exception as e:
                logger.debug(f"Storage class selection: {e}")
            
            # Storage amount
            logger.debug(f"Setting storage amount: {storage_amount_gb} GB")
            try:
                storage_input = page.locator("input[aria-label*='Storage amount']").first
                if await storage_input.count() > 0:
                    await storage_input.scroll_into_view_if_needed()
                    await storage_input.click()
                    await storage_input.fill(str(storage_amount_gb))
                    logger.debug(f"✅ Storage: {storage_amount_gb} GB")
            except Exception as e:
                logger.debug(f"Storage amount: {e}")
            
            # PUT requests
            logger.debug(f"Setting PUT requests: {put_requests_per_month}")
            try:
                put_input = page.locator("input[aria-label*='PUT']").first
                if await put_input.count() > 0:
                    await put_input.scroll_into_view_if_needed()
                    await put_input.click()
                    await put_input.fill(str(put_requests_per_month))
                    logger.debug(f"✅ PUT requests: {put_requests_per_month}")
            except Exception as e:
                logger.debug(f"PUT requests: {e}")
            
            # GET requests
            logger.debug(f"Setting GET requests: {get_requests_per_month}")
            try:
                get_input = page.locator("input[aria-label*='GET']").first
                if await get_input.count() > 0:
                    await get_input.scroll_into_view_if_needed()
                    await get_input.click()
                    await get_input.fill(str(get_requests_per_month))
                    logger.debug(f"✅ GET requests: {get_requests_per_month}")
            except Exception as e:
                logger.debug(f"GET requests: {e}")
            
            # Data transfer out
            logger.debug(f"Setting data transfer out: {data_transfer_out_gb} GB")
            try:
                transfer_input = page.locator("input[aria-label*='Data transfer out']").first
                if await transfer_input.count() > 0:
                    await transfer_input.scroll_into_view_if_needed()
                    await transfer_input.click()
                    await transfer_input.fill(str(data_transfer_out_gb))
                    logger.debug(f"✅ Data transfer: {data_transfer_out_gb} GB")
            except Exception as e:
                logger.debug(f"Data transfer: {e}")
            
            # Save and view summary
            logger.debug("Clicking 'Save and view summary'...")
            save_clicked = False
            
            for save_sel in [
                "button[aria-label='Save and view summary']",
                "button:has-text('Save and view summary')",
                "button:has-text('Save and add service')",
            ]:
                try:
                    save_btn = page.locator(save_sel).first
                    if await save_btn.is_visible(timeout=2000):
                        await save_btn.scroll_into_view_if_needed()
                        await save_btn.click()
                        logger.debug(f"✅ Clicked save button: {save_sel}")
                        save_clicked = True
                        break
                except Exception:
                    continue
            
            if not save_clicked:
                # JavaScript fallback
                await page.evaluate("""
                    () => {
                        const btn = document.querySelector("button[aria-label='Save and view summary']");
                        if (btn) btn.click();
                    }
                """)
            
            await page.wait_for_timeout(4000)
            
            # Capture share link
            logger.debug("Capturing share link...")
            share_link = await capture_share_link(page)
            
            # Take screenshot on failure
            if not share_link:
                try:
                    screenshot_path = f"debug_s3_{storage_class.replace(' ', '_')}.png"
                    await page.screenshot(path=screenshot_path, full_page=True)
                    logger.debug(f"📸 Debug screenshot saved: {screenshot_path}")
                except Exception as e:
                    logger.debug(f"Screenshot failed: {e}")
            
            await browser.close()
            
            if share_link:
                logger.info(f"✅ Generated S3 calculator link: {storage_class}")
            else:
                logger.warning(f"⚠️ Failed to generate S3 calculator link")
            
            return share_link
            
    except Exception as e:
        logger.error(f"❌ Error generating S3 calculator link: {e}", exc_info=True)
        return ""


def generate_s3_calculator_link_sync(
    region: str = "US East (N. Virginia)",
    storage_class: str = "S3 Standard",
    storage_amount_gb: float = 100,
    put_requests_per_month: int = 10000,
    get_requests_per_month: int = 100000,
    data_transfer_out_gb: float = 10,
) -> str:
    """
    Synchronous wrapper for S3 calculator link generation.
    
    Args:
        region: AWS region display name
        storage_class: S3 storage class
        storage_amount_gb: Storage amount in GB
        put_requests_per_month: PUT requests per month
        get_requests_per_month: GET requests per month
        data_transfer_out_gb: Data transfer out in GB
    
    Returns:
        Shareable AWS Calculator link or empty string if failed
    """
    try:
        return asyncio.run(generate_s3_calculator_link(
            region=region,
            storage_class=storage_class,
            storage_amount_gb=storage_amount_gb,
            put_requests_per_month=put_requests_per_month,
            get_requests_per_month=get_requests_per_month,
            data_transfer_out_gb=data_transfer_out_gb,
        ))
    except Exception as e:
        logger.error(f"Error in S3 calculator link generation: {e}")
        return ""
