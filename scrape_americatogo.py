from playwright.sync_api import sync_playwright, expect
from dotenv import load_dotenv
import os
import time
import logging
from datetime import datetime
import time
from urllib.parse import urljoin
import argparse
import pandas as pd
from google.oauth2.service_account import Credentials
from pathlib import Path
import re

# setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# get some env vars.
load_dotenv()
CATERING_SERVICE_PROVIDER = "AMERICATOGO"
LOGINID = os.getenv(f"{CATERING_SERVICE_PROVIDER}_LOGINID")
PW = os.getenv(f"{CATERING_SERVICE_PROVIDER}_PW")
SITE = os.getenv(f"{CATERING_SERVICE_PROVIDER}_SITE")
LOGIN_URL = os.getenv(f"{CATERING_SERVICE_PROVIDER}_LOGIN_URL")
SCOPES = ["https://www.googleapis.com/auth/calendar"]  # keep scopes in code

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)
EXPORT_MENU_ITEM_TEXT = "Export all data to XLS"


def login(page, LOGINID, PW):
     # Fill in email and password
    page.fill('input[name="Email"]', LOGINID)
    page.fill('input[name="Password"]', PW)

    # Click the Sign In button
    page.click('button[type="submit"]')

    # Optionally: wait for navigation or specific element after login
    page.wait_for_load_state("networkidle")

    # Check if login was successful
    current_url = page.url
    if 'Home/SignIn' not in current_url or 'VendorPortal' in current_url:
        logger.info("Login appears successful")
    else:
        logger.error("Login failed - still on login page")
def go_to_view_orders(page):
    # Preferred: accessible name
    try:
        page.get_by_role("button", name="View Orders").click()
    except Exception:
        logger.info("Fallback selector for View Orders")
        page.locator("button.navicon[data-title='View Orders']").click()

    page.wait_for_url(re.compile(r".*/VendorPortal/Orders.*"))
    logger.info(f"At Orders page: {page.url}")
    page.wait_for_load_state("networkidle")


def _find_export_root(page):
    """
    Return (root, is_frame) where root is a Locator *context* (page or frame)
    that contains the Export dropdown. Tries main page first, then iframes.
    """
    sel = ".dx-datagrid-export-button.dx-dropdownbutton[title='Export']"
    # main page?
    if page.locator(sel).first.count():
        return page, False
    # try iframes
    for fr in page.frames:
        try:
            if fr.locator(sel).first.count():
                return fr, True
        except Exception:
            continue
    raise AssertionError("Export dropdown not found on page or any iframe")

def open_export_menu(page):
    """
    Clicks the Export dropdown and waits for its popup (no aria-owns required).
    Works whether the grid is on the main page or inside an iframe.
    """
    root, _ = _find_export_root(page)

    # Make sure toolbar is rendered & in view
    root.locator(".dx-toolbar-items-container").first.wait_for(state="visible", timeout=15000)
    container = root.locator(".dx-datagrid-export-button.dx-dropdownbutton[title='Export']").first
    expect(container).to_be_visible(timeout=10000)

    btn = container.locator(".dx-dropdownbutton-action[role='button']").first
    expect(btn).to_be_visible(timeout=10000)

    if btn.get_attribute("aria-expanded") != "true":
        btn.click()

    # Wait for the DevExtreme overlay popup that contains the list items
    root.locator(".dx-dropdownbutton-content .dx-list-items").first.wait_for(state="visible", timeout=10000)

def export_all_to_xls(page, save_dir: Path) -> tuple[pd.DataFrame, Path]:
    save_dir.mkdir(parents=True, exist_ok=True)
    root, _ = _find_export_root(page)

    item = root.get_by_role("option", name=EXPORT_MENU_ITEM_TEXT).first
    expect(item).to_be_visible(timeout=10000)

    with page.expect_download() as dl_info:
        try:
            item.click()
        except Exception:
            item.click(force=True)

    download = dl_info.value
    suggested = download.suggested_filename or "orders.xls"
    out_path = save_dir / suggested
    download.save_as(str(out_path))
    logger.info(f"Saved export to: {out_path}")

    ext = out_path.suffix.lower()
    if ext == ".xlsx":
        df = pd.read_excel(out_path, engine="openpyxl")
    elif ext == ".xls":
        df = pd.read_excel(out_path, engine="xlrd")  # xlrd<2.0 required
    elif ext == ".csv":
        df = pd.read_csv(out_path)
    else:
        raise ValueError(f"Unsupported export format: {ext}")

    return df, out_path

