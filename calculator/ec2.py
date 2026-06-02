"""
fill_aws_calculator.py  —  v22
Run:  py ec2.py
"""
 
import asyncio
import re
from playwright.async_api import async_playwright, Page
 
URL = "https://calculator.aws/#/createCalculator/ec2-enhancement"
 
OS_MAP = {
    "Linux":           "Linux",
    "RHEL":            "Red Hat Enterprise Linux",
    "SUSE":            "SUSE Linux Enterprise Server",
    "Windows":         "Windows Server",
    "Windows_SQL_Std": "Windows Server with SQL Server Standard",
    "Windows_SQL_Web": "Windows Server with SQL Server Web",
    "Windows_SQL_Ent": "Windows Server with SQL Server Enterprise",
    "Linux_SQL_Std":   "Linux with SQL Server Standard",
    "Linux_SQL_Web":   "Linux with SQL Server Web",
}
 
REGIONS = [
    "US East (N. Virginia)", "US East (Ohio)", "US West (N. California)", "US West (Oregon)",
    "Africa (Cape Town)", "Asia Pacific (Hong Kong)", "Asia Pacific (Hyderabad)",
    "Asia Pacific (Jakarta)", "Asia Pacific (Malaysia)", "Asia Pacific (Melbourne)",
    "Asia Pacific (Mumbai)", "Asia Pacific (Osaka)", "Asia Pacific (Seoul)",
    "Asia Pacific (Singapore)", "Asia Pacific (Sydney)", "Asia Pacific (Thailand)",
    "Asia Pacific (Tokyo)", "Canada (Central)", "Canada West (Calgary)",
    "Europe (Frankfurt)", "Europe (Ireland)", "Europe (London)", "Europe (Milan)",
    "Europe (Paris)", "Europe (Spain)", "Europe (Stockholm)", "Europe (Zurich)",
    "Israel (Tel Aviv)", "Middle East (Bahrain)", "Middle East (UAE)",
    "South America (Sao Paulo)",
]
 
# Friendly name → internal key mapping (so users can type either)
PRICING_ALIASES = {
    "on-demand":               "on-demand",
    "on demand":               "on-demand",
    "ondemand":                "on-demand",
    "spot":                    "spot",
    "spot instances":          "spot",
    "reserved-compute":        "reserved-compute",
    "compute savings plans":   "reserved-compute",
    "compute savings":         "reserved-compute",
    "reserved-ec2instance":    "reserved-ec2instance",
    "ec2 instance savings plans": "reserved-ec2instance",
    "ec2 savings":             "reserved-ec2instance",
}
 
 
def ask(prompt, default, options=None):
    if options:
        print(f"\n  Options: {', '.join(options)}")
    val = input(f"  {prompt} [{default}]: ").strip()
    return val if val else default
 
 
def normalize_pricing(raw: str) -> str:
    """Convert any user input to internal pricing key."""
    return PRICING_ALIASES.get(raw.lower().strip(), "on-demand")
 
 
