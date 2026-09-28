"""Initial conditions for the toy truck business (ENG/TE 566 instructional guide, part 2-3).

Presets:
  fresh   - $200,000 owner investment on Jan 1 2026, master data loaded, no inventory.
  turnin  - fresh + one opening purchase of parts for 40,000 trucks, built into finished
            goods, vendors paid at the January close. Starts on Feb 1 with product in
            stock so the three turn-in transactions (sale, purchase, payroll) can run.
"""
from datetime import date

from money import to_cents
from models import (db, Account, Customer, Employee, ExpenseAccount, Part, Vendor,
                    FinishedGoods, set_setting)
import ledger

START_DATE = date(2026, 1, 1)
INITIAL_INVESTMENT = 200_000

# Bill of materials from the instructional guide: (part, qty per truck, unit cost, vendor)
BOM = [
    ("Wheels", 8, 0.01, "Wheels R Us", "12 Rubber Rd", "Akron", "OH", "44308"),
    ("Windshield Glass", 1, 0.05, "Acme Plastics", "88 Clearview Ave", "Toledo", "OH", "43604"),
    ("Interior", 1, 0.05, "Cozy Cabs Inc", "5 Upholstery Ln", "Peoria", "IL", "61602"),
    ("Tank", 1, 0.10, "Tank Works", "301 Mixer Blvd", "Joliet", "IL", "60432"),
    ("Axles", 4, 0.01, "Micro Axles", "44 Spindle St", "Rockford", "IL", "61101"),
    ("Cab", 1, 0.10, "Castings for U", "900 Foundry Way", "Gary", "IN", "46402"),
    ("Body", 1, 0.10, "Casting Man", "902 Foundry Way", "Gary", "IN", "46402"),
    ("Box", 1, 0.05, "Many Boxes", "17 Carton Ct", "Chicago", "IL", "60607"),
]
REORDER_TRUCKS = 35_000   # warn when a part covers fewer than ~1 month of sales

CUSTOMERS = ["Smith Co.", "Toys r Us", "Online Hobbies", "TowerHobbies", "Hobbytron",
             "Walmart", "Kmart", "Target", "Hobbytown", "Cars are Us"]
TRUCK_PRICE = 2.50

# 10 operating expense accounts, $200,000/year in total (salary and taxes excluded)
EXPENSES = [
    ("6100", "Rent", 48_000), ("6110", "Utilities", 18_000),
    ("6120", "Maintenance", 15_000), ("6130", "Insurance", 24_000),
    ("6140", "Marketing", 30_000), ("6150", "Travel", 12_000),
    ("6160", "Shipping", 24_000), ("6170", "Phone & Internet", 6_000),
    ("6180", "Office Supplies", 9_000), ("6190", "Professional Services", 14_000),
]


def seed(preset="fresh"):
    db.drop_all()
    db.create_all()
    for code, name, typ in ledger.BASE_ACCOUNTS:
        db.session.add(Account(code=code, name=name, type=typ))
    for code, name, annual in EXPENSES:
        acct = Account(code=code, name=name, type="expense")
        db.session.add(acct)
        db.session.add(ExpenseAccount(name=name, annual_budget=to_cents(annual), account=acct))
    for part, qty, cost, vendor, a1, city, st, zc in BOM:
        v = Vendor(company=vendor, address1=a1, city=city, state=st, zipcode=zc)
        db.session.add(v)
        db.session.add(Part(name=part, vendor=v, unit_price=cost, qty_per_unit=qty,
                            reorder_point=qty * REORDER_TRUCKS))
    for name in CUSTOMERS:
        db.session.add(Customer(company=name, unit_price=TRUCK_PRICE))
    db.session.add(Employee(first_name="John", last_name="Smith", address1="123 Front St",
                            city="Urbana", state="IL", zipcode="61801", ssn="123-45-6789",
                            filing_status="single", state_allowances=0,
                            annual_salary=to_cents(150_000)))
    db.session.add(FinishedGoods(id=1, qty_on_hand=0, value=0))
    set_setting("current_date", START_DATE.isoformat())
    set_setting("employer_taxes", "0")
    db.session.flush()
    cash = to_cents(INITIAL_INVESTMENT)
    ledger.post(START_DATE, "investment", "Initial owner investment",
                [(ledger.CASH, cash, 0), (ledger.OWNER_CAPITAL, 0, cash)],
                cf=("financing", "Owner investment"))
    db.session.commit()

    if preset == "turnin":
        from services.purchasing import create_po, build_units
        from services.operations import month_end_close
        opening_trucks = 40_000
        for p in Part.query.filter(Part.qty_per_unit > 0).order_by(Part.id):
            create_po(p.id, p.qty_per_unit * opening_trucks)
        build_units(opening_trucks)
        month_end_close()