def clean_text(text):
    if not text:
        return text
    # Insert spaces where letters/digits/AMPM kiss each other
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)       # aB -> a B
    text = re.sub(r'([A-Za-z])(\d)', r'\1 \2', text)       # A1 -> A 1
    text = re.sub(r'(\d)([A-Za-z])', r'\1 \2', text)       # 1A -> 1 A
    text = re.sub(r'\b(AM|PM)([A-Z][a-z])', r'\1 \2', text)# PMThu -> PM Thu
    text = re.sub(r'([0-9])([a-z]+@)', r'\1 \2', text)     # 9email@...
    text = re.sub(r'([a-z])(\(\d)', r'\1 \2', text)        # a(123
    return re.sub(r'\s+', ' ', text.strip())

def extract_order_details(page):
    """
    Extract order details from the popup that appears after clicking "View Order Text"
    
    Returns:
        dict: Dictionary containing extracted order information
    """
    iframe = page.frame_locator('iframe[name="frame"]')
    
    # Wait for the order table to appear - this is the most reliable indicator
    order_table = iframe.locator('#ordercopy').first
    order_table.wait_for(state="visible", timeout=15000)
    
    order_details = {}
    
    try:
        # Extract basic order information
        order_id_elem = order_table.locator('text=ATG Order ID:').locator('..').first
        if order_id_elem.count() > 0:
            order_id_text = order_id_elem.text_content()
            # Extract just the ID number
            order_id_match = re.search(r'ATG Order ID:\s*(\d+)', order_id_text)
            if order_id_match:
                order_details['atg_order_id'] = order_id_match.group(1)
        
        # Extract PO ID
        po_id_elem = order_table.locator('text=PO ID:').locator('..').first
        if po_id_elem.count() > 0:
            po_id_text = po_id_elem.text_content()
            po_id_match = re.search(r'PO ID:\s*(\w+)', po_id_text)
            if po_id_match:
                order_details['po_id'] = po_id_match.group(1)
        
        # Extract vendor name (appears to be "Dabao Singapore")
        vendor_elem = order_table.locator('.important').first
        if vendor_elem.count() > 0:
            order_details['vendor_name'] = clean_text(vendor_elem.text_content())
        
        # Extract delivery information with special HTML handling
        delivery_section = order_table.locator('text=Deliver to').locator('..').first
        if delivery_section.count() > 0:
            # Get the HTML content to better handle line breaks
            try:
                delivery_html = delivery_section.inner_html()
                # Replace HTML line breaks with spaces
                delivery_html = re.sub(r'<br\s*/?>', ' ', delivery_html)
                # Remove HTML tags and get text
                from html import unescape
                delivery_text = re.sub(r'<[^>]+>', '', delivery_html)
                delivery_text = unescape(delivery_text)
                order_details['delivery_info'] = clean_text(delivery_text)
            except:
                # Fallback to regular text content
                delivery_text = delivery_section.text_content()
                order_details['delivery_info'] = clean_text(delivery_text)
        
        # Extract delivery time (handle <br>, parse to fields)
        delivery_time_section = order_table.locator('text=Deliver at').locator('..').first
        if delivery_time_section.count() > 0:
            try:
                dt_html = delivery_time_section.inner_html()
                # <br> -> space; strip tags; unescape
                dt_text = re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', ' ', dt_html))
                from html import unescape
                dt_text = unescape(dt_text)
            except:
                dt_text = delivery_time_section.text_content()

            cleaned = clean_text(dt_text.replace('Deliver at', ''))
            order_details['delivery_time'] = cleaned

            m = re.search(r'(?P<time>\d{1,2}:\d{2}\s*[AP]M)\s+(?P<date>.+)', cleaned)
            if m:
                time_part = m.group('time').strip().upper()
                date_part = m.group('date').strip()
                parsed_date = next(
                    (datetime.strptime(date_part, fmt).date() for fmt in ("%A, %B %d, %Y", "%B %d, %Y")
                    if not isinstance(fmt, tuple)  # no-op; keeps same logic
                    for _ in [True]  # single-pass helper
                    if not (setattr(__import__('builtins'), '_x', None))  # dummy to satisfy comprehension
                    ),
                    None
                )
                # The above comprehension is too cute; keep simple for readability instead:
                parsed_date = None
                for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
                    try:
                        parsed_date = datetime.strptime(date_part, fmt).date()
                        break
                    except ValueError:
                        pass
                parsed_time = None
                try:
                    parsed_time = datetime.strptime(time_part, "%I:%M %p").time()
                except ValueError:
                    pass
                if parsed_date and parsed_time:
                    delivery_dt = datetime.combine(parsed_date, parsed_time)
                    order_details['delivery_iso'] = delivery_dt.isoformat(timespec='minutes')
                    order_details['delivery_date'] = parsed_date.isoformat()
                    order_details['delivery_time_24h'] = parsed_time.strftime("%H:%M")


        # Extract delivery instructions
        instructions_elem = order_table.locator('text=Delivery Instructions').locator('../..').first
        if instructions_elem.count() > 0:
            instructions_text = instructions_elem.text_content()
            cleaned_instructions = clean_text(instructions_text.replace('Delivery Instructions', ''))
            order_details['delivery_instructions'] = cleaned_instructions
        
        # Extract items
        items = []
        item_rows = order_table.locator('tr.item-row')
        for i in range(item_rows.count()):
            row = item_rows.nth(i)
            
            # Extract quantity
            qty_cell = row.locator('.quantity').first
            qty = clean_text(qty_cell.text_content()) if qty_cell.count() > 0 else ''
            
            # Extract item description
            item_desc_cell = row.locator('td').nth(2)  # 3rd column contains item info
            item_desc = clean_text(item_desc_cell.text_content()) if item_desc_cell.count() > 0 else ''
            
            # Extract price
            price_cell = row.locator('.price').first
            price = clean_text(price_cell.text_content()) if price_cell.count() > 0 else ''
            
            if qty and item_desc and price:
                items.append({
                    'quantity': qty,
                    'description': item_desc,
                    'price': price
                })
        
        order_details['items'] = items
        
        # Extract pricing summary
        pricing = {}
        
        # Subtotal
        subtotal_elem = order_table.locator('text=Subtotal').locator('../..').locator('.charge-amount').first
        if subtotal_elem.count() > 0:
            pricing['subtotal'] = clean_text(subtotal_elem.text_content())
        
        # Service Fee
        service_fee_elem = order_table.locator('text=Service Fee').locator('../..').locator('.charge-amount').first
        if service_fee_elem.count() > 0:
            pricing['service_fee'] = clean_text(service_fee_elem.text_content())
        
        # Delivery
        delivery_fee_elem = order_table.locator('text=Delivery').locator('../..').locator('.charge-amount').first
        if delivery_fee_elem.count() > 0:
            pricing['delivery_fee'] = clean_text(delivery_fee_elem.text_content())
        
        # Tax
        tax_elem = order_table.locator('text=Tax').locator('../..').locator('.charge-amount').first
        if tax_elem.count() > 0:
            pricing['tax'] = clean_text(tax_elem.text_content())
        
        # Total
        total_elem = order_table.locator('.total-amount').first
        if total_elem.count() > 0:
            pricing['total'] = clean_text(total_elem.text_content())
        
        # Payment method
        payment_elem = order_table.locator('.payment-name').first
        if payment_elem.count() > 0:
            pricing['payment_method'] = clean_text(payment_elem.text_content())
        
        order_details['pricing'] = pricing
        
        # Extract number of people
        people_elem = order_table.locator('text=This order is for').locator('..').first
        if people_elem.count() > 0:
            people_text = people_elem.text_content()
            people_match = re.search(r'This order is for (\d+) people', people_text)
            if people_match:
                order_details['number_of_people'] = people_match.group(1)
                # Extract per person cost
                per_person_match = re.search(r'\$([0-9.]+) per person', people_text)
                if per_person_match:
                    order_details['cost_per_person'] = per_person_match.group(1)
        
        # Extract creation date
        footer_elem = order_table.locator('.footer').first
        if footer_elem.count() > 0:
            footer_text = footer_elem.text_content()
            created_match = re.search(r'created (.+)', footer_text)
            if created_match:
                order_details['created_date'] = created_match.group(1).strip()
        
    except Exception as e:
        print(f"Error extracting order details: {e}")
    
    return order_details

