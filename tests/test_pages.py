"""Click through every page and form the way a user would."""
import re

import ledger
from models import Customer, Part


def test_every_page_renders(turnin_app):
    client = turnin_app.test_client()
    pages = ["/", "/employees", "/employees/add", "/customers", "/customers/add", "/vendors",
             "/vendors/add", "/pay-employee", "/payroll", "/inventory", "/build",
             "/invoices/new", "/invoices", "/po/new", "/po", "/expenses", "/bills",
             "/balance-sheet", "/income-statement", "/cash-flow", "/statements", "/journal",
             "/journal/1", "/testing"]
    for page in pages:
        resp = client.get(page)
        assert resp.status_code == 200, page


def test_forms_post_and_update_statements(turnin_app):
    c = turnin_app.test_client()
    smith = Customer.query.filter_by(company="Smith Co.").one()
    tank = Part.query.filter_by(name="Tank").one()

    r = c.post("/invoices/new", data={"customer_id": smith.id, "units": "20000"}, follow_redirects=True)
    assert b"Invoice #1 created" in r.data
    r = c.post("/po/new", data={"part_id": tank.id, "qty": "200000", "receive_now": "1"},
               follow_redirects=True)
    assert b"billed $20,000.00" in r.data
    r = c.post("/pay-employee", data={"employee_id": 1, "bonus": "0"}, follow_redirects=True)
    assert b"net $8,863.83" in r.data
    r = c.get("/balance-sheet")
    assert b"balanced" in r.data and b"$50,000.00" in r.data

    # business-rule errors are shown, not crashes
    r = c.post("/invoices/new", data={"customer_id": smith.id, "units": "999999"})
    assert r.status_code == 200 and b"complete units in stock" in r.data
    r = c.post("/build", data={"units": "abc"})
    assert r.status_code == 200 and b"check the numbers" in r.data

    # add master data
    r = c.post("/customers/add", data={"company": "We Sell Toys", "unit_price": "2.50"}, follow_redirects=True)
    assert b"We Sell Toys" in r.data
    r = c.post("/vendors/add", data={"company": "Warning Labels 4 All", "part": "Warning Labels",
                                     "unit_price": "0.02", "qty_per_unit": "0"}, follow_redirects=True)
    assert b"Warning Labels 4 All" in r.data
    r = c.post("/employees/add", data={"first_name": "James", "last_name": "Jones", "salary": "50000",
                                       "ssn": "987654321", "state_allowances": "2"}, follow_redirects=True)
    assert b"Jones" in r.data and b"***-**-4321" in r.data

    # month-end close collects the receivable and pays the vendor
    r = c.post("/testing/close", data={}, follow_redirects=True)
    assert b"collected $50,000.00" in r.data and b"paid vendors $20,000.00" in r.data
    bs = ledger.balance_sheet()
    assert bs["ar"] == 0 and bs["ap"] == 0 and bs["balanced"]
    assert ledger.cash_flow()["ending_cash"] == bs["cash"]

    # before/after page for the invoice shows both states
    r = c.get("/journal")
    ids = [int(i) for i in re.findall(rb'/journal/(\d+)"', r.data)]
    assert ids
    r = c.get(f"/journal/{max(ids)}")
    assert r.status_code == 200 and r.data.count(b"Balance check") == 2


def test_reset_to_fresh(turnin_app):
    c = turnin_app.test_client()
    c.post("/testing/reset", data={"preset": "fresh"})
    bs = ledger.balance_sheet()
    assert bs["cash"] == 200_000_00 and bs["inventory"] == 0
