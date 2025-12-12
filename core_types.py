from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, date, time
from typing import List, Dict, Optional

@dataclass
class OrderItem:
    quantity: str
    description: str
    price: str

@dataclass
class Order:
    atg_order_id: str
    po_id: str = ""
    vendor_name: str = ""
    customer_name: str = ""
    address: str = ""                 # normalized multi-line address
    delivery_info: str = ""           # raw "Deliver to" text flattened
    delivery_instructions: str = ""
    delivery_time_raw: str = ""       # "3:00 PM Thursday, September 11, 2025"
    delivery_iso: str = ""            # "2025-09-11T15:00"
    delivery_date: str = ""           # "YYYY-MM-DD"
    delivery_time_24h: str = ""       # "HH:MM"
    number_of_people: str = ""
    cost_per_person: str = ""
    pricing: Dict[str,str] = None
    items: List[OrderItem] = None
    # provenance / metadata
    page_number: int = 0
    row_number: int = 0
    order_sequence: int = 0

    def to_flat_row(self) -> Dict[str,str]:
        """Flatten to a single-row dict for CSV/Excel Orders sheet."""
        p = self.pricing or {}
        return {
            "ATG_Order_ID": self.atg_order_id,
            "PO_ID": self.po_id,
            "Vendor": self.vendor_name,
            "Customer_Name": self.customer_name,
            "Address": self.address,
            "Delivery_Info": self.delivery_info,
            "Delivery_Instructions": self.delivery_instructions,
            "Delivery_Time_Raw": self.delivery_time_raw,
            "Delivery_Date": self.delivery_date,
            "Delivery_Time_24h": self.delivery_time_24h,
            "Delivery_ISO": self.delivery_iso,
            "Number_of_People": self.number_of_people,
            "Cost_per_Person": self.cost_per_person,
            "Subtotal": p.get("subtotal",""),
            "Service_Fee": p.get("service_fee",""),
            "Delivery_Fee": p.get("delivery_fee",""),
            "Tax": p.get("tax",""),
            "Total": p.get("total",""),
            "Payment_Method": p.get("payment_method",""),
            "Page_Number": str(self.page_number),
            "Row_Number": str(self.row_number),
            "Order_Sequence": str(self.order_sequence),
        }

    def items_rows(self) -> List[Dict[str,str]]:
        out = []
        for it in (self.items or []):
            out.append({
                "ATG_Order_ID": self.atg_order_id,
                "Quantity": it.quantity,
                "Description": it.description,
                "Price": it.price,
            })
        return out