def get_total_rows(page):
    """
    Get the total number of rows in the data grid
    """
    iframe = page.frame_locator('iframe[name="frame"]')
    
    # Wait for grid to load
    grid = iframe.locator(".dx-datagrid-content").first
    grid.wait_for(state="visible", timeout=20000)
    
    # Count all data rows
    rows = iframe.locator("tbody tr.dx-data-row")
    return rows.count()

def _pager(iframe):
    return iframe.locator(".dx-datagrid-pager .dx-pages, .dx-pager .dx-pages").first

def get_current_page_info(page):
    iframe = page.frame_locator('iframe[name="frame"]')
    pages_root = _pager(iframe)
    pages_root.wait_for(state="visible", timeout=10000)
    btns = pages_root.locator(".dx-page")
    btns.first.wait_for(state="visible", timeout=10000)

    current_btn = pages_root.locator(".dx-page.dx-selection, .dx-page[aria-selected='true']").first
    current_page = int(re.sub(r"[^\d]", "", current_btn.inner_text().strip()))

    labels = [int(btns.nth(i).inner_text().strip()) for i in range(btns.count())
              if btns.nth(i).inner_text().strip().isdigit()]
    total_pages = max(labels) if labels else None
    return current_page, total_pages


def navigate_to_next_page(page):
    """
    Clicks the next numeric page button.
    Returns True if navigated, False if already on last page.
    """
    iframe = page.frame_locator('iframe[name="frame"]')

    cur, total = get_current_page_info(page)
    if total is not None and cur >= total:
        return False  # already on last page

    # remember first row text to detect change
    first_row = iframe.locator("tbody tr.dx-data-row").first
    first_row.wait_for(state="visible", timeout=10000)
    before = first_row.inner_text()

    target_num = cur + 1
    pages_root = _pager(iframe)
    target_btn = pages_root.locator(f".dx-page:has-text('{target_num}')").first
    target_btn.wait_for(state="visible", timeout=10000)
    target_btn.click()

    # wait for selection to move OR the first row content to change
    try:
        pages_root.locator(f".dx-page.dx-selection:has-text('{target_num}'), .dx-page[aria-selected='true']:has-text('{target_num}')").wait_for(timeout=10000)
    except:
        pass  # not all themes use dx-selection immediately

    # ensure rows refreshed
    first_row.wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(300)  # tiny settle
    try:
        # row content changed means new page loaded
        first_row.wait_for(state="visible", timeout=10000)
        if first_row.inner_text() != before:
            return True
    except:
        pass

    # also try a lightweight network idle wait as fallback
    page.wait_for_load_state("networkidle", timeout=5000)
    return True

