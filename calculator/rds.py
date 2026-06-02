"""
rds.py  —  AWS Calculator  RDS Auto-Fill  v1
 
Mirrors s3.py exactly in style.
Opens calculator.aws, fills the RDS MySQL form, saves the estimate,
captures the share link, scrapes costs, and writes a result file.
 
Run:
    py rds.py
 
Requirements:
    pip install playwright --break-system-packages
    playwright install chromium
"""
 
import asyncio
import re
from playwright.async_api import async_playwright, Page
 
# ── URLs ──────────────────────────────────────────────────────────────────────
# Each engine has its own calculator URL
ENGINE_URLS = {
    "MySQL":          "https://calculator.aws/#/createCalculator/RDSMySQL",
    "PostgreSQL":     "https://calculator.aws/#/createCalculator/RDSPostgreSQL",
    "MariaDB":        "https://calculator.aws/#/createCalculator/RDSMariaDB",
    "SQL Server":     "https://calculator.aws/#/createCalculator/RDSSQLServer",
    "Oracle":         "https://calculator.aws/#/createCalculator/RDSOracle",
    "Aurora MySQL":   "https://calculator.aws/#/createCalculator/AuroraMySQL",
    "Aurora PostgreSQL": "https://calculator.aws/#/createCalculator/AuroraPostgreSQL",
}
 
REGIONS = [
    "US East (N. Virginia)", "US East (Ohio)", "US West (N. California)",
    "US West (Oregon)", "Africa (Cape Town)", "Asia Pacific (Hong Kong)",
    "Asia Pacific (Hyderabad)", "Asia Pacific (Jakarta)", "Asia Pacific (Malaysia)",
    "Asia Pacific (Melbourne)", "Asia Pacific (Mumbai)", "Asia Pacific (Osaka)",
    "Asia Pacific (Seoul)", "Asia Pacific (Singapore)", "Asia Pacific (Sydney)",
    "Asia Pacific (Thailand)", "Asia Pacific (Tokyo)", "Canada (Central)",
    "Canada West (Calgary)", "Europe (Frankfurt)", "Europe (Ireland)",
    "Europe (London)", "Europe (Milan)", "Europe (Paris)", "Europe (Spain)",
    "Europe (Stockholm)", "Europe (Zurich)", "Israel (Tel Aviv)",
    "Middle East (Bahrain)", "Middle East (UAE)", "South America (Sao Paulo)",
]
 
DEPLOYMENT_OPTIONS = ["Single-AZ", "Multi-AZ"]
 
STORAGE_TYPES = ["General Purpose SSD (gp2)", "General Purpose SSD (gp3)",
                 "Provisioned IOPS SSD (io1)", "Magnetic"]
 
ENGINES = list(ENGINE_URLS.keys())
 
 
# ── Input helpers ─────────────────────────────────────────────────────────────
 
def ask(prompt: str, default: str, options: list = None) -> str:
    if options:
        print(f"    Options: {', '.join(options)}")
    val = input(f"  {prompt} [{default}]: ").strip()
    return val if val else default
 
 