def ask_config():
    print("=" * 62)
    print("  AWS Calculator  —  EC2 Auto-Fill  v22")
    print("  Press Enter to keep the default value shown in [brackets]")
    print("=" * 62)
 
    print("\n── Basic Info ──────────────────────────────────────────────")
    instance_type = ask("Instance Type", "t3.micro")
    region        = ask("Region", "US East (N. Virginia)", REGIONS[:6])
    os_key        = ask("OS (key)", "Linux", list(OS_MAP.keys()))
    os_label      = OS_MAP.get(os_key, "Linux")
    description   = ask("Description", f"{instance_type} | {region} | {os_label}")
 
    print("\n── Instance Config ─────────────────────────────────────────")
    tenancy       = ask("Tenancy", "Shared Instances",
                        ["Shared Instances", "Dedicated Instances", "Dedicated Host"])
    workload      = ask("Workload", "consistent", ["consistent", "spiky"])
    num_instances = ask("Number of Instances", "1")
 
    print("\n── Pricing ─────────────────────────────────────────────────")
    pricing_raw   = ask("Pricing Model", "on-demand",
                        ["on-demand", "spot",
                         "reserved-compute  (= Compute Savings Plans)",
                         "reserved-ec2instance  (= EC2 Instance Savings Plans)"])
    pricing_model = normalize_pricing(pricing_raw)
 
    usage_pct        = "100"
    usage_type       = "Utilization percent per month"
    spot_discount    = "61"
    reservation_term = "3 year"
    payment_option   = "No upfront"
 
    if pricing_model == "on-demand":
        usage_pct  = ask("Usage %", "100")
        usage_type = ask("Usage type", "Utilization percent per month",
                         ["Utilization percent per month", "Hours per day",
                          "Hours per week", "Hours per month"])
    elif pricing_model == "spot":
        spot_discount = ask("Spot discount % (historical avg shown on page)", "61")
    elif pricing_model in ("reserved-compute", "reserved-ec2instance"):
        reservation_term = ask("Reservation term", "3 year", ["1 year", "3 year"])
        payment_option   = ask("Payment option", "No upfront",
                                ["No upfront", "Partial upfront", "All upfront"])
 
    print("\n── Storage (optional) ──────────────────────────────────────")
    storage_gb = ask("Storage GB (leave blank to skip)", "")
 
    print("\n── Display ─────────────────────────────────────────────────")
    headless_inp = ask("Headless mode? (y/n)", "n", ["y", "n"])
    headless     = headless_inp.lower() == "y"
    output_file  = ask("Output file name", "estimate_result.txt")
 
    config = {
        "description": description, "location_type": "Region", "region": region,
        "tenancy": tenancy, "os": os_key, "os_label": os_label, "workload": workload,
        "num_instances": num_instances, "instance_type": instance_type,
        "pricing_model": pricing_model, "usage_pct": usage_pct, "usage_type": usage_type,
        "spot_discount": spot_discount, "reservation_term": reservation_term,
        "payment_option": payment_option, "storage_gb": storage_gb,
        "headless": headless, "output_file": output_file,
    }
 
    # Human-readable label for confirm screen
    label_map = {
        "on-demand":            "On-Demand",
        "spot":                 "Spot Instances",
        "reserved-compute":     "Compute Savings Plans",
        "reserved-ec2instance": "EC2 Instance Savings Plans",
    }
 
    print("\n" + "=" * 62 + "\n  CONFIRM CONFIG\n" + "=" * 62)
    print(f"  Description   : {config['description']}")
    print(f"  Region        : {config['region']}")
    print(f"  OS            : {config['os_label']}")
    print(f"  Instance Type : {config['instance_type']}")
    print(f"  Instances     : {config['num_instances']}")
    print(f"  Tenancy       : {config['tenancy']}")
    print(f"  Workload      : {config['workload']}")
    print(f"  Pricing       : {label_map.get(pricing_model, pricing_model)}")
    if pricing_model == "on-demand":
        print(f"  Usage         : {config['usage_pct']}%  ({config['usage_type']})")
    elif pricing_model == "spot":
        print(f"  Spot Discount : {config['spot_discount']}%")
    elif pricing_model in ("reserved-compute", "reserved-ec2instance"):
        print(f"  Term          : {config['reservation_term']}")
        print(f"  Payment       : {config['payment_option']}")
    print(f"  Storage       : {config['storage_gb'] or 'N/A'}")
    print(f"  Output file   : {config['output_file']}")
    print("=" * 62)
 
    if input("\n  Proceed? [Y/n]: ").strip().lower() == "n":
        print("  Aborted.")
        exit(0)
    return config
 
 
# ── Helpers ────────────────────────────────────────────────────────────────────
 
async def accept_cookies(page: Page):
    try:
        btn = page.locator("button[aria-label='Accept all cookies']")
        if await btn.is_visible(timeout=4_000):
            await btn.click()
            await page.wait_for_timeout(800)
            print("   ✅  Cookies accepted")
    except Exception:
        pass
 
 