def save_orders_to_file(orders, output_dir: Path, format='json'):
    """
    Save extracted orders to file
    
    Args:
        orders: List of order dictionaries
        output_dir: Directory to save file
        format: 'json', 'csv', or 'excel'
    """
    import json
    from datetime import datetime
    
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if format == 'json':
        filename = f"orders_export_{timestamp}.json"
        filepath = output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(orders, f, indent=2, ensure_ascii=False)
    
    elif format == 'csv':
        filename = f"orders_export_{timestamp}.csv"
        filepath = output_dir / filename
        
        # Flatten the nested structure for CSV
        flattened_orders = []
        for order in orders:
            flat_order = {}
            
            # Basic fields
            basic_fields = ['atg_order_id', 'po_id', 'vendor_name', 'delivery_time',
                            'delivery_date', 'delivery_time_24h', 'delivery_info',
                            'delivery_instructions', 'created_date', '_page_number',
                            '_row_number', '_order_sequence', 'delivery_iso']
            
            for field in basic_fields:
                flat_order[field] = order.get(field, '')
            
            # Pricing fields
            if 'pricing' in order:
                pricing = order['pricing']
                for key, value in pricing.items():
                    flat_order[f'pricing_{key}'] = value
            
            # Items (concatenated)
            if 'items' in order:
                items_text = '; '.join([
                    f"{item.get('quantity', '')}x {item.get('description', '')} - {item.get('price', '')}"
                    for item in order['items']
                ])
                flat_order['items'] = items_text
            
            flattened_orders.append(flat_order)
        
        df = pd.DataFrame(flattened_orders)
        df.to_csv(filepath, index=False)
    
    elif format == 'excel':
        filename = f"orders_export_{timestamp}.xlsx"
        filepath = output_dir / filename
        
        # Create separate sheets for orders and items
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # Orders sheet (basic info)
            orders_data = []
            for order in orders:
                order_row = {
                    'ATG_Order_ID': order.get('atg_order_id', ''),
                    'PO_ID': order.get('po_id', ''),
                    'Vendor': order.get('vendor_name', ''),
                    'Delivery_Time_Raw': order.get('delivery_time', ''),   # original text
                    'Delivery_Date': order.get('delivery_date', ''),       # YYYY-MM-DD
                    'Delivery_Time_24h': order.get('delivery_time_24h', ''),  # HH:MM
                    'Delivery_ISO': order.get('delivery_iso', ''),         # 2025-09-11T15:00
                    'Number_of_People': order.get('number_of_people', ''),
                    'Cost_per_Person': order.get('cost_per_person', ''),
                    'Total': order.get('pricing', {}).get('total', ''),
                    'Created_Date': order.get('created_date', ''),
                    'Page_Number': order.get('_page_number', ''),
                    'Row_Number': order.get('_row_number', ''),
                }
                orders_data.append(order_row)
            
            orders_df = pd.DataFrame(orders_data)
            orders_df.to_excel(writer, sheet_name='Orders', index=False)
            
            # Items sheet (detailed items)
            items_data = []
            for order in orders:
                order_id = order.get('atg_order_id', '')
                if 'items' in order:
                    for item in order['items']:
                        item_row = {
                            'ATG_Order_ID': order_id,
                            'Quantity': item.get('quantity', ''),
                            'Description': item.get('description', ''),
                            'Price': item.get('price', ''),
                        }
                        items_data.append(item_row)
            
            if items_data:
                items_df = pd.DataFrame(items_data)
                items_df.to_excel(writer, sheet_name='Items', index=False)
    
    print(f"Orders saved to: {filepath}")
    return filepath

