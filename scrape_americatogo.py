#!/usr/bin/env python3
"""
AmericaToGo Order Scraper

Scrapes orders from AmericaToGo vendor portal and syncs them to Google Calendar.
Uses Playwright for web automation and integrates with existing Google Calendar client.
"""

import os
import re
import time
import json
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from html import unescape

import pandas as pd
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from core_types import Order, OrderItem
from gcalclient import GoogleCalendarClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
CATERING_SERVICE_PROVIDER = "ATG"
LOGINID = os.getenv(f"{CATERING_SERVICE_PROVIDER}_LOGINID")
PW = os.getenv(f"{CATERING_SERVICE_PROVIDER}_PW")
SITE = os.getenv(f"{CATERING_SERVICE_PROVIDER}_SITE")
LOGIN_URL = os.getenv(f"{CATERING_SERVICE_PROVIDER}_LOGIN_URL")
CALENDAR_ID = os.getenv("CALENDAR_ID")
CALENDAR_TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "America/Los_Angeles")
CALENDAR_WINDOW_DAYS = int(os.getenv("CALENDAR_WINDOW_DAYS", "365"))
CALENDAR_EVENT_DURATION = int(os.getenv("CALENDAR_EVENT_DURATION", "60"))

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Regex patterns
CITY_STATE_ZIP = re.compile(r',\s*[A-Z]{2}\s+\d{5}(-\d{4})?$')
PHONE_RE = re.compile(r'\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}')