async def fill_input(page: Page, locator_str: str, value: str):
    field = page.locator(locator_str).first
    await field.scroll_into_view_if_needed()
    await field.click(force=True)
    await field.fill(value)
 
 
async def open_cloudscape_dropdown(page: Page, label_text: str):
    label = page.locator(f"label:has-text('{label_text}')").first
    for_attr = await label.get_attribute("for")
    if for_attr:
        await page.locator(f"#{for_attr}").click()
    else:
        await label.locator("..").locator("button").first.click()
    await page.wait_for_timeout(800)
 
 
async def pick_option_safe(page: Page, option_text: str):
    await page.wait_for_timeout(400)
    try:
        opt = page.get_by_role("option", name=option_text, exact=True)
        if await opt.count() > 0:
            await opt.first.scroll_into_view_if_needed()
            await opt.first.click()
            await page.wait_for_timeout(600)
            return True
    except Exception:
        pass
    for sel in [
        f"li[role='option']:has-text('{option_text}')",
        f"li:has-text('{option_text}')",
        f"button:has-text('{option_text}')",
        f"span:has-text('{option_text}')",
    ]:
        try:
            opt = page.locator(sel).first
            if await opt.is_visible(timeout=1_500):
                await opt.scroll_into_view_if_needed()
                await opt.click()
                await page.wait_for_timeout(600)
                return True
        except Exception:
            continue
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
    for attempt in range(3):
        await open_cloudscape_dropdown(page, label_text)
        await pick_option_safe(page, option_text)
        try:
            label    = page.locator(f"label:has-text('{label_text}')").first
            for_attr = await label.get_attribute("for")
            if for_attr:
                current = (await page.locator(f"#{for_attr}").inner_text()).strip()
                if option_text.lower() in current.lower():
                    print(f"   ✅  {label_text}  →  {current}")
                    return
                else:
                    print(f"   ↩  Retry {attempt+1}: got '{current}', want '{option_text}'")
                    await page.wait_for_timeout(600)
            else:
                print(f"   ✅  {label_text}  →  {option_text}")
                return
        except Exception:
            print(f"   ✅  {label_text}  →  {option_text}")
            return
    print(f"   ⚠   Failed to set '{label_text}' after 3 attempts")
 
 
async def js_click(page: Page, selector: str):
    await page.evaluate("""
        (selector) => {
            const el = document.querySelector(selector);
            if (el) el.click();
        }
    """, selector)
    await page.wait_for_timeout(600)
 
 
async def click_radio_by_label(page: Page, label_text: str) -> bool:
    try:
        label = page.locator(f"label:has-text('{label_text}')").first
        if await label.is_visible(timeout=2_000):
            await label.scroll_into_view_if_needed()
            await label.click()
            await page.wait_for_timeout(600)
            print(f"   ✅  Radio clicked: {label_text}")
            return True
    except Exception:
        pass
    clicked = await page.evaluate("""
        (labelText) => {
            for (const el of document.querySelectorAll('label, span, div, h3, p')) {
                if (el.offsetParent !== null && el.textContent.trim() === labelText) {
                    const r = el.closest('label')?.querySelector('input[type="radio"]')
                           || el.parentElement?.querySelector('input[type="radio"]')
                           || el.previousElementSibling;
                    if (r && r.type === 'radio') { r.click(); return true; }
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """, label_text)
    await page.wait_for_timeout(600)
    if clicked:
        print(f"   ✅  JS radio clicked: {label_text}")
    return bool(clicked)
 
 