def click_row_action_robust(page, action_text: str, *, row_index: int = 1, max_retries: int = 3):
    """
    More robust version of click_row_action with better error handling and retries
    """
    iframe = page.frame_locator('iframe[name="frame"]')
    
    for attempt in range(max_retries):
        try:
            print(f"  Attempt {attempt + 1} to click row {row_index} action...")
            
            # Wait for grid to be stable
            grid = iframe.locator(".dx-datagrid-content").first
            grid.wait_for(state="visible", timeout=20000)
            
            # Add a small delay to ensure grid is fully rendered
            page.wait_for_timeout(1000)
            
            # Get the specific row with more robust waiting
            row = iframe.locator("tbody tr.dx-data-row").nth(row_index - 1)
            row.wait_for(state="visible", timeout=15000)
            
            # Scroll row into view
            row.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            
            # Find and click the three-dots button with multiple selectors
            three_dots_selectors = [
                ".dx-dropdownbutton[title='Available actions'] .dx-dropdownbutton-action",
                ".dx-dropdownbutton .dx-dropdownbutton-action",
                "[title='Available actions']"
            ]
            
            three_dots = None
            for selector in three_dots_selectors:
                try:
                    button = row.locator(selector).first
                    if button.count() > 0 and button.is_visible():
                        three_dots = button
                        break
                except:
                    continue
            
            if three_dots is None:
                raise Exception(f"Could not find three-dots button in row {row_index}")
            
            # Click the button
            three_dots.click(force=True)
            
            # Wait for dropdown with more patience
            page.wait_for_timeout(1500)
            
            # Try multiple approaches to find the dropdown
            dropdown_found = False
            dropdown_selectors = [
                '.dx-overlay-content[role="dialog"][aria-label="Dropdown"]:visible',
                '.dx-overlay-content[role="dialog"]:visible',
                '.dx-dropdownbutton-content:visible',
                '.dx-list-items:visible'
            ]
            
            for dropdown_selector in dropdown_selectors:
                try:
                    dropdown = iframe.locator(dropdown_selector).first
                    if dropdown.count() > 0 and dropdown.is_visible():
                        # Try to find and click the action
                        action_selectors = [
                            f".dx-list-item:has-text('{action_text}')",
                            f"*:has-text('{action_text}')"
                        ]
                        
                        for action_selector in action_selectors:
                            try:
                                action_option = dropdown.locator(action_selector).first
                                if action_option.count() > 0 and action_option.is_visible():
                                    action_option.click()
                                    dropdown_found = True
                                    break
                            except:
                                continue
                        
                        if dropdown_found:
                            break
                except:
                    continue
            
            if dropdown_found:
                print(f"  ✓ Successfully clicked action for row {row_index}")
                return True
            else:
                raise Exception("Dropdown menu not found or action not clickable")
                
        except Exception as e:
            print(f"  ✗ Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                # Wait before retry and try to clear any open dialogs
                page.wait_for_timeout(2000)
                try:
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(1000)
                except:
                    pass
    
    return False

def extract_and_display_order_details_robust(page, action_text: str = "View Order Text", row_index: int = 1):
    """
    More robust version with better error handling and recovery
    """
    try:
        # First, ensure we're in a clean state
        try:
            page.keyboard.press('Escape')
            page.wait_for_timeout(500)
        except:
            pass
        
        # Click the row action to open popup with retries
        if not click_row_action_robust(page, action_text, row_index=row_index):
            return None
        
        # Wait longer for popup to fully load
        page.wait_for_timeout(3000)
        
        # Extract the details
        order_details = extract_order_details(page)
        
        # Only print details if extraction was successful
        if order_details and order_details.get('atg_order_id'):
            print("=== ORDER DETAILS ===")
            print(f"ATG Order ID: {order_details.get('atg_order_id', 'N/A')}")
            print(f"PO ID: {order_details.get('po_id', 'N/A')}")
            print(f"Vendor: {order_details.get('vendor_name', 'N/A')}")
            print(f"Delivery Time: {order_details.get('delivery_time', 'N/A')}")
            print(f"Number of People: {order_details.get('number_of_people', 'N/A')}")
            print(f"Cost per Person: ${order_details.get('cost_per_person', 'N/A')}")
            
            if 'items' in order_details and order_details['items']:
                print("\n=== ITEMS ===")
                for i, item in enumerate(order_details['items'], 1):
                    print(f"{i}. Qty: {item['quantity']} - {item['description']} - {item['price']}")
            
            if 'pricing' in order_details and order_details['pricing']:
                pricing = order_details['pricing']
                print("\n=== PRICING ===")
                print(f"Subtotal: {pricing.get('subtotal', 'N/A')}")
                print(f"Service Fee: {pricing.get('service_fee', 'N/A')}")
                print(f"Delivery: {pricing.get('delivery_fee', 'N/A')}")
                print(f"Tax: {pricing.get('tax', 'N/A')}")
                print(f"Total: {pricing.get('total', 'N/A')}")
                print(f"Payment: {pricing.get('payment_method', 'N/A')}")
            
            print(f"\nCreated: {order_details.get('created_date', 'N/A')}")
        
        # Close the popup with multiple attempts
        close_popup_robust(page)
        
        return order_details
        
    except Exception as e:
        print(f"Error in extract_and_display_order_details_robust: {e}")
        # Try to close any open popups
        try:
            close_popup_robust(page)
        except:
            pass
        return None

def close_popup_robust(page, max_attempts: int = 3):
    """
    More robust popup closing with multiple attempts and methods
    """
    iframe = page.frame_locator('iframe[name="frame"]')
    
    for attempt in range(max_attempts):
        try:
            # Try multiple close button selectors
            close_selectors = [
                '.dx-closebutton:visible',
                '.dx-button[aria-label="Close"]:visible',
                '.dx-icon-close:visible',
                '.dx-popup-title .dx-button:visible',
                '.dx-overlay-content[role="dialog"] .dx-closebutton'
            ]
            
            popup_closed = False
            for selector in close_selectors:
                try:
                    close_button = iframe.locator(selector).first
                    if close_button.count() > 0 and close_button.is_visible():
                        close_button.click()
                        page.wait_for_timeout(1000)
                        popup_closed = True
                        break
                except:
                    continue
            
            if popup_closed:
                break
            
            # If no close button worked, try Escape key
            page.keyboard.press('Escape')
            page.wait_for_timeout(1000)
            
            # Check if popup is still visible
            try:
                popup = iframe.locator('#ordercopy').first
                if popup.count() == 0 or not popup.is_visible():
                    break
            except:
                break
                
        except Exception as e:
            print(f"Close attempt {attempt + 1} failed: {e}")
            if attempt == max_attempts - 1:
                # Final attempt with multiple escape presses
                for _ in range(3):
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(500)

def extract_all_orders_improved(page, max_orders=None, start_from_row=1, delay_between_orders=2):
    """
    Improved version with better error handling and delays
    """
    all_orders = []
    orders_processed = 0
    current_page = 1
    
    print("Starting to extract all orders...")
    
    while True:
        print(f"\n=== Processing Page {current_page} ===")
        
        # Get current page info
        page_num, total_pages = get_current_page_info(page)
        if total_pages:
            print(f"Page {page_num} of {total_pages}")
        
        # Get total rows on current page with retry
        total_rows = None
        for attempt in range(3):
            try:
                total_rows = get_total_rows(page)
                break
            except:
                print(f"Failed to get row count, attempt {attempt + 1}")
                page.wait_for_timeout(2000)
        
        if total_rows is None:
            print("Could not determine number of rows, skipping page")
            break
            
        print(f"Found {total_rows} orders on this page")
        
        # Determine which rows to process on this page
        start_row = start_from_row if current_page == 1 else 1
        
        # Process each row on current page
        for row_index in range(start_row, total_rows + 1):
            if max_orders and orders_processed >= max_orders:
                print(f"\nReached maximum orders limit: {max_orders}")
                return all_orders
            
            print(f"Processing order {orders_processed + 1} (Page {current_page}, Row {row_index})")
            
            try:
                # Extract order details with improved function
                order_details = extract_and_display_order_details_robust(
                    page, 
                    "View Order Text", 
                    row_index=row_index
                )
                
                if order_details and order_details.get('atg_order_id'):
                    # Add metadata
                    order_details['_page_number'] = current_page
                    order_details['_row_number'] = row_index
                    order_details['_order_sequence'] = orders_processed + 1
                    
                    all_orders.append(order_details)
                    orders_processed += 1
                    
                    print(f"✓ Successfully extracted order {order_details.get('atg_order_id', 'N/A')}")
                else:
                    print(f"✗ Failed to extract details for row {row_index}")
                    
            except Exception as e:
                print(f"✗ Error processing row {row_index}: {e}")
                continue
            
            # # Add delay between orders to avoid overwhelming the server
            # if row_index < total_rows:  # Don't delay after last row
            #     print(f"  Waiting {delay_between_orders}s before next order...")
            #     page.wait_for_timeout(delay_between_orders * 1000)
        
        # Try to navigate to next page
        print(f"\nAttempting to navigate to next page...")
        if navigate_to_next_page(page):
            current_page += 1
            start_from_row = 1
            # Add delay between pages
            page.wait_for_timeout(3000)
        else:
            print("No more pages to process")
            break
    
    print(f"\n=== EXTRACTION COMPLETE ===")
    print(f"Total orders extracted: {len(all_orders)}")
    return all_orders

# Updated main function
def main(headless: bool, preview_rows: int, out_dir: Path):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.goto(LOGIN_URL)

        login(page, LOGINID, PW)
        go_to_view_orders(page)

        # Wait for page to load
        page.wait_for_load_state("networkidle")
        time.sleep(5)  # Longer initial wait

        # Extract all orders with improved function
        all_orders = extract_all_orders_improved(
            page, 
            max_orders=5,  # Start with smaller number for testing
            start_from_row=1,
            delay_between_orders=3  # Increase delay between orders
        )
        
        # Save to file
        if all_orders:
            save_orders_to_file(all_orders, out_dir, format='excel')
            save_orders_to_file(all_orders, out_dir, format='json')
            
            print(f"\nSUMMARY:")
            print(f"Extracted {len(all_orders)} orders")
            print(f"Files saved to: {out_dir}")
        else:
            print("No orders were extracted")

        browser.close()

if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--categories", nargs="*", help="Names of categories to scrape")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--preview-rows", type=int, default=5, help="Rows to print from the exported sheet")
    parser.add_argument("--out-dir", type=Path, default=Path("downloads"), help="Directory to save the exported file")
    args = parser.parse_args()
    main(args.headless, args.preview_rows, args.out_dir)