class AmericaToGoScraper:
    """Main scraper class for AmericaToGo orders"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.page = None
        self.browser = None
        self.context = None
    
    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.new_page()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
    
    def login(self):
        """Login to AmericaToGo vendor portal"""
        logger.info("Logging in to AmericaToGo...")
        self.page.goto(LOGIN_URL)
        
        # Fill credentials
        self.page.fill('input[name="Email"]', LOGINID)
        self.page.fill('input[name="Password"]', PW)
        self.page.click('button[type="submit"]')
        
        # Wait for navigation
        self.page.wait_for_load_state("networkidle")
        
        # Verify login success
        current_url = self.page.url
        if 'Home/SignIn' not in current_url or 'VendorPortal' in current_url:
            logger.info("Login successful")
        else:
            logger.error("Login failed - still on login page")
            raise Exception("Login failed")
    
    def navigate_to_orders(self):
        """Navigate to the orders page"""
        logger.info("Navigating to orders page...")
        try:
            self.page.get_by_role("button", name="View Orders").click()
        except Exception:
            logger.info("Using fallback selector for View Orders")
            self.page.locator("button.navicon[data-title='View Orders']").click()
        
        self.page.wait_for_url(re.compile(r".*/VendorPortal/Orders.*"))
        logger.info(f"At Orders page: {self.page.url}")
        self.page.wait_for_load_state("networkidle")
    
    def get_total_rows(self):
        """Get total number of rows in the data grid"""
        iframe = self.page.frame_locator('iframe[name="frame"]')
        grid = iframe.locator(".dx-datagrid-content").first
        grid.wait_for(state="visible", timeout=20000)
        rows = iframe.locator("tbody tr.dx-data-row")
        return rows.count()
    
    def get_current_page_info(self):
        """Get current page number and total pages"""
        iframe = self.page.frame_locator('iframe[name="frame"]')
        pages_root = iframe.locator(".dx-datagrid-pager .dx-pages, .dx-pager .dx-pages").first
        pages_root.wait_for(state="visible", timeout=10000)
        
        btns = pages_root.locator(".dx-page")
        btns.first.wait_for(state="visible", timeout=10000)
        
        current_btn = pages_root.locator(".dx-page.dx-selection, .dx-page[aria-selected='true']").first
        current_page = int(re.sub(r"[^\d]", "", current_btn.inner_text().strip()))
        
        labels = [int(btns.nth(i).inner_text().strip()) for i in range(btns.count())
                  if btns.nth(i).inner_text().strip().isdigit()]
        total_pages = max(labels) if labels else None
        
        return current_page, total_pages
    
    def navigate_to_next_page(self):
        """Navigate to next page. Returns True if successful, False if on last page"""
        iframe = self.page.frame_locator('iframe[name="frame"]')
        
        cur, total = self.get_current_page_info()
        if total is not None and cur >= total:
            return False
        
        # Remember first row to detect change
        first_row = iframe.locator("tbody tr.dx-data-row").first
        first_row.wait_for(state="visible", timeout=10000)
        before = first_row.inner_text()
        
        # Click next page
        target_num = cur + 1
        pages_root = iframe.locator(".dx-datagrid-pager .dx-pages, .dx-pager .dx-pages").first
        target_btn = pages_root.locator(f".dx-page:has-text('{target_num}')").first
        target_btn.wait_for(state="visible", timeout=10000)
        target_btn.click()
        
        # Wait for page change
        try:
            pages_root.locator(f".dx-page.dx-selection:has-text('{target_num}'), .dx-page[aria-selected='true']:has-text('{target_num}')").wait_for(timeout=10000)
        except:
            pass
        
        # Verify content changed
        first_row.wait_for(state="visible", timeout=10000)
        self.page.wait_for_timeout(300)
        
        try:
            if first_row.inner_text() != before:
                return True
        except:
            pass
        
        self.page.wait_for_load_state("networkidle", timeout=5000)
        return True
    
    def click_row_action(self, action_text: str, row_index: int = 1, max_retries: int = 3):
        """Click action button for a specific row with retries"""
        iframe = self.page.frame_locator('iframe[name="frame"]')
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"Attempt {attempt + 1} to click row {row_index} action...")
                
                # Wait for grid stability
                grid = iframe.locator(".dx-datagrid-content").first
                grid.wait_for(state="visible", timeout=20000)
                self.page.wait_for_timeout(1000)
                
                # Get the row
                row = iframe.locator("tbody tr.dx-data-row").nth(row_index - 1)
                row.wait_for(state="visible", timeout=15000)
                row.scroll_into_view_if_needed()
                self.page.wait_for_timeout(500)
                
                # Find and click three-dots button
                button = row.locator(".dx-dropdownbutton[title='Available actions'] .dx-dropdownbutton-action").first
                if not (button.count() > 0 and button.is_visible()):
                    raise Exception(f"Could not find three-dots button in row {row_index}")
                
                button.click(force=True)
                self.page.wait_for_timeout(1500)
                
                # Click the action in dropdown
                dropdown = iframe.locator('.dx-overlay-content[role="dialog"][aria-label="Dropdown"]:visible').first
                dropdown.wait_for(state="visible", timeout=8000)
                
                action = dropdown.locator(f".dx-list-item:has-text('{action_text}'):visible").first
                action.wait_for(state="visible", timeout=5000)
                
                try:
                    action.click(timeout=4000)
                except Exception:
                    action.scroll_into_view_if_needed()
                    action.click(force=True, timeout=4000)
                
                logger.debug(f"✓ Clicked '{action_text}' for row {row_index}")
                return True
                
            except Exception as e:
                logger.debug(f"✗ Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    self.page.wait_for_timeout(2000)
                    try:
                        self.page.keyboard.press('Escape')
                        self.page.wait_for_timeout(1000)
                    except:
                        pass
        
        return False
    
    def close_popup(self, max_attempts: int = 3):
        """Close popup with multiple attempts"""
        iframe = self.page.frame_locator('iframe[name="frame"]')
        
        for attempt in range(max_attempts):
            try:
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
                            self.page.wait_for_timeout(1000)
                            popup_closed = True
                            break
                    except:
                        continue
                
                if popup_closed:
                    break
                
                # Try Escape key
                self.page.keyboard.press('Escape')
                self.page.wait_for_timeout(1000)
                
                # Check if popup is gone
                try:
                    popup = iframe.locator('#ordercopy').first
                    if popup.count() == 0 or not popup.is_visible():
                        break
                except:
                    break
                    
            except Exception as e:
                logger.debug(f"Close attempt {attempt + 1} failed: {e}")
                if attempt == max_attempts - 1:
                    for _ in range(3):
                        self.page.keyboard.press('Escape')
                        self.page.wait_for_timeout(500)
    
    def clean_text(self, text):
        """Clean and normalize text content"""
        if not text:
            return text
        
        # Insert spaces where needed
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)       # aB -> a B
        text = re.sub(r'([A-Za-z])(\d)', r'\1 \2', text)       # A1 -> A 1
        text = re.sub(r'(\d)([A-Za-z])', r'\1 \2', text)       # 1A -> 1 A
        text = re.sub(r'\b(AM|PM)([A-Z][a-z])', r'\1 \2', text)  # PMThu -> PM Thu
        text = re.sub(r'([0-9])([a-z]+@)', r'\1 \2', text)     # 9email@...
        text = re.sub(r'([a-z])(\(\d)', r'\1 \2', text)        # a(123
        return re.sub(r'\s+', ' ', text.strip())
    
    def extract_address_from_html(self, delivery_html: str) -> str:
        """Extract clean address from delivery HTML"""
        # Convert <br> to newlines and remove other tags
        txt = re.sub(r'<br\s*/?>', '\n', delivery_html, flags=re.I)
        txt = re.sub(r'<[^>]+>', ' ', txt)
        txt = unescape(txt)
        
        # Normalize whitespace per line
        raw_lines = [l for l in (s.strip() for s in txt.splitlines()) if l]
        lines = [re.sub(r'\s+', ' ', l).strip(' ,') for l in raw_lines if l]
        
        # Remove email/phone lines
        lines = [l for l in lines if '@' not in l and not PHONE_RE.search(l)]
        
        # Find city/state/zip line
        city_idx = next((i for i, l in enumerate(lines) if CITY_STATE_ZIP.search(l)), None)
        if city_idx is None:
            # Fallback: use last up to 3 lines
            window = lines[-3:] if len(lines) >= 3 else lines
        else:
            # Take 2 lines before city + city line
            start_idx = max(0, city_idx - 2)
            window = lines[start_idx:city_idx] + [lines[city_idx]]
        
        # Keep only last 3 elements
        window = window[-3:]
        
        # Clean up and join
        window = [re.sub(r'\s*,\s*,', ', ', l).strip(' ,') for l in window]
        return ", ".join(window)
    
    def extract_order_details(self):
        """Extract order details from the popup"""
        iframe = self.page.frame_locator('iframe[name="frame"]')
        
        # Wait for order table
        order_table = iframe.locator('#ordercopy').first
        order_table.wait_for(state="visible", timeout=15000)
        
        order_details = {}
        
        try:
            # Extract ATG Order ID
            order_id_elem = order_table.locator('text=ATG Order ID:').locator('..').first
            if order_id_elem.count() > 0:
                order_id_text = order_id_elem.text_content()
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
            
            # Extract vendor name
            vendor_elem = order_table.locator('.important').first
            if vendor_elem.count() > 0:
                order_details['vendor_name'] = self.clean_text(vendor_elem.text_content())
            
            # Extract delivery information
            delivery_section = order_table.locator('text=Deliver to').locator('..').first
            if delivery_section.count() > 0:
                try:
                    delivery_html = delivery_section.inner_html()
                    order_details['address'] = self.extract_address_from_html(delivery_html)
                    
                    # Clean delivery info
                    delivery_html = re.sub(r'<br\s*/?>', ' ', delivery_html)
                    delivery_text = re.sub(r'<[^>]+>', '', delivery_html)
                    delivery_text = unescape(delivery_text)
                    order_details['delivery_info'] = self.clean_text(delivery_text)
                except:
                    delivery_text = delivery_section.text_content()
                    order_details['delivery_info'] = self.clean_text(delivery_text)
                
                # Extract customer name
                cust_name = None
                try:
                    m = re.search(
                        r'Deliver to.*?<span[^>]*class="[^"]*\bimportant\b[^"]*"[^>]*>\s*(.*?)\s*</span>',
                        delivery_html,
                        flags=re.IGNORECASE | re.DOTALL
                    )
                    if m:
                        cust_name = self.clean_text(m.group(1))
                except:
                    pass
                
                # Fallback: first part of delivery info
                if not cust_name:
                    di = order_details.get('delivery_info', '')
                    for sep in [",", "|", "\n"]:
                        if sep in di:
                            cust_name = self.clean_text(di.split(sep)[0])
                            break
                    if not cust_name:
                        cust_name = self.clean_text(di)
                
                order_details['customer_name'] = (cust_name or 'Customer')[:80]
            
            # Extract delivery time
            delivery_time_section = order_table.locator('text=Deliver at').locator('..').first
            if delivery_time_section.count() > 0:
                try:
                    dt_html = delivery_time_section.inner_html()
                    dt_text = re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', ' ', dt_html))
                    dt_text = unescape(dt_text)
                except:
                    dt_text = delivery_time_section.text_content()
                
                cleaned = self.clean_text(dt_text.replace('Deliver at', ''))
                order_details['delivery_time_raw'] = cleaned
                
                # Parse time and date
                m = re.search(r'(?P<time>\d{1,2}:\d{2}\s*[AP]M)\s+(?P<date>.+)', cleaned)
                if m:
                    time_part = m.group('time').strip().upper()
                    date_part = m.group('date').strip()
                    
                    # Parse date
                    parsed_date = None
                    for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
                        try:
                            parsed_date = datetime.strptime(date_part, fmt).date()
                            break
                        except ValueError:
                            pass
                    
                    # Parse time
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
                cleaned_instructions = self.clean_text(instructions_text.replace('Delivery Instructions', ''))
                order_details['delivery_instructions'] = cleaned_instructions
            
            # Extract items
            items = []
            item_rows = order_table.locator('tr.item-row')
            for i in range(item_rows.count()):
                row = item_rows.nth(i)
                
                qty_cell = row.locator('.quantity').first
                qty = self.clean_text(qty_cell.text_content()) if qty_cell.count() > 0 else ''
                
                item_desc_cell = row.locator('td').nth(2)
                item_desc = self.clean_text(item_desc_cell.text_content()) if item_desc_cell.count() > 0 else ''
                
                price_cell = row.locator('.price').first
                price = self.clean_text(price_cell.text_content()) if price_cell.count() > 0 else ''
                
                if qty and item_desc and price:
                    items.append(OrderItem(
                        quantity=qty,
                        description=item_desc,
                        price=price
                    ))
            
            order_details['items'] = items
            
            # Extract pricing
            pricing = {}
            pricing_fields = [
                ('Subtotal', 'subtotal'),
                ('Service Fee', 'service_fee'),
                ('Delivery', 'delivery_fee'),
                ('Tax', 'tax')
            ]
            
            for field_text, field_key in pricing_fields:
                elem = order_table.locator(f'text={field_text}').locator('../..').locator('.charge-amount').first
                if elem.count() > 0:
                    pricing[field_key] = self.clean_text(elem.text_content())
            
            # Total
            total_elem = order_table.locator('.total-amount').first
            if total_elem.count() > 0:
                pricing['total'] = self.clean_text(total_elem.text_content())
            
            # Payment method
            payment_elem = order_table.locator('.payment-name').first
            if payment_elem.count() > 0:
                pricing['payment_method'] = self.clean_text(payment_elem.text_content())
            
            order_details['pricing'] = pricing
            
            # Extract number of people and cost per person
            people_elem = order_table.locator('text=This order is for').locator('..').first
            if people_elem.count() > 0:
                people_text = people_elem.text_content()
                people_match = re.search(r'This order is for (\d+) people', people_text)
                if people_match:
                    order_details['number_of_people'] = people_match.group(1)
                    
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
            logger.error(f"Error extracting order details: {e}")
        
        return order_details
    
    def extract_order_from_row(self, row_index: int):
        """Extract order details from a specific row"""
        try:
            # Clear any open dialogs
            try:
                self.page.keyboard.press('Escape')
                self.page.wait_for_timeout(500)
            except:
                pass
            
            # Click row action to open popup
            if not self.click_row_action("View Order Text", row_index=row_index):
                return None
            
            # Wait for popup to load
            self.page.wait_for_timeout(3000)
            
            # Extract details
            order_details = self.extract_order_details()
            
            # Close popup
            self.close_popup()
            
            return order_details
            
        except Exception as e:
            logger.error(f"Error extracting order from row {row_index}: {e}")
            try:
                self.close_popup()
            except:
                pass
            return None
    
    def extract_all_orders(self, max_orders=None, start_from_row=1):
        """Extract all orders from all pages"""
        all_orders = []
        orders_processed = 0
        current_page = 1
        
        logger.info("Starting order extraction...")
        
        while True:
            logger.info(f"Processing Page {current_page}")
            
            # Get page info
            page_num, total_pages = self.get_current_page_info()
            if total_pages:
                logger.info(f"Page {page_num} of {total_pages}")
            
            # Get total rows with retry
            total_rows = None
            for attempt in range(3):
                try:
                    total_rows = self.get_total_rows()
                    break
                except:
                    logger.warning(f"Failed to get row count, attempt {attempt + 1}")
                    self.page.wait_for_timeout(2000)
            
            if total_rows is None:
                logger.warning("Could not determine number of rows, skipping page")
                break
            
            logger.info(f"Found {total_rows} orders on this page")
            
            # Process rows
            start_row = start_from_row if current_page == 1 else 1
            
            for row_index in range(start_row, total_rows + 1):
                if max_orders and orders_processed >= max_orders:
                    logger.info(f"Reached maximum orders limit: {max_orders}")
                    return all_orders
                
                logger.info(f"Processing order {orders_processed + 1} (Page {current_page}, Row {row_index})")
                
                order_details = self.extract_order_from_row(row_index)
                
                if order_details and order_details.get('atg_order_id'):
                    # Convert to Order object
                    order = Order(
                        atg_order_id=order_details.get('atg_order_id', ''),
                        po_id=order_details.get('po_id', ''),
                        vendor_name=order_details.get('vendor_name', ''),
                        customer_name=order_details.get('customer_name', ''),
                        address=order_details.get('address', ''),
                        delivery_info=order_details.get('delivery_info', ''),
                        delivery_instructions=order_details.get('delivery_instructions', ''),
                        delivery_time_raw=order_details.get('delivery_time_raw', ''),
                        delivery_iso=order_details.get('delivery_iso', ''),
                        delivery_date=order_details.get('delivery_date', ''),
                        delivery_time_24h=order_details.get('delivery_time_24h', ''),
                        number_of_people=order_details.get('number_of_people', ''),
                        cost_per_person=order_details.get('cost_per_person', ''),
                        pricing=order_details.get('pricing', {}),
                        items=order_details.get('items', []),
                        page_number=current_page,
                        row_number=row_index,
                        order_sequence=orders_processed + 1
                    )
                    
                    all_orders.append(order)
                    orders_processed += 1
                    
                    logger.info(f"✓ Successfully extracted order {order.atg_order_id}")
                else:
                    logger.warning(f"✗ Failed to extract details for row {row_index}")
            
            # Navigate to next page
            logger.info("Attempting to navigate to next page...")
            if self.navigate_to_next_page():
                current_page += 1
                start_from_row = 1
                self.page.wait_for_timeout(3000)
            else:
                logger.info("No more pages to process")
                break
        
        logger.info(f"Extraction complete. Total orders: {len(all_orders)}")
        return all_orders


def save_orders_to_file(orders, output_dir: Path, format='json'):
    """Save orders to file in specified format"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if format == 'json':
        filename = f"orders_export_{timestamp}.json"
        filepath = output_dir / filename
        
        # Convert orders to dict format
        orders_data = []
        for order in orders:
            order_dict = order.to_dict() if hasattr(order, 'to_dict') else {
                'atg_order_id': order.atg_order_id,
                'po_id': order.po_id,
                'vendor_name': order.vendor_name,
                'customer_name': order.customer_name,
                'address': order.address,
                'delivery_info': order.delivery_info,
                'delivery_instructions': order.delivery_instructions,
                'delivery_time_raw': order.delivery_time_raw,
                'delivery_iso': order.delivery_iso,
                'delivery_date': order.delivery_date,
                'delivery_time_24h': order.delivery_time_24h,
                'number_of_people': order.number_of_people,
                'cost_per_person': order.cost_per_person,
                'pricing': order.pricing,
                'items': [{'quantity': item.quantity, 'description': item.description, 'price': item.price} 
                         for item in (order.items or [])],
                'page_number': order.page_number,
                'row_number': order.row_number,
                'order_sequence': order.order_sequence
            }
            orders_data.append(order_dict)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(orders_data, f, indent=2, ensure_ascii=False)
    
    elif format == 'excel':
        filename = f"orders_export_{timestamp}.xlsx"
        filepath = output_dir / filename
        
        # Create separate sheets for orders and items
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # Orders sheet
            orders_data = [order.to_flat_row() for order in orders]
            orders_df = pd.DataFrame(orders_data)
            orders_df.to_excel(writer, sheet_name='Orders', index=False)
            
            # Items sheet
            items_data = []
            for order in orders:
                items_data.extend(order.items_rows())
            
            if items_data:
                items_df = pd.DataFrame(items_data)
                items_df.to_excel(writer, sheet_name='Items', index=False)
    
    logger.info(f"Orders saved to: {filepath}")
    return filepath