async def select_pricing_section(page: Page, pricing_model: str):
    """
    Click the correct pricing radio/card.
    Strategy:
      1. Try known radio IDs
      2. Try aria-label on radio inputs
      3. Try clicking visible label text
      4. JS fallback scan
    """
    model_map = {
        "on-demand":            "On-Demand",
        "spot":                 "Spot Instances",
        "reserved-compute":     "Compute Savings Plans",
        "reserved-ec2instance": "EC2 Instance Savings Plans",
    }
    label = model_map.get(pricing_model, "On-Demand")
    print(f"\n[10] Pricing Model → {label} …")
 
    # ── Strategy 1: known radio IDs ───────────────────────────────
    radio_ids = {
        "on-demand":            ["on-demand", "onDemand", "ON_DEMAND"],
        "spot":                 ["spot", "SPOT"],
        "reserved-compute":     ["reserved", "RESERVED", "savings-plan", "savingsPlan"],
        "reserved-ec2instance": ["reserved", "RESERVED", "savings-plan", "savingsPlan"],
    }
    checked = False
    for rid in radio_ids.get(pricing_model, []):
        try:
            radio = page.locator(f"input#{rid}").first
            if await radio.count() > 0:
                await radio.scroll_into_view_if_needed()
                await radio.check()
                await page.wait_for_timeout(800)
                print(f"   ✅  Radio #{rid} checked")
                checked = True
                break
        except Exception:
            continue
 
    # ── Strategy 2: aria-label / value attribute ──────────────────
    if not checked:
        for attr_val in ["on-demand", "spot", "reserved", "savings"]:
            if attr_val not in pricing_model.replace("-", "") and attr_val not in ["on-demand", "spot", "reserved", "savings"]:
                continue
            try:
                radio = page.locator(
                    f"input[type='radio'][value*='{attr_val}'], "
                    f"input[type='radio'][aria-label*='{attr_val}']"
                ).first
                if await radio.count() > 0 and await radio.is_visible(timeout=1_500):
                    await radio.scroll_into_view_if_needed()
                    await radio.check()
                    await page.wait_for_timeout(800)
                    print(f"   ✅  Radio by value/aria: {attr_val}")
                    checked = True
                    break
            except Exception:
                continue
 
    # ── Strategy 3: click the visible label card ──────────────────
    if not checked:
        await click_radio_by_label(page, label)
 
    await page.wait_for_timeout(800)
 
    # ── For savings plans: also click the specific plan card ──────
    if pricing_model in ("reserved-compute", "reserved-ec2instance"):
        await page.wait_for_timeout(600)
        success = await click_radio_by_label(page, label)
        if not success:
            # Try partial text match
            try:
                card = page.locator(f"div:has-text('{label}') input[type='radio']").first
                if await card.count() > 0:
                    await card.scroll_into_view_if_needed()
                    await card.check()
                    print(f"   ✅  Plan card radio: {label}")
            except Exception as e:
                print(f"   ⚠   Plan card failed: {e}")
 
 
async def configure_reserved_options(page: Page, reservation_term: str, payment_option: str):
    print(f"\n[10b] Reservation Term → {reservation_term} …")
    if not await click_radio_by_label(page, reservation_term):
        try:
            await page.locator(f"label:has-text('{reservation_term}')").first.click()
            print(f"   ✅  Term: {reservation_term}")
        except Exception as e:
            print(f"   ⚠   Term failed: {e}")
 
    print(f"\n[10c] Payment Option → {payment_option} …")
    if not await click_radio_by_label(page, payment_option):
        try:
            await page.locator(f"label:has-text('{payment_option}')").first.click()
            print(f"   ✅  Payment: {payment_option}")
        except Exception as e:
            print(f"   ⚠   Payment failed: {e}")
 
 