def ask_config() -> dict:
    print("=" * 66)
    print("  AWS Calculator  —  RDS Auto-Fill  v1")
    print("  Press Enter to keep the default value shown in [brackets]")
    print("=" * 66)
 
    print("\n── Basic Info ──────────────────────────────────────────────────")
    description = ask("Description", "My RDS Estimate")
    region      = ask("Region", "US East (N. Virginia)", REGIONS[:6])
 
    print("\n── RDS Engine & Instance ────────────────────────────────────────")
    engine        = ask("Database Engine", "MySQL", ENGINES)
    instance_type = ask("Instance Type (e.g. db.r5d.24xlarge)", "db.r5.large")
    deployment    = ask("Deployment", "Single-AZ", DEPLOYMENT_OPTIONS)
 
    print("\n── Storage ──────────────────────────────────────────────────────")
    storage_type   = ask("Storage Type", "General Purpose SSD (gp2)", STORAGE_TYPES)
    storage_amount = ask("Storage Amount (GB)", "100")
 
    print("\n── Additional Options ───────────────────────────────────────────")
    nodes          = ask("Number of instances / nodes", "1")
    backup_storage = ask("Backup storage (GB, leave blank to skip)", "")
    data_transfer  = ask("Data Transfer OUT to Internet (GB)", "10")
 
    print("\n── Display ─────────────────────────────────────────────────────")
    headless_inp = ask("Headless mode? (y/n)", "n", ["y", "n"])
    headless     = headless_inp.lower() == "y"
    output_file  = ask("Output file name", "rds_estimate_result.txt")
 
    config = dict(
        description=description,
        region=region,
        engine=engine,
        instance_type=instance_type,
        deployment=deployment,
        storage_type=storage_type,
        storage_amount=storage_amount,
        nodes=nodes,
        backup_storage=backup_storage,
        data_transfer=data_transfer,
        headless=headless,
        output_file=output_file,
        url=ENGINE_URLS.get(engine, ENGINE_URLS["MySQL"]),
    )
 
    print("\n" + "=" * 66)
    print("  CONFIRM CONFIG")
    print("=" * 66)
    print(f"  Description          : {config['description']}")
    print(f"  Region               : {config['region']}")
    print(f"  Engine               : {config['engine']}")
    print(f"  Instance Type        : {config['instance_type']}")
    print(f"  Deployment           : {config['deployment']}")
    print(f"  Storage Type         : {config['storage_type']}")
    print(f"  Storage Amount       : {config['storage_amount']} GB")
    print(f"  Nodes / Instances    : {config['nodes']}")
    print(f"  Backup Storage       : {config['backup_storage'] or 'N/A'}")
    print(f"  Data Transfer OUT    : {config['data_transfer']} GB")
    print(f"  Headless             : {config['headless']}")
    print(f"  Output file          : {config['output_file']}")
    print("=" * 66)
 
    confirm = input("\n  Proceed? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("  Aborted.")
        exit(0)
 
    return config
 
 
# ── Page helpers (identical to s3.py) ────────────────────────────────────────
 
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
 
    clicked = await page.evaluate(f"""
        () => {{
            const all = [...document.querySelectorAll('li, [role="option"], button, span')];
            const match = all.find(el =>
                el.offsetParent !== null &&
                el.textContent.trim() === `{option_text}`
            );
            if (match) {{ match.click(); return true; }}
            return false;
        }}
    """)
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
    print(f"   ⚠   Failed to set '{label_text}' to '{option_text}' after 3 attempts")
 
 
async def fill_field_with_fallback(page: Page, selectors: list, value: str, label: str) -> bool:
    for sel in selectors:
        try:
            field = page.locator(sel).first
            if await field.is_visible(timeout=1_500):
                await fill_input(page, sel, value)
                print(f"   ✅  {label}: {value}")
                return True
        except Exception:
            continue
    print(f"   ⚠   {label}: no matching field found (value '{value}' not filled)")
    return False
 
 
async def js_click(page: Page, selector: str):
    await page.evaluate(f"""
        () => {{
            const el = document.querySelector("{selector}");
            if (el) el.click();
        }}
    """)
    await page.wait_for_timeout(600)
 
 
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
    await page.screenshot(path="rds_estimate_bottom.png")
    print("   ✅  rds_estimate_bottom.png")
 
    await page.keyboard.press("End")
    await page.wait_for_timeout(500)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(800)
    await page.screenshot(path="rds_estimate_fullpage.png", full_page=True)
    print("   ✅  rds_estimate_fullpage.png  (full page)")
 
 
async def scrape_costs(page: Page) -> dict:
    result = {}
    for label in ["Monthly cost", "Total 12 months", "Upfront cost"]:
        try:
            await page.wait_for_selector(f"text={label}", timeout=12_000)
            break
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
                            for (let i = 0; i < 8; i++) {
                                el = el?.nextElementSibling;
                                const t = el?.textContent?.trim() || '';
                                if (t.includes('USD') || /[\d,]+\.\d{2}/.test(t)) return t;
                            }
                        }
                    }
                    const all = [...document.querySelectorAll('*')];
                    for (const el of all) {
                        if (el.children.length === 0 && el.textContent.trim() === label) {
                            let row = el.closest('tr, [class*="row"], [class*="summary"]');
                            if (row) {
                                const usd = [...row.querySelectorAll('*')]
                                    .find(c => c.children.length === 0 && c.textContent.includes('USD'));
                                if (usd) return usd.textContent.trim();
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
        rows     = await page.query_selector_all("table tbody tr")
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
    print("   → Looking for Share / Save estimate button …")
 
    share_selectors = [
        "button[aria-label='Save estimate']",
        "button[aria-label='Share']",
        "button:has-text('Save estimate')",
        "button:has-text('Share')",
    ]
 
    clicked = False
    for sel in share_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2_000):
                await btn.scroll_into_view_if_needed()
                await btn.click()
                clicked = True
                print(f"   ✅  Clicked: {sel}")
                break
        except Exception:
            continue
 
    if not clicked:
        print("   ⚠   Share button not found")
        return share_link
 
    await page.wait_for_timeout(2_000)
 
    save_dialog = page.get_by_role("dialog", name="Save estimate")
    try:
        await save_dialog.wait_for(state="visible", timeout=5_000)
        print("   ✅  Save estimate dialog visible")
    except Exception:
        print("   ⚠   Dialog not visible")
        return share_link
 
    try:
        agree_btn = save_dialog.get_by_role("button", name="Agree and continue")
        if await agree_btn.is_visible(timeout=2_000):
            await agree_btn.click()
            await page.wait_for_timeout(3_000)
            print("   ✅  Clicked 'Agree and continue'")
    except Exception:
        try:
            agree_btn = page.locator("button:has-text('Agree and continue')").first
            if await agree_btn.is_visible(timeout=2_000):
                await agree_btn.click()
                await page.wait_for_timeout(3_000)
                print("   ✅  Clicked 'Agree and continue' (fallback)")
        except Exception:
            pass
 
    await page.screenshot(path="rds_modal_share.png")
    print("   ✅  rds_modal_share.png")
 
    print("   → Waiting for Public share link …")
    for attempt in range(20):
        share_link = await page.evaluate("""
            () => {
                const inputs = [...document.querySelectorAll('input')];
                for (const inp of inputs) {
                    const v = inp.value || '';
                    if (v.includes('calculator.aws') && v.includes('estimate')) return v.trim();
                }
                const links = [...document.querySelectorAll('a[href*="calculator.aws"]')];
                if (links.length) return links[0].href.trim();
                return '';
            }
        """)
        if share_link:
            print(f"   ✅  Share link (attempt {attempt+1}): {share_link}")
            break
        await page.wait_for_timeout(1_000)
        print(f"   ⏳  attempt {attempt+1}/20 …")
 
    if not share_link:
        try:
            body_text = await page.inner_text("body")
            m = re.search(r"https://calculator\.aws/#/estimate\?id=[^\s\"'<>\n]+", body_text)
            if m:
                share_link = m.group(0).strip()
                print(f"   ✅  Share link (regex): {share_link}")
        except Exception:
            pass
 
    for close_sel in [
        "button[aria-label='Close modal']",
        "button[aria-label='Close']",
        "button[aria-label='Dismiss']",
        "button:has-text('Cancel')",
        "button:has-text('Close')",
    ]:
        try:
            btn = save_dialog.locator(close_sel).first
            if await btn.is_visible(timeout=1_500):
                await btn.click()
                await page.wait_for_timeout(800)
                print("   ✅  Modal closed")
                break
        except Exception:
            continue
 
    return share_link
 
 
# ── Main automation ───────────────────────────────────────────────────────────
 
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
 
        if CONFIG["headless"]:
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        else:
            context = await browser.new_context(no_viewport=True)
 
        page = await context.new_page()
 
        print("\n" + "=" * 66)
        print("  RUNNING …")
        print("=" * 66)
 
        # ── 1. Load ───────────────────────────────────────────────────────────
        print(f"\n[1]  Opening AWS RDS Calculator ({CONFIG['engine']}) …")
        await page.goto(CONFIG["url"], wait_until="networkidle", timeout=45_000)
        await page.wait_for_timeout(3_000)
        await accept_cookies(page)
        print("   ✅  Page loaded")
 
        # ── 2. Description ────────────────────────────────────────────────────
        print("\n[2]  Description …")
        try:
            await fill_input(page, "input[aria-label='Description - optional']", CONFIG["description"])
            print(f"   ✅  {CONFIG['description']}")
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # ── 3. Region ─────────────────────────────────────────────────────────
        print("\n[3]  Region …")
        try:
            await select_dropdown_verified(page, "Choose a Region", CONFIG["region"])
            await page.wait_for_timeout(1_200)
        except Exception as e:
            print(f"   ⚠   {e}")
 
        # ── 4. Deployment Option ──────────────────────────────────────────────
        print("\n[4]  Deployment Option …")
        try:
            # Try radio buttons first (common on RDS page)
            radio_selectors = [
                f"input[type='radio'][value*='Single']" if "Single" in CONFIG["deployment"] else f"input[type='radio'][value*='Multi']",
                f"label:has-text('{CONFIG['deployment']}')",
            ]
            deployed = False
            for sel in radio_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2_000):
                        await el.click()
                        await page.wait_for_timeout(600)
                        print(f"   ✅  Deployment: {CONFIG['deployment']}")
                        deployed = True
                        break
                except Exception:
                    continue
 
            if not deployed:
                # Fallback: dropdown
                await select_dropdown_verified(page, "Deployment", CONFIG["deployment"])
        except Exception as e:
            print(f"   ⚠   Deployment: {e}")
 
        await page.screenshot(path="rds_check_basic.png")
        print("   📷  rds_check_basic.png")
 
        # ── 5. Instance Type ──────────────────────────────────────────────────
        print("\n[5]  Instance Type …")
        try:
            # RDS instance type is typically a searchable dropdown
            it_selectors = [
                "input[aria-label*='instance type']",
                "input[aria-label*='Instance type']",
                "input[aria-label*='Instance class']",
                "input[placeholder*='instance']",
                "input[placeholder*='Instance']",
            ]
            typed = False
            for sel in it_selectors:
                try:
                    field = page.locator(sel).first
                    if await field.is_visible(timeout=2_000):
                        await field.click()
                        await field.fill(CONFIG["instance_type"])
                        await page.wait_for_timeout(800)
                        # pick from dropdown that appears
                        await pick_option_safe(page, CONFIG["instance_type"])
                        print(f"   ✅  Instance type: {CONFIG['instance_type']}")
                        typed = True
                        break
                except Exception:
                    continue
 
            if not typed:
                await select_dropdown_verified(page, "DB instance class", CONFIG["instance_type"])
        except Exception as e:
            print(f"   ⚠   Instance type: {e}")
 
        # ── 6. Number of Instances ────────────────────────────────────────────
        print("\n[6]  Number of Instances …")
        await fill_field_with_fallback(
            page,
            [
                "input[aria-label*='nodes']",
                "input[aria-label*='Nodes']",
                "input[aria-label*='instances']",
                "input[aria-label*='Instances']",
                "input[aria-label*='quantity']",
            ],
            CONFIG["nodes"],
            "Number of instances",
        )
 
        # ── 7. Storage Type ───────────────────────────────────────────────────
        print("\n[7]  Storage Type …")
        try:
            storage_type_short = CONFIG["storage_type"]
            # Try tab buttons (gp2, gp3, io1 tabs)
            for short in ["gp2", "gp3", "io1", "Magnetic"]:
                if short.lower() in storage_type_short.lower():
                    tab = page.locator(
                        f"button:has-text('{short}'), [role='tab']:has-text('{short}')"
                    ).first
                    if await tab.is_visible(timeout=1_500):
                        await tab.click()
                        await page.wait_for_timeout(600)
                        print(f"   ✅  Storage type tab: {short}")
                        break
            else:
                await select_dropdown_verified(page, "Storage type", CONFIG["storage_type"])
        except Exception as e:
            print(f"   ⚠   Storage type: {e}")
 
        # ── 8. Storage Amount ─────────────────────────────────────────────────
        print("\n[8]  Storage Amount …")
        await fill_field_with_fallback(
            page,
            [
                "input[aria-label*='Storage amount']",
                "input[aria-label*='storage amount']",
                "input[aria-label*='Allocated storage']",
                "input[aria-label*='allocated storage']",
                "input[aria-label*='Storage (GB)']",
            ],
            CONFIG["storage_amount"],
            "Storage amount (GB)",
        )
 
        await page.screenshot(path="rds_check_storage.png")
        print("   📷  rds_check_storage.png")
 
        # ── 9. Backup Storage ─────────────────────────────────────────────────
        if CONFIG.get("backup_storage"):
            print("\n[9]  Backup Storage …")
            await fill_field_with_fallback(
                page,
                [
                    "input[aria-label*='Backup']",
                    "input[aria-label*='backup']",
                    "input[aria-label*='snapshot']",
                ],
                CONFIG["backup_storage"],
                "Backup storage (GB)",
            )
 
        # ── 10. Data Transfer OUT ──────────────────────────────────────────────
        print("\n[10] Data Transfer OUT to Internet …")
        await fill_field_with_fallback(
            page,
            [
                "input[aria-label*='Data transfer out to internet']",
                "input[aria-label*='transfer out']",
                "input[aria-label*='Transfer OUT']",
                "input[aria-label*='Internet']",
                "input[aria-label*='outbound']",
            ],
            CONFIG["data_transfer"],
            "Data Transfer OUT",
        )
 
        await page.screenshot(path="rds_check_transfer.png")
        print("   📷  rds_check_transfer.png")
 
        # ── 11. Save and view summary ─────────────────────────────────────────
        print("\n[11] Clicking Save and view summary …")
        await js_click(page, "button[aria-label='Save and view summary']")
        await page.wait_for_timeout(4_000)
        await page.screenshot(path="rds_estimate_page.png")
        print("   ✅  rds_estimate_page.png")
 
        # ── 12. Scroll ────────────────────────────────────────────────────────
        print("\n[12] Scrolling summary page …")
        await scroll_estimate_page(page)
 
        # ── 13. Scrape costs ──────────────────────────────────────────────────
        print("\n[13] Scraping costs …")
        results = await scrape_costs(page)
 
        # ── 14. Share link ────────────────────────────────────────────────────
        print("\n[14] Capturing share link …")
        share_link = await click_share_and_capture_link(page)
 
        # ── Output ────────────────────────────────────────────────────────────
        print("\n" + "=" * 66)
        print("  ESTIMATE RESULTS")
        print("=" * 66)
        print(f"  Share link      :  {share_link or '⚠ Not captured'}")
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
                    label = h if headers else f"[{h}]"
                    print(f"    {str(label):30} : {v}")
        print("=" * 66)
 
        with open(CONFIG["output_file"], "w", encoding="utf-8") as f:
            f.write("AWS RDS Estimate Results\n")
            f.write("=" * 50 + "\n")
            f.write(f"Description          : {CONFIG['description']}\n")
            f.write(f"Region               : {CONFIG['region']}\n")
            f.write(f"Engine               : {CONFIG['engine']}\n")
            f.write(f"Instance Type        : {CONFIG['instance_type']}\n")
            f.write(f"Deployment           : {CONFIG['deployment']}\n")
            f.write(f"Storage Type         : {CONFIG['storage_type']}\n")
            f.write(f"Storage Amount       : {CONFIG['storage_amount']} GB\n")
            f.write(f"Nodes / Instances    : {CONFIG['nodes']}\n")
            if CONFIG.get("backup_storage"):
                f.write(f"Backup Storage       : {CONFIG['backup_storage']} GB\n")
            f.write(f"Data Transfer OUT    : {CONFIG['data_transfer']} GB\n")
            if share_link:
                f.write(f"Share link           : {share_link}\n")
            f.write("-" * 50 + "\n")
            f.write(f"Upfront cost    : {results.get('upfront_cost')}\n")
            f.write(f"Monthly cost    : {results.get('monthly_cost')}\n")
            f.write(f"Total 12 months : {results.get('total_12month_cost')}\n")
            f.write("-" * 50 + "\n")
            if headers:
                f.write("Headers : " + " | ".join(headers) + "\n\n")
            for i, row in enumerate(all_rows):
                f.write(f"Row {i+1} : " + " | ".join(row) + "\n")
 
        print(f"\n   ✅  {CONFIG['output_file']}")
        print("   ✅  Screenshots saved")
 
        if not CONFIG["headless"]:
            print("\nPress Enter to close …")
            input()
 
        await browser.close()
 
 
def main():
    CONFIG = ask_config()
    asyncio.run(run(CONFIG))
 
 
if __name__ == "__main__":
    main()