def build_calendar_event_body(order: Order, platform: str = "ATG",
                             tz_name: str = CALENDAR_TIMEZONE,
                             default_duration_minutes: int = CALENDAR_EVENT_DURATION) -> dict:
    """Build Google Calendar event body from order data"""
    
    identifier = f"{platform}-{order.atg_order_id}" if order.atg_order_id else None
    if not identifier or not order.delivery_iso:
        return None
    
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Los_Angeles")
    
    try:
        start_dt = datetime.fromisoformat(order.delivery_iso)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=tz)
    except Exception:
        return None
    
    end_dt = start_dt + timedelta(minutes=default_duration_minutes)
    
    # Build title
    customer = order.customer_name or "Customer"
    pax = order.number_of_people or ""
    total = order.pricing.get("total", "") if order.pricing else ""
    
    title = f"{identifier} - {customer}"
    if pax:
        title += f" - {pax} pax"
    if total:
        title += f" - {total}"
    
    # Build description
    description_lines = [
        f"<b>Identifier:</b> {identifier}",
        f"<b>PO ID:</b> {order.po_id or 'N/A'}",
        "=" * 40,
        f"<b>Delivery Instructions:</b>\n{order.delivery_instructions or 'N/A'}",
        "=" * 40
    ]
    
    if order.items:
        description_lines.append("<b>Items:</b>")
        for item in order.items:
            description_lines.append(f"  - {item.quantity} x {item.description} — {item.price}")
        description_lines.append("=" * 40)
    
    if order.pricing:
        description_lines.append("<b>Pricing:</b>")
        for k, v in order.pricing.items():
            description_lines.append(f"  - {k}: {v}")
    
    return {
        "summary": title,
        "location": order.address or "",
        "description": "\n".join(description_lines),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": tz.key},
        "extendedProperties": {"private": {"order_key": identifier}},
    }


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Scrape AmericaToGo orders")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--max-orders", type=int, default=5, help="Maximum number of orders to extract")
    parser.add_argument("--out-dir", type=Path, default=DOWNLOADS_DIR, help="Output directory")
    parser.add_argument("--no-calendar", action="store_true", help="Skip Google Calendar sync")
    
    args = parser.parse_args()
    
    # Extract orders
    with AmericaToGoScraper(headless=args.headless) as scraper:
        scraper.login()
        scraper.navigate_to_orders()
        
        orders = scraper.extract_all_orders(
            max_orders=args.max_orders,
            start_from_row=1
        )
        
        if orders:
            # Save to files
            save_orders_to_file(orders, args.out_dir, format='json')
            save_orders_to_file(orders, args.out_dir, format='excel')
            
            # Sync to Google Calendar
            if not args.no_calendar and CALENDAR_ID:
                logger.info("Syncing orders to Google Calendar...")
                calendar_client = GoogleCalendarClient()
                changes = calendar_client.upsert_events(
                    calendar_id=CALENDAR_ID,
                    orders=orders,
                    body_builder=lambda order: build_calendar_event_body(order, "ATG"),
                    days_before=CALENDAR_WINDOW_DAYS,
                    days_after=CALENDAR_WINDOW_DAYS,
                    tz_name=CALENDAR_TIMEZONE
                )
                logger.info(f"Upserted {len(changes)} calendar events")
            
            logger.info(f"Successfully processed {len(orders)} orders")
        else:
            logger.warning("No orders were extracted")


if __name__ == "__main__":
    main()