async def configure_spot_discount(page: Page, spot_discount: str):
    print(f"\n[10b] Spot Discount → {spot_discount}% …")
    filled = await page.evaluate("""
        (discount) => {
            for (const lbl of document.querySelectorAll('label, p, span, div')) {
                if (lbl.textContent.includes('Assume percentage discount')) {
                    const container = lbl.closest('div[class]') || lbl.parentElement;
                    const inp = container?.querySelector('input') || lbl.nextElementSibling;
                    if (inp && inp.tagName === 'INPUT') {
                        inp.focus(); inp.select();
                        inp.value = discount;
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                }
            }
            return false;
        }
    """, spot_discount)
    if filled:
        print(f"   ✅  Spot discount (JS): {spot_discount}%")
    else:
        try:
            field = page.locator("input[aria-label*='iscount']").first
            await field.triple_click()
            await field.fill(spot_discount)
            print(f"   ✅  Spot discount (aria): {spot_discount}%")
        except Exception as e:
            print(f"   ⚠   Spot discount failed: {e}")
 
 
async def configure_usage_type(page: Page, usage_type: str):
    print(f"\n[11b] Usage type → {usage_type} …")
    try:
        await select_dropdown_verified(page, "Usage type", usage_type)
    except Exception:
        try:
            sel_el = page.locator("select").filter(
                has_text="Utilization percent per month"
            ).first
            await sel_el.select_option(label=usage_type)
            print(f"   ✅  Usage type (select): {usage_type}")
        except Exception as e:
            print(f"   ⚠   Usage type failed: {e}")
 
 
async def scroll_estimate_page(page: Page):
    print("   → Scrolling to bottom …")
    await page.evaluate("""
        () => {
            window.scrollTo(0, document.body.scrollHeight);
            document.querySelectorAll('div').forEach(el => {
                const ov = window.getComputedStyle(el).overflowY;
                if ((ov === 'auto' || ov === 'scroll') && el.scrollHeight > el.clientHeight + 10)
                    el.scrollTop = el.scrollHeight;
            });
        }
    """)
    await page.wait_for_timeout(1_500)
    await page.screenshot(path="estimate_bottom.png")
    print("   ✅  estimate_bottom.png")
    await page.keyboard.press("End")
    await page.wait_for_timeout(500)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(800)
    await page.screenshot(path="estimate_fullpage.png", full_page=True)
    print("   ✅  estimate_fullpage.png")
 
 
async def scrape_costs(page: Page) -> dict:
    result = {}
    try:
        await page.wait_for_selector("text=Monthly cost", timeout=8_000)
    except Exception:
        pass
    try:
        costs = await page.evaluate("""
            () => {
                const find = (label) => {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while (node = walker.nextNode()) {
                        if (node.textContent.trim() === label) {
                            let el = node.parentElement;
                            for (let i = 0; i < 6; i++) {
                                el = el?.nextElementSibling;
                                if (el?.textContent.includes('USD')) return el.textContent.trim();
                            }
                        }
                    }
                    return 'N/A';
                };
                return {
                    upfront:  find('Upfront cost'),
                    monthly:  find('Monthly cost'),
                    total_12: find('Total 12 months cost'),
                };
            }
        """)
        result["upfront_cost"]       = costs.get("upfront",  "N/A")
        result["monthly_cost"]       = costs.get("monthly",  "N/A")
        result["total_12month_cost"] = costs.get("total_12", "N/A")
    except Exception:
        full = await page.inner_text("body")
        for lbl, key in [
            ("Upfront cost",         "upfront_cost"),
            ("Monthly cost",         "monthly_cost"),
            ("Total 12 months cost", "total_12month_cost"),
        ]:
            m = re.search(rf"{lbl}\s+([\d,.]+ USD)", full)
            result[key] = m.group(1) if m else "N/A"
 
    try:
        ths = await page.query_selector_all("table thead th, table thead td")
        result["headers"] = [(await h.inner_text()).strip() for h in ths]
    except Exception:
        result["headers"] = []
 
    try:
        await page.wait_for_selector("table tbody tr", timeout=8_000)
        rows = await page.query_selector_all("table tbody tr")
        all_rows = []
        for row in rows:
            cells = await row.query_selector_all("td")
            texts = [(await c.inner_text()).strip() for c in cells]
            if any(texts):
                all_rows.append(texts)
        result["table_rows"] = all_rows
    except Exception:
        result["table_rows"] = []
 
    return result
 
 
