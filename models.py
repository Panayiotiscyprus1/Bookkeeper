"""Database models.

Design: every business event posts a balanced JournalEntry (double-entry bookkeeping).
The balance sheet, income statement and cash flow statement are *computed* from the
journal, never stored, so they are always consistent with the transaction history.
Money is stored as integer cents.
"""
from datetime import date

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=False)


# ---------------------------------------------------------------- ledger

class Account(db.Model):
    """Chart of accounts. type: asset | liability | equity | revenue | expense."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    type = db.Column(db.String(20), nullable=False)


class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    kind = db.Column(db.String(30), nullable=False)       # invoice, po_receipt, payroll, ...
    memo = db.Column(db.String(200), nullable=False)
    # Cash-flow classification for entries that move cash (direct method)
    cf_section = db.Column(db.String(20))                  # operating | investing | financing
    cf_label = db.Column(db.String(60))
    lines = db.relationship("JournalLine", backref="entry", cascade="all, delete-orphan")


class JournalLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    debit = db.Column(db.Integer, default=0, nullable=False)   # cents
    credit = db.Column(db.Integer, default=0, nullable=False)  # cents
    account = db.relationship("Account")


# ---------------------------------------------------------------- master data

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    address1 = db.Column(db.String(100), default="")
    address2 = db.Column(db.String(100), default="")
    city = db.Column(db.String(50), default="")
    state = db.Column(db.String(2), default="")
    zipcode = db.Column(db.String(10), default="")
    ssn = db.Column(db.String(11), default="")
    filing_status = db.Column(db.String(10), default="single")   # single | married | hoh
    state_allowances = db.Column(db.Integer, default=0)          # IL-W-4 line 1 allowances
    annual_salary = db.Column(db.Integer, nullable=False)        # cents

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def masked_ssn(self):
        digits = "".join(c for c in (self.ssn or "") if c.isdigit())
        return f"***-**-{digits[-4:]}" if len(digits) >= 4 else ""


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(100), nullable=False)
    contact_first = db.Column(db.String(50), default="")
    contact_last = db.Column(db.String(50), default="")
    address1 = db.Column(db.String(100), default="")
    address2 = db.Column(db.String(100), default="")
    city = db.Column(db.String(50), default="")
    state = db.Column(db.String(2), default="")
    zipcode = db.Column(db.String(10), default="")
    unit_price = db.Column(db.Float, nullable=False, default=2.50)  # $ per truck


class Vendor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(100), nullable=False)
    address1 = db.Column(db.String(100), default="")
    address2 = db.Column(db.String(100), default="")
    city = db.Column(db.String(50), default="")
    state = db.Column(db.String(2), default="")
    zipcode = db.Column(db.String(10), default="")
    parts = db.relationship("Part", backref="vendor")


class Part(db.Model):
    """A raw component. qty_per_unit > 0 means it is in the truck's bill of materials."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendor.id"), nullable=False)
    unit_price = db.Column(db.Float, nullable=False)       # $ per part from vendor
    qty_per_unit = db.Column(db.Integer, default=0)         # BOM quantity per truck
    reorder_point = db.Column(db.Integer, default=0)        # warn below this quantity
    qty_on_hand = db.Column(db.Integer, default=0)
    value = db.Column(db.Integer, default=0)                # cents, moving-average cost

    @property
    def needs_reorder(self):
        return self.qty_per_unit > 0 and self.qty_on_hand < self.reorder_point


class FinishedGoods(db.Model):
    """Single row holding completed trucks in stock."""
    id = db.Column(db.Integer, primary_key=True)
    qty_on_hand = db.Column(db.Integer, default=0)
    value = db.Column(db.Integer, default=0)                # cents


class ExpenseAccount(db.Model):
    """One of the 10 fixed operating expense accounts, paid as monthly bills."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    annual_budget = db.Column(db.Integer, nullable=False)   # cents
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    account = db.relationship("Account")


# ---------------------------------------------------------------- transactions / history

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Integer, nullable=False)           # cents
    cogs = db.Column(db.Integer, nullable=False)            # cents
    paid_date = db.Column(db.Date)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))
    customer = db.relationship("Customer")


class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey("part.id"), nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendor.id"), nullable=False)
    qty_ordered = db.Column(db.Integer, nullable=False)
    qty_received = db.Column(db.Integer)                    # None until received
    unit_price = db.Column(db.Float, nullable=False)
    total = db.Column(db.Integer, default=0)                # cents billed (= received x price)
    received_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))
    part = db.relationship("Part")
    vendor = db.relationship("Vendor")

    @property
    def status(self):
        if self.received_date is None:
            return "Open"
        return "Paid" if self.paid_date else "Received (payable)"


class PayrollRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    gross = db.Column(db.Integer, nullable=False)           # salary for period + bonus
    salary = db.Column(db.Integer, nullable=False)
    bonus = db.Column(db.Integer, default=0)
    federal = db.Column(db.Integer, nullable=False)
    state = db.Column(db.Integer, nullable=False)
    social_security = db.Column(db.Integer, nullable=False)
    medicare = db.Column(db.Integer, nullable=False)
    employer_taxes = db.Column(db.Integer, default=0)       # employer FICA match (optional)
    net = db.Column(db.Integer, nullable=False)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))
    employee = db.relationship("Employee")

    @property
    def withholding(self):
        return self.federal + self.state + self.social_security + self.medicare


class BillPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    expense_id = db.Column(db.Integer, db.ForeignKey("expense_account.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))
    expense = db.relationship("ExpenseAccount")


# ---------------------------------------------------------------- settings helpers

def get_setting(key, default=None):
    row = db.session.get(Setting, key)
    return row.value if row else default


def set_setting(key, value):
    row = db.session.get(Setting, key)
    if row:
        row.value = str(value)
    else:
        db.session.add(Setting(key=key, value=str(value)))


def current_date() -> date:
    return date.fromisoformat(get_setting("current_date", "2026-01-01"))
