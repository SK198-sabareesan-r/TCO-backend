"""
utils/aws_calculator.py
-----------------------
AWS Pricing Calculator automation - generates shareable calculator links.

Integrates with the pipeline to automatically create AWS Calculator links
for each service after cost estimation.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# AWS Calculator URLs
EC2_URL = "https://calculator.aws/#/createCalculator/ec2-enhancement"
RDS_URLS = {
    "MySQL": "https://calculator.aws/#/createCalculator/RDSMySQL",
    "PostgreSQL": "https://calculator.aws/#/createCalculator/RDSPostgreSQL",
    "MariaDB": "https://calculator.aws/#/createCalculator/RDSMariaDB",
    "SQL Server": "https://calculator.aws/#/createCalculator/RDSSQLServer",
    "Oracle": "https://calculator.aws/#/createCalculator/RDSOracle",
    "Aurora MySQL": "https://calculator.aws/#/createCalculator/AuroraMySQL",
    "Aurora PostgreSQL": "https://calculator.aws/#/createCalculator/AuroraPostgreSQL",
}

# OS mapping for calculator
OS_MAP = {
    "Linux": "Linux",
    "RHEL": "Red Hat Enterprise Linux",
    "SUSE": "SUSE Linux Enterprise Server",
    "Windows": "Windows Server",
    "Windows Server": "Windows Server",
    "ubuntu": "Linux",
    "Ubuntu": "Linux",
    "freebsd": "Linux",
    "FreeBSD": "Linux",
}

# Region code to display name mapping
REGION_MAP = {
    # US Regions
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    
    # Asia Pacific
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-east-1": "Asia Pacific (Hong Kong)",
    
    # Europe
    "eu-central-1": "Europe (Frankfurt)",
    "eu-west-1": "Europe (Ireland)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-north-1": "Europe (Stockholm)",
    "eu-south-1": "Europe (Milan)",
    
    # South America
    "sa-east-1": "South America (São Paulo)",
    
    # Canada
    "ca-central-1": "Canada (Central)",
    
    # Middle East
    "me-south-1": "Middle East (Bahrain)",
    
    # Africa
    "af-south-1": "Africa (Cape Town)",
    
    # Common variations
    "centralindia": "Asia Pacific (Mumbai)",
    "central india": "Asia Pacific (Mumbai)",
    "mumbai": "Asia Pacific (Mumbai)",
}


async def accept_cookies(page: Page):
    """Accept cookies if dialog appears."""
    try:
        btn = page.locator("button[aria-label='Accept all cookies']")
        if await btn.is_visible(timeout=4000):
            await btn.click()
            await page.wait_for_timeout(800)
            logger.debug("Cookies accepted")
    except Exception:
        pass


def normalize_region(region: str) -> str:
    """
    Normalize region to AWS Calculator display name.
    
    Args:
        region: Region code (ap-south-1) or name (Mumbai, centralindia)
    
    Returns:
        AWS Calculator display name (Asia Pacific (Mumbai))
    """
    if not region:
        return "US East (N. Virginia)"
    
    # Check if already in display format
    if region.startswith("US ") or region.startswith("Asia Pacific") or \
       region.startswith("Europe") or region.startswith("South America") or \
       region.startswith("Canada") or region.startswith("Middle East") or \
       region.startswith("Africa"):
        return region
    
    # Try direct mapping
    region_lower = region.lower().strip()
    if region_lower in REGION_MAP:
        return REGION_MAP[region_lower]
    
    # Try without hyphens/spaces
    region_normalized = region_lower.replace("-", "").replace(" ", "")
    for key, value in REGION_MAP.items():
        if key.replace("-", "").replace(" ", "") == region_normalized:
            return value
    
    # Default fallback
    logger.warning(f"Unknown region '{region}', using default US East (N. Virginia)")
    return "US East (N. Virginia)"


def normalize_os(os: str) -> str:
    """
    Normalize OS to AWS Calculator format.
    
    Args:
        os: Operating system name
    
    Returns:
        AWS Calculator OS name
    """
    if not os:
        return "Linux"
    
    os_lower = os.lower().strip()
    
    # Check direct mapping
    for key, value in OS_MAP.items():
        if key.lower() == os_lower:
            return value
    
    # Partial matching
    if "windows" in os_lower:
        return "Windows Server"
    elif "rhel" in os_lower or "red hat" in os_lower:
        return "Red Hat Enterprise Linux"
    elif "suse" in os_lower:
        return "SUSE Linux Enterprise Server"
    elif "ubuntu" in os_lower or "linux" in os_lower or "freebsd" in os_lower:
        return "Linux"
    
    # Default
    return "Linux"


async def fill_input(page: Page, locator_str: str, value: str):
    """Fill an input field."""
    try:
        field = page.locator(locator_str).first
        await field.scroll_into_view_if_needed()
        await field.click(force=True)
        await field.fill(value)
    except Exception as e:
        logger.debug(f"Failed to fill {locator_str}: {e}")


async def open_cloudscape_dropdown(page: Page, label_text: str):
    """Open a CloudScape dropdown by label."""
    label = page.locator(f"label:has-text('{label_text}')").first
    for_attr = await label.get_attribute("for")
    if for_attr:
        await page.locator(f"#{for_attr}").click()
    else:
        await label.locator("..").locator("button").first.click()
    await page.wait_for_timeout(800)


async def pick_option_safe(page: Page, option_text: str):
    """Pick an option from dropdown with multiple fallback strategies."""
    await page.wait_for_timeout(400)
    
    # Strategy 1: Role-based selection
    try:
        opt = page.get_by_role("option", name=option_text, exact=True)
        if await opt.count() > 0:
            await opt.first.scroll_into_view_if_needed()
            await opt.first.click()
            await page.wait_for_timeout(600)
            return True
    except Exception:
        pass
    
    # Strategy 2: Multiple selectors
    for sel in [
        f"li[role='option']:has-text('{option_text}')",
        f"li:has-text('{option_text}')",
        f"button:has-text('{option_text}')",
        f"span:has-text('{option_text}')",
    ]:
        try:
            opt = page.locator(sel).first
            if await opt.is_visible(timeout=1500):
                await opt.scroll_into_view_if_needed()
                await opt.click()
                await page.wait_for_timeout(600)
                return True
        except Exception:
            continue
    
    # Strategy 3: JavaScript fallback
    clicked = await page.evaluate("""
        (optionText) => {
            const all = [...document.querySelectorAll('li, [role="option"], button, span')];
            const match = all.find(el =>
                el.offsetParent !== null && el.textContent.trim() === optionText);
            if (match) { match.click(); return true; }
            return false;
        }
    """, option_text)
    await page.wait_for_timeout(600)
    return bool(clicked)


async def select_dropdown_verified(page: Page, label_text: str, option_text: str):
    """Select dropdown option with verification and retry."""
    for attempt in range(3):
        try:
            await open_cloudscape_dropdown(page, label_text)
            success = await pick_option_safe(page, option_text)
            
            if not success:
                logger.debug(f"Attempt {attempt+1}: pick_option_safe returned False")
                await page.wait_for_timeout(800)
                continue
            
            # Verify selection
            try:
                label = page.locator(f"label:has-text('{label_text}')").first
                for_attr = await label.get_attribute("for")
                if for_attr:
                    current = (await page.locator(f"#{for_attr}").inner_text()).strip()
                    if option_text.lower() in current.lower():
                        logger.debug(f"✅ Selected {label_text} -> {current}")
                        return True
                    else:
                        logger.debug(f"Retry {attempt+1}: got '{current}', want '{option_text}'")
                        await page.wait_for_timeout(800)
                else:
                    logger.debug(f"✅ Selected {label_text} -> {option_text} (no verification)")
                    return True
            except Exception as e:
                logger.debug(f"Verification failed, assuming success: {e}")
                return True
                
        except Exception as e:
            logger.debug(f"Attempt {attempt+1} failed: {e}")
            await page.wait_for_timeout(800)
    
    logger.warning(f"Failed to set '{label_text}' after 3 attempts")
    return False


async def capture_share_link(page: Page) -> str:
    """Click share button and capture the link."""
    try:
        # Click Save estimate button - try multiple selectors
        logger.debug("Looking for Save/Share button...")
        button_found = False
        
        for sel in [
            "button[aria-label='Save estimate']",
            "button[aria-label='Share']",
            "button:has-text('Save estimate')",
            "button:has-text('Share')",
            "button:has-text('Save and add service')",
            "button[type='submit']:has-text('Save')",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    logger.debug(f"✅ Clicked share button: {sel}")
                    button_found = True
                    break
            except Exception as e:
                logger.debug(f"Button selector '{sel}' failed: {e}")
                continue
        
        if not button_found:
            # Try JavaScript fallback
            logger.debug("Trying JavaScript fallback for share button...")
            clicked = await page.evaluate("""
                () => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = btn.textContent || '';
                        const ariaLabel = btn.getAttribute('aria-label') || '';
                        if (text.includes('Save') || text.includes('Share') || 
                            ariaLabel.includes('Save') || ariaLabel.includes('Share')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            if clicked:
                logger.debug("✅ Clicked share button via JavaScript")
                button_found = True
        
        if not button_found:
            logger.warning("⚠️ Share button not found")
            return ""
        
        await page.wait_for_timeout(3000)
        
        # Handle "Agree and continue" dialog
        logger.debug("Checking for 'Agree and continue' dialog...")
        agree_selectors = [
            "button:has-text('Agree and continue')",
            "button:has-text('Agree')",
            "[role='dialog'] button:has-text('continue')",
            "button:has-text('I agree')",
        ]
        for agree_sel in agree_selectors:
            try:
                agree_btn = page.locator(agree_sel).first
                if await agree_btn.is_visible(timeout=2000):
                    await agree_btn.scroll_into_view_if_needed()
                    await agree_btn.click()
                    logger.debug("✅ Clicked 'Agree and continue'")
                    await page.wait_for_timeout(4000)
                    break
            except Exception:
                continue
        
        # Wait for share link to be generated
        logger.debug("Waiting for share link to be generated...")
        share_link = ""
        for attempt in range(25):
            share_link = await page.evaluate("""
                () => {
                    // Check input fields
                    for (const inp of document.querySelectorAll('input')) {
                        const v = inp.value || '';
                        if (v.includes('calculator.aws') && v.includes('estimate')) 
                            return v.trim();
                    }
                    // Check anchor tags
                    for (const a of document.querySelectorAll('a')) {
                        const h = a.href || '';
                        if (h.includes('calculator.aws') && h.includes('estimate')) 
                            return h.trim();
                    }
                    return '';
                }
            """)
            if share_link:
                logger.debug(f"✅ Share link captured (attempt {attempt+1})")
                break
            await page.wait_for_timeout(1000)
        
        # Regex fallback
        if not share_link:
            try:
                logger.debug("Trying regex fallback for share link...")
                body_text = await page.inner_text("body")
                import re
                m = re.search(r"https://calculator\.aws[^\s\"'<>\n]+estimate[^\s\"'<>\n]*", body_text)
                if m:
                    share_link = m.group(0).strip()
                    logger.debug("✅ Share link found via regex")
            except Exception as e:
                logger.debug(f"Regex fallback failed: {e}")
        
        # Close modal
        logger.debug("Closing modal...")
        for close_sel in [
            "button[aria-label='Close modal']",
            "button[aria-label='Close']",
            "button[aria-label='Dismiss']",
            "button:has-text('Done')",
            "button:has-text('Cancel')",
            "button:has-text('Close')",
            "[role='dialog'] button[aria-label*='Close']",
        ]:
            try:
                btn = page.locator(close_sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await page.wait_for_timeout(800)
                    logger.debug("✅ Modal closed")
                    break
            except Exception:
                continue
        
        if share_link:
            logger.debug(f"✅ Final share link: {share_link[:80]}...")
        else:
            logger.warning("⚠️ Could not capture share link")
        
        return share_link
        
    except Exception as e:
        logger.error(f"❌ Failed to capture share link: {e}")
        return ""


async def generate_ec2_calculator_link(
    instance_type: str,
    region: str,
    operating_system: str = "Linux",
    tenancy: str = "Shared",
    num_instances: int = 1,
    pricing_model: str = "on-demand",
    usage_pct: int = 100,
    storage_gb: Optional[int] = None,
    headless: bool = True,
) -> str:
    """
    Generate AWS Calculator link for EC2 instance.
    
    Args:
        instance_type: AWS instance type (e.g., "t3.micro", "m5.xlarge")
        region: AWS region display name (e.g., "Asia Pacific (Mumbai)")
        operating_system: OS (Linux, Windows, RHEL, SUSE)
        tenancy: Shared Instances, Dedicated Instances, Dedicated Host
        num_instances: Number of instances
        pricing_model: on-demand, spot, reserved
        usage_pct: Usage percentage (0-100)
        storage_gb: Storage in GB (optional)
        headless: Run browser in headless mode (set False for debugging)
    
    Returns:
        Shareable AWS Calculator link or empty string if failed
    """
    try:
        # Normalize inputs
        region = normalize_region(region)
        operating_system = normalize_os(operating_system)
        
        logger.debug(f"Normalized region: {region}, OS: {operating_system}")
        
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
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Load page
            logger.debug(f"Loading AWS Calculator for {instance_type}...")
            await page.goto(EC2_URL, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(4000)
            await accept_cookies(page)
            
            # Fill description
            description = f"{instance_type} | {region} | {operating_system}"
            await fill_input(page, "input[aria-label='Description - optional']", description)
            
            # Select region - try most common label first
            logger.debug(f"Selecting region: {region}")
            region_success = await select_dropdown_verified(page, "Choose a Region", region)
            
            if not region_success:
                logger.warning(f"⚠️ Could not select region '{region}', continuing anyway...")
            else:
                await page.wait_for_timeout(1200)
            
            # Select tenancy
            tenancy_value = tenancy if "Instances" in tenancy or "Host" in tenancy else f"{tenancy} Instances"
            logger.debug(f"Selecting tenancy: {tenancy_value}")
            try:
                await select_dropdown_verified(page, "Tenancy", tenancy_value)
            except Exception as e:
                logger.debug(f"Tenancy selection failed: {e}")
            
            # Select OS - try most common label first
            os_label = operating_system  # Already normalized
            logger.debug(f"Selecting OS: {os_label}")
            os_success = await select_dropdown_verified(page, "Operating system", os_label)
            
            if not os_success:
                logger.warning(f"⚠️ Could not select OS '{os_label}', continuing anyway...")
            
            # Workload (consistent)
            try:
                radio = page.locator("input[type='radio'][value='consistent']")
                await radio.scroll_into_view_if_needed()
                await radio.check()
                logger.debug("Workload: consistent")
            except Exception:
                pass
            
            # Number of instances
            await fill_input(page, "input[aria-label*='Number of instances']", str(num_instances))
            logger.debug(f"Instances: {num_instances}")
            
            # Instance type - use search and select from table
            logger.debug(f"Searching for instance type: {instance_type}")
            try:
                search = page.locator("input[aria-label*='Search instance types']")
                await search.scroll_into_view_if_needed()
                await search.click(force=True)
                await search.fill(instance_type)
                await page.wait_for_timeout(2500)
                
                # Select from table row
                row_radio = page.locator(
                    f"tr:has-text('{instance_type}') input[type='radio']"
                ).first
                await row_radio.scroll_into_view_if_needed()
                await row_radio.check()
                await page.wait_for_timeout(600)
                logger.debug(f"Instance type selected: {instance_type}")
            except Exception as e:
                logger.warning(f"Failed to select instance type: {e}")
            
            # Pricing model
            logger.debug(f"Selecting pricing model: {pricing_model}")
            try:
                # Try known radio IDs
                radio_ids = {
                    "on-demand": ["on-demand", "onDemand", "ON_DEMAND"],
                    "spot": ["spot", "SPOT"],
                    "reserved": ["reserved", "RESERVED"],
                }
                checked = False
                for rid in radio_ids.get(pricing_model, ["on-demand"]):
                    try:
                        radio = page.locator(f"input#{rid}").first
                        if await radio.count() > 0:
                            await radio.scroll_into_view_if_needed()
                            await radio.check()
                            await page.wait_for_timeout(800)
                            checked = True
                            break
                    except Exception:
                        continue
                
                if not checked:
                    # Fallback: try by value attribute
                    radio = page.locator(f"input[type='radio'][value='{pricing_model}']").first
                    if await radio.count() > 0:
                        await radio.check()
                        await page.wait_for_timeout(800)
            except Exception as e:
                logger.debug(f"Pricing model selection: {e}")
            
            # Usage % (for on-demand and spot)
            if pricing_model in ("on-demand", "spot"):
                await fill_input(page, "input[aria-label='Usage']", str(usage_pct))
                logger.debug(f"Usage: {usage_pct}%")
            
            # Storage (optional)
            if storage_gb:
                await fill_input(page, "input[aria-label*='Storage amount']", str(storage_gb))
                logger.debug(f"Storage: {storage_gb} GB")
            
            # Save and view summary
            logger.debug("Clicking 'Save and view summary'...")
            save_clicked = False
            
            # Try multiple selectors
            for save_sel in [
                "button[aria-label='Save and view summary']",
                "button:has-text('Save and view summary')",
                "button:has-text('Save and add service')",
                "button[type='submit']:has-text('Save')",
            ]:
                try:
                    save_btn = page.locator(save_sel).first
                    if await save_btn.is_visible(timeout=2000):
                        await save_btn.scroll_into_view_if_needed()
                        await save_btn.click()
                        logger.debug(f"✅ Clicked save button: {save_sel}")
                        save_clicked = True
                        break
                except Exception as e:
                    logger.debug(f"Save selector '{save_sel}' failed: {e}")
                    continue
            
            if not save_clicked:
                # JavaScript fallback
                logger.debug("Trying JavaScript fallback for save button...")
                clicked = await page.evaluate("""
                    () => {
                        const btn = document.querySelector("button[aria-label='Save and view summary']");
                        if (btn) { btn.click(); return true; }
                        const buttons = document.querySelectorAll('button');
                        for (const b of buttons) {
                            if (b.textContent.includes('Save')) {
                                b.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                if clicked:
                    logger.debug("✅ Clicked save button via JavaScript")
                    save_clicked = True
            
            if not save_clicked:
                logger.warning("⚠️ Could not click save button")
            
            await page.wait_for_timeout(4000)
            
            # Capture share link
            logger.debug("Capturing share link...")
            share_link = await capture_share_link(page)
            
            # Take screenshot on failure for debugging
            if not share_link:
                try:
                    screenshot_path = f"debug_ec2_{instance_type.replace('.', '_')}.png"
                    await page.screenshot(path=screenshot_path, full_page=True)
                    logger.debug(f"📸 Debug screenshot saved: {screenshot_path}")
                except Exception as e:
                    logger.debug(f"Screenshot failed: {e}")
            
            await browser.close()
            
            if share_link:
                logger.info(f"✅ Generated EC2 calculator link: {instance_type}")
            else:
                logger.warning(f"⚠️ Failed to generate calculator link for {instance_type}")
            
            return share_link
            
    except Exception as e:
        logger.error(f"❌ Error generating EC2 calculator link: {e}", exc_info=True)
        return ""


async def generate_rds_calculator_link(
    instance_type: str,
    region: str,
    database_engine: str = "MySQL",
    deployment: str = "Single-AZ",
    storage_type: str = "General Purpose SSD (gp2)",
    storage_gb: int = 100,
    num_instances: int = 1,
) -> str:
    """
    Generate AWS Calculator link for RDS instance.
    
    Args:
        instance_type: RDS instance type (e.g., "db.t3.micro", "db.r5.large")
        region: AWS region display name
        database_engine: MySQL, PostgreSQL, MariaDB, SQL Server, Oracle
        deployment: Single-AZ, Multi-AZ
        storage_type: General Purpose SSD (gp2), gp3, io1, Magnetic
        storage_gb: Storage in GB
        num_instances: Number of instances
    
    Returns:
        Shareable AWS Calculator link or empty string if failed
    """
    try:
        # Get URL for engine
        url = RDS_URLS.get(database_engine, RDS_URLS["MySQL"])
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})
            page = await context.new_page()
            
            # Load page
            logger.debug(f"Loading AWS RDS Calculator for {instance_type} ({database_engine})...")
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(5000)  # Extra wait for RDS page
            await accept_cookies(page)
            logger.debug("Page loaded")
            
            # Fill description
            description = f"{instance_type} | {region} | {database_engine}"
            try:
                await fill_input(page, "input[aria-label='Description - optional']", description)
                logger.debug(f"Description: {description}")
            except Exception as e:
                logger.debug(f"Description failed: {e}")
            
            # Select region - try multiple approaches
            logger.debug(f"Selecting region: {region}")
            region_selected = False
            
            # Approach 1: Try any label containing "Region"
            try:
                labels = await page.locator("label").all()
                for label in labels:
                    text = await label.inner_text()
                    if "region" in text.lower():
                        logger.debug(f"Found region label: {text}")
                        await open_cloudscape_dropdown(page, text.strip())
                        await pick_option_safe(page, region)
                        region_selected = True
                        break
            except Exception as e:
                logger.debug(f"Region approach 1 failed: {e}")
            
            # Approach 2: Try direct button click
            if not region_selected:
                try:
                    # Look for any button that might be the region selector
                    buttons = await page.locator("button").all()
                    for btn in buttons:
                        aria_label = await btn.get_attribute("aria-label")
                        if aria_label and "region" in aria_label.lower():
                            await btn.click()
                            await page.wait_for_timeout(800)
                            await pick_option_safe(page, region)
                            region_selected = True
                            break
                except Exception as e:
                    logger.debug(f"Region approach 2 failed: {e}")
            
            if region_selected:
                logger.debug(f"Region selected: {region}")
                await page.wait_for_timeout(1200)
            else:
                logger.warning(f"Could not select region, continuing anyway...")
            
            # Deployment option
            logger.debug(f"Selecting deployment: {deployment}")
            try:
                # Try radio buttons
                if "Single" in deployment:
                    radio = page.locator("input[type='radio'][value*='Single']").first
                else:
                    radio = page.locator("input[type='radio'][value*='Multi']").first
                
                if await radio.count() > 0:
                    await radio.scroll_into_view_if_needed()
                    await radio.click()
                    await page.wait_for_timeout(600)
                    logger.debug(f"Deployment: {deployment}")
            except Exception as e:
                logger.debug(f"Deployment selection: {e}")
            
            # Instance type - try direct input fill
            logger.debug(f"Setting instance type: {instance_type}")
            try:
                # Find any input that might be for instance type
                inputs = await page.locator("input[type='text']").all()
                for inp in inputs:
                    aria_label = await inp.get_attribute("aria-label")
                    placeholder = await inp.get_attribute("placeholder")
                    
                    if aria_label and ("instance" in aria_label.lower() or "class" in aria_label.lower()):
                        await inp.scroll_into_view_if_needed()
                        await inp.click()
                        await inp.fill(instance_type)
                        await page.wait_for_timeout(1500)
                        await pick_option_safe(page, instance_type)
                        logger.debug(f"Instance type: {instance_type}")
                        break
                    elif placeholder and ("instance" in placeholder.lower() or "class" in placeholder.lower()):
                        await inp.scroll_into_view_if_needed()
                        await inp.click()
                        await inp.fill(instance_type)
                        await page.wait_for_timeout(1500)
                        await pick_option_safe(page, instance_type)
                        logger.debug(f"Instance type: {instance_type}")
                        break
            except Exception as e:
                logger.warning(f"Instance type selection: {e}")
            
            # Number of instances
            logger.debug(f"Setting instances: {num_instances}")
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
                            logger.debug(f"Instances: {num_instances}")
                            break
            except Exception as e:
                logger.debug(f"Instances field: {e}")
            
            # Storage type (try tab buttons)
            logger.debug(f"Selecting storage type: {storage_type}")
            try:
                for short in ["gp2", "gp3", "io1", "Magnetic"]:
                    if short.lower() in storage_type.lower():
                        tab = page.locator(f"button:has-text('{short}'), [role='tab']:has-text('{short}')").first
                        if await tab.is_visible(timeout=1500):
                            await tab.scroll_into_view_if_needed()
                            await tab.click()
                            await page.wait_for_timeout(600)
                            logger.debug(f"Storage type: {short}")
                            break
            except Exception as e:
                logger.debug(f"Storage type: {e}")
            
            # Storage amount
            logger.debug(f"Setting storage: {storage_gb} GB")
            try:
                inputs = await page.locator("input[type='text'], input[type='number']").all()
                for inp in inputs:
                    aria_label = await inp.get_attribute("aria-label")
                    if aria_label and "storage" in aria_label.lower() and "amount" in aria_label.lower():
                        await inp.scroll_into_view_if_needed()
                        await inp.click()
                        await inp.fill(str(storage_gb))
                        logger.debug(f"Storage: {storage_gb} GB")
                        break
            except Exception as e:
                logger.debug(f"Storage amount: {e}")
            
            # Save and view summary
            logger.debug("Clicking 'Save and view summary'...")
            try:
                save_btn = page.locator("button[aria-label='Save and view summary']").first
                if await save_btn.is_visible(timeout=3000):
                    await save_btn.scroll_into_view_if_needed()
                    await save_btn.click()
                    await page.wait_for_timeout(4000)
                else:
                    # JavaScript fallback
                    await page.evaluate("""
                        () => {
                            const btn = document.querySelector("button[aria-label='Save and view summary']");
                            if (btn) btn.click();
                        }
                    """)
                    await page.wait_for_timeout(4000)
            except Exception as e:
                logger.warning(f"Save button: {e}")
            
            # Capture share link
            logger.debug("Capturing share link...")
            share_link = await capture_share_link(page)
            
            await browser.close()
            
            if share_link:
                logger.info(f"✅ Generated RDS calculator link: {instance_type}")
            else:
                logger.warning(f"⚠️ Failed to generate calculator link for {instance_type}")
            
            return share_link
            
    except Exception as e:
        logger.error(f"Error generating RDS calculator link: {e}")
        return ""


def generate_calculator_link_sync(
    service_type: str,
    instance_type: str,
    region: str,
    **kwargs
) -> str:
    """
    Synchronous wrapper for generating calculator links.

    Args:
        service_type: ec2, rds, s3, etc.
        instance_type: AWS instance type
        region: AWS region display name
        **kwargs: Additional parameters (os, tenancy, database_engine, etc.)

    Returns:
        Shareable AWS Calculator link or empty string if failed
    """
    try:
        # Check if event loop is already running
        try:
            loop = asyncio.get_running_loop()
            # If we get here, event loop is running - disable calculator for now
            logger.debug("Event loop already running, skipping calculator link generation")
            return ""
        except RuntimeError:
            # No event loop running, safe to use asyncio.run()
            pass

        if service_type.lower() == "ec2":
            return asyncio.run(generate_ec2_calculator_link(
                instance_type=instance_type,
                region=region,
                operating_system=kwargs.get("operating_system", "Linux"),
                tenancy=kwargs.get("tenancy", "Shared"),
                num_instances=kwargs.get("num_instances", 1),
                pricing_model=kwargs.get("pricing_model", "on-demand"),
                usage_pct=kwargs.get("usage_pct", 100),
                storage_gb=kwargs.get("storage_gb"),
            ))
        elif service_type.lower() == "rds":
            return asyncio.run(generate_rds_calculator_link(
                instance_type=instance_type,
                region=region,
                database_engine=kwargs.get("database_engine", "MySQL"),
                deployment=kwargs.get("deployment", "Single-AZ"),
                storage_type=kwargs.get("storage_type", "General Purpose SSD (gp2)"),
                storage_gb=kwargs.get("storage_gb", 100),
                num_instances=kwargs.get("num_instances", 1),
            ))
        elif service_type.lower() == "s3":
            from utils.s3_calculator import generate_s3_calculator_link
            return asyncio.run(generate_s3_calculator_link(
                region=region,
                storage_class=kwargs.get("storage_class", "S3 Standard"),
                storage_amount_gb=kwargs.get("storage_amount_gb", 100),
                put_requests_per_month=kwargs.get("put_requests_per_month", 10000),
                get_requests_per_month=kwargs.get("get_requests_per_month", 100000),
                data_transfer_out_gb=kwargs.get("data_transfer_out_gb", 10),
            ))
        else:
            logger.warning(f"Calculator not supported for service type: {service_type}")
            return ""
    except Exception as e:
        logger.error(f"Error in calculator link generation: {e}")
        return ""