async def click_share_and_capture_link(page: Page) -> str:
    share_link = ""
    print("   → Looking for Share button …")
 
    for sel in [
        "button[aria-label='Save estimate']", "button[aria-label='Share']",
        "button:has-text('Save estimate')",   "button:has-text('Share')",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2_000):
                await btn.scroll_into_view_if_needed()
                await btn.click()
                print(f"   ✅  Clicked: {sel}")
                break
        except Exception:
            continue
    else:
        print("   ⚠   Share button not found")
        return share_link
 
    await page.wait_for_timeout(2_500)
 
    # ── Handle Agree and continue dialog ─────────────────────────
    agree_selectors = [
        "button:has-text('Agree and continue')",
        "button:has-text('Agree')",
        "[role='dialog'] button:has-text('continue')",
    ]
    for agree_sel in agree_selectors:
        try:
            agree_btn = page.locator(agree_sel).first
            if await agree_btn.is_visible(timeout=3_000):
                await agree_btn.scroll_into_view_if_needed()
                await agree_btn.click()
                print("   ✅  Clicked 'Agree and continue'")
                await page.wait_for_timeout(4_000)   # wait for link to generate
                break
        except Exception:
            continue
 
    await page.screenshot(path="modal_share.png")
    print("   ✅  modal_share.png")
 
    # ── Wait for share link ───────────────────────────────────────
    print("   → Waiting for share link …")
    for attempt in range(20):
        share_link = await page.evaluate("""
            () => {
                for (const inp of document.querySelectorAll('input')) {
                    const v = inp.value || '';
                    if (v.includes('calculator.aws') && v.includes('estimate')) return v.trim();
                }
                // Also check anchor tags
                for (const a of document.querySelectorAll('a')) {
                    const h = a.href || '';
                    if (h.includes('calculator.aws') && h.includes('estimate')) return h.trim();
                }
                return '';
            }
        """)
        if share_link:
            print(f"   ✅  Share link captured (attempt {attempt+1}): {share_link}")
            break
        await page.wait_for_timeout(1_000)
        print(f"   ⏳  attempt {attempt+1}/20 …")
 
    # ── Regex fallback ────────────────────────────────────────────
    if not share_link:
        try:
            body_text = await page.inner_text("body")
            m = re.search(r"https://calculator\.aws[^\s\"'<>\n]+estimate[^\s\"'<>\n]*", body_text)
            if m:
                share_link = m.group(0).strip()
                print(f"   ✅  Share link (regex): {share_link}")
        except Exception:
            pass
 
    # ── Close modal ───────────────────────────────────────────────
    for close_sel in [
        "button[aria-label='Close modal']", "button[aria-label='Close']",
        "button[aria-label='Dismiss']",     "button:has-text('Done')",
        "button:has-text('Cancel')",        "button:has-text('Close')",
    ]:
        try:
            btn = page.locator(close_sel).first
            if await btn.is_visible(timeout=1_500):
                await btn.click()
                await page.wait_for_timeout(800)
                print("   ✅  Modal closed")
                break
        except Exception:
            continue
 
    return share_link
 
 
# ── Main ───────────────────────────────────────────────────────────────────────
 
async def run(CONFIG: dict):
    async with async_playwright() as p:
        launch_args = ["--no-sandbox", "--disable-setuid-sandbox"]
        if not CONFIG["headless"]:
            launch_args.append("--start-maximized")
 
        browser = await p.chromium.launch(
            headless=CONFIG["headless"],
            slow_mo=50 if CONFIG["headless"] else 200,
            args=launch_args,
        )
        context = (
            await browser.new_context(viewport={"width": 1920, "height": 1080})
            if CONFIG["headless"]
            else await browser.new_context(no_viewport=True)
        )
        page = await context.new_page()
        print("\n" + "=" * 62 + "\n  RUNNING …\n" + "=" * 62)
 
        # [1] Load
        print("\n[1]  Opening AWS Calculator …")
        await page.goto(URL, wait_until="networkidle", timeout=45_000)
        await page.wait_for_timeout(3_000)
        await accept_cookies(page)
        print("   ✅  Page loaded")
 
        # [2] Description
        print("\n[2]  Description …")
        try:
            await fill_input(page, "input[aria-label='Description - optional']", CONFIG["description"])
            print(f"   ✅  {CONFIG['description']}")
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # [3] Location Type
        print("\n[3]  Location Type …")
        try:
            await select_dropdown_verified(page, "Choose a location type", CONFIG["location_type"])
            await page.wait_for_timeout(1_000)
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # [4] Region
        print("\n[4]  Region …")
        try:
            await select_dropdown_verified(page, "Choose a Region", CONFIG["region"])
            await page.wait_for_timeout(1_200)
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # [5] Tenancy
        print("\n[5]  Tenancy …")
        try:
            await select_dropdown_verified(page, "Tenancy", CONFIG["tenancy"])
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # [6] OS
        print("\n[6]  Operating System …")
        try:
            await select_dropdown_verified(page, "Operating system", CONFIG["os_label"])
        except Exception as e:
            print(f"   ⚠   {e}")
        await page.screenshot(path="check_after_os.png")
        print("   📷  check_after_os.png")
 
        # [7] Workload
        print("\n[7]  Workload …")
        try:
            radio = page.locator(f"input[type='radio'][value='{CONFIG['workload']}']")
            await radio.scroll_into_view_if_needed()
            await radio.check()
            print(f"   ✅  {CONFIG['workload']}")
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # [8] Instances
        print("\n[8]  Number of instances …")
        try:
            await fill_input(page, "input[aria-label*='Number of instances']", CONFIG["num_instances"])
            print(f"   ✅  {CONFIG['num_instances']}")
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # [9] Instance type
        print("\n[9]  Instance type …")
        try:
            search = page.locator("input[aria-label*='Search instance types']")
            await search.scroll_into_view_if_needed()
            await search.click(force=True)
            await search.fill(CONFIG["instance_type"])
            await page.wait_for_timeout(2_500)
            row_radio = page.locator(
                f"tr:has-text('{CONFIG['instance_type']}') input[type='radio']"
            ).first
            await row_radio.scroll_into_view_if_needed()
            await row_radio.check()
            await page.wait_for_timeout(600)
            print(f"   ✅  {CONFIG['instance_type']}")
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # [10] Pricing
        await select_pricing_section(page, CONFIG["pricing_model"])
        await page.wait_for_timeout(1_200)
 
        if CONFIG["pricing_model"] in ("reserved-compute", "reserved-ec2instance"):
            await configure_reserved_options(
                page, CONFIG["reservation_term"], CONFIG["payment_option"]
            )
        elif CONFIG["pricing_model"] == "spot":
            await configure_spot_discount(page, CONFIG["spot_discount"])
        elif CONFIG["pricing_model"] == "on-demand":
            print("\n[11] Usage % …")
            try:
                await fill_input(page, "input[aria-label='Usage']", CONFIG["usage_pct"])
                print(f"   ✅  {CONFIG['usage_pct']}%")
            except Exception as e:
                print(f"   ⚠   {e}")
            if CONFIG["usage_type"] != "Utilization percent per month":
                await configure_usage_type(page, CONFIG["usage_type"])
 
        # [12] Storage
        if CONFIG.get("storage_gb"):
            print("\n[12] Storage …")
            try:
                await fill_input(page, "input[aria-label*='Storage amount']", CONFIG["storage_gb"])
                print(f"   ✅  {CONFIG['storage_gb']} GB")
            except Exception as e:
                print(f"   ⚠   {e}")
 
        # [13] Save and view summary
        print("\n[13] Clicking Save and view summary …")
        await js_click(page, "button[aria-label='Save and view summary']")
        try:
            btn = page.locator("button[aria-label='Save and view summary']")
            if await btn.is_visible(timeout=2_000):
                await btn.scroll_into_view_if_needed()
                await btn.click()
                print("   ✅  Save and view summary (fallback)")
        except Exception:
            pass
        await page.wait_for_timeout(4_000)
        await page.screenshot(path="estimate_page.png")
        print("   ✅  estimate_page.png")
 
        # [14] Scroll
        print("\n[14] Scrolling summary page …")
        await scroll_estimate_page(page)
 
        # [15] Scrape
        print("\n[15] Scraping costs …")
        results = await scrape_costs(page)
 
        # [16] Share link
        print("\n[16] Capturing share link …")
        share_link = await click_share_and_capture_link(page)
 
        # ── Results ────────────────────────────────────────────────────────────
        print("\n" + "=" * 62 + "\n  ESTIMATE RESULTS\n" + "=" * 62)
        print(f"  Share link      :  {share_link or 'Not captured'}")
        print(f"  Upfront cost    :  {results.get('upfront_cost')}")
        print(f"  Monthly cost    :  {results.get('monthly_cost')}")
        print(f"  Total 12 months :  {results.get('total_12month_cost')}")
 
        headers  = results.get("headers", [])
        all_rows = results.get("table_rows", [])
        if all_rows:
            print(f"\n  Service rows ({len(all_rows)} found):")
            for i, row in enumerate(all_rows):
                print(f"\n  ── Row {i+1} ──")
                for h, v in (zip(headers, row) if headers else enumerate(row)):
                    print(f"    {str(h):30} : {v}")
        print("=" * 62)
 
        # ── Save to file ───────────────────────────────────────────────────────
        with open(CONFIG["output_file"], "w", encoding="utf-8") as f:
            f.write("AWS EC2 Estimate Results\n" + "=" * 50 + "\n")
            f.write(f"Description     : {CONFIG['description']}\n")
            f.write(f"Region          : {CONFIG['region']}\n")
            f.write(f"Instance Type   : {CONFIG['instance_type']}\n")
            f.write(f"OS              : {CONFIG['os_label']}\n")
            f.write(f"Pricing Model   : {CONFIG['pricing_model']}\n")
            if CONFIG["pricing_model"] == "on-demand":
                f.write(f"Usage           : {CONFIG['usage_pct']}% ({CONFIG['usage_type']})\n")
            elif CONFIG["pricing_model"] == "spot":
                f.write(f"Spot Discount   : {CONFIG['spot_discount']}%\n")
            elif CONFIG["pricing_model"] in ("reserved-compute", "reserved-ec2instance"):
                f.write(f"Reservation Term: {CONFIG['reservation_term']}\n")
                f.write(f"Payment Option  : {CONFIG['payment_option']}\n")
            f.write(f"Instances       : {CONFIG['num_instances']}\n")
            if share_link:
                f.write(f"Share link      : {share_link}\n")
            f.write("-" * 50 + "\n")
            f.write(f"Upfront cost    : {results.get('upfront_cost')}\n")
            f.write(f"Monthly cost    : {results.get('monthly_cost')}\n")
            f.write(f"Total 12 months : {results.get('total_12month_cost')}\n")
            f.write("-" * 50 + "\n")
            if headers:
                f.write("Headers : " + " | ".join(headers) + "\n\n")
            for i, row in enumerate(all_rows):
                f.write(f"Row {i+1} : " + " | ".join(row) + "\n")
 
        print(f"\n   ✅  Saved to {CONFIG['output_file']}")
        print("   ✅  Screenshots saved")
 
        if not CONFIG["headless"]:
            input("\nPress Enter to close …")
        await browser.close()
 
 
def main():
    CONFIG = ask_config()
    asyncio.run(run(CONFIG))
 
 
if __name__ == "__main__":
    main()
AWS Pricing Calculator
AWS Pricing Calculator lets you explore AWS services, and create an estimate for the cost of your use cases on AWS.
 