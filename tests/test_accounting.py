import pytest

import ledger
from ledger import BusinessError
from models import Customer, Part, Employee, ExpenseAccount, current_date
from services import operations, purchasing
from services.tax import compute_paycheck, federal_withholding, illinois_withholding

D = 100  # cents per dollar


# ---------------------------------------------------------------- 2026 tax math

def test_monthly_paycheck_150k_single():
    c = compute_paycheck(12_500 * D, periods=12)
    # Pub 15-T: (150,000 - 8,600) = 141,400 -> 17,966 + 24% x 28,200 = 24,734 / 12
    assert c.federal == 2_061_17
    assert c.state == 618_75          # 4.95% x 12,500, zero IL allowances
    assert c.social_security == 775_00
    assert c.medicare == 181_25
    assert c.net == 8_863_83


def test_illinois_allowance_reduces_withholding():
    assert illinois_withholding(12_500 * D, 12, allowances=1) == 606_68


def test_social_security_stops_at_wage_base():
    c = compute_paycheck(12_500 * D, ytd_wages_cents=180_000 * D)
    assert c.social_security == 279_00   # only 4,500 left under the $184,500 base


def test_additional_medicare_over_200k():
    c = compute_paycheck(12_500 * D, ytd_wages_cents=195_000 * D)
    assert c.medicare == 181_25 + 67_50   # 0.9% on the 7,500 above $200,000


def test_low_wage_no_federal():
    assert federal_withholding(1_000 * D, 12) == 0


# ---------------------------------------------------------------- turn-in activities

def statements():
    return ledger.balance_sheet(), ledger.income_statement()


def test_turnin_three_transactions(turnin_app):
    bs0, inc0 = statements()
    assert bs0["cash"] == 177_200 * D and bs0["inventory"] == 22_800 * D
    assert inc0["sales"] == 0 and inc0["net_income"] == 0 and bs0["net_worth"] == 200_000 * D

    # 1) sale for $50,000 on net-30: receivable, not cash
    smith = Customer.query.filter_by(company="Smith Co.").one()
    operations.create_invoice(smith.id, 20_000)
    bs1, inc1 = statements()
    assert inc1["sales"] == 50_000 * D and bs1["ar"] == 50_000 * D
    assert inc1["cogs"] == 11_400 * D and bs1["cash"] == bs0["cash"]
    assert bs1["balanced"]

    # 2) purchase $20,000 of inventory on net-30: payable, not cash
    tank = Part.query.filter_by(name="Tank").one()
    purchasing.create_po(tank.id, 200_000)
    bs2, inc2 = statements()
    assert bs2["ap"] == 20_000 * D and bs2["inventory"] == bs1["inventory"] + 20_000 * D
    assert bs2["cash"] == bs1["cash"] and inc2 == inc1
    assert bs2["balanced"]

    # 3) one payroll period: full gross leaves cash
    operations.pay_employee(Employee.query.first().id)
    bs3, inc3 = statements()
    assert bs3["cash"] == bs2["cash"] - 12_500 * D
    assert inc3["payroll"] == 8_863_83 and inc3["payroll_withholding"] == 3_636_17
    assert bs3["balanced"]


# ---------------------------------------------------------------- full year

def test_full_year_scenario(app):
    """4 quarterly POs from 8 vendors, 12 invoices to 10 customers ($1M), 12 payrolls,
    $200k of bills, month-end closes. Books must balance and tie out every step."""
    customers = Customer.query.order_by(Customer.id).all()
    parts = purchasing.bom_parts()
    assert len(customers) == 10 and len({p.vendor_id for p in parts}) == 8
    lowest_cash = None
    for month in range(1, 13):
        assert current_date().month == month
        if month in (1, 4, 7, 10):
            for p in parts:
                purchasing.create_po(p.id, p.qty_per_unit * 100_000)
            purchasing.build_units(100_000)
        units = 33_337 if month == 12 else 33_333
        operations.create_invoice(customers[(month - 1) % 10].id, units)
        operations.month_end_close(run_payroll=True, pay_bills=True)
        bs = ledger.balance_sheet()
        assert bs["balanced"]
        lowest_cash = bs["cash"] if lowest_cash is None else min(lowest_cash, bs["cash"])

    inc, bs, cf = ledger.income_statement(), ledger.balance_sheet(), ledger.cash_flow()
    assert inc["sales"] == 1_000_000 * D
    assert inc["cogs"] == 228_000 * D                       # 400,000 trucks x $0.57
    assert inc["bills"] == 200_000 * D
    assert inc["payroll"] + inc["payroll_withholding"] == 150_000 * D
    assert inc["net_income"] == 422_000 * D
    assert bs["ar"] == 0 and bs["ap"] == 0 and bs["inventory"] == 0
    assert bs["net_worth"] == 200_000 * D + inc["net_income"]
    assert bs["cash"] == 622_000 * D == cf["ending_cash"]
    assert lowest_cash > 0
    assert operations.PayrollRun.query.count() == 12
    assert operations.Invoice.query.count() == 12
    assert current_date().year == 2027


# ---------------------------------------------------------------- business rules

def test_received_quantity_differs_from_ordered(app):
    labels = Part.query.filter_by(name="Box").one()
    po = purchasing.create_po(labels.id, 5_000, qty_received=5_471)
    assert po.total == 273_55                       # billed for what arrived, 5,471 x $0.05
    assert labels.qty_on_hand == 5_471
    assert ledger.balance_sheet()["ap"] == 273_55


def test_po_can_wait_for_delivery(app):
    axles = Part.query.filter_by(name="Axles").one()
    po = purchasing.create_po(axles.id, 1_000, receive_now=False)
    assert po.status == "Open" and ledger.balance_sheet()["ap"] == 0
    purchasing.receive_open_po(po.id, 900)
    assert po.total == 9_00 and axles.qty_on_hand == 900


def test_cannot_oversell_or_overbuild(app):
    with pytest.raises(BusinessError):
        operations.create_invoice(Customer.query.first().id, 1)
    with pytest.raises(BusinessError):
        purchasing.build_units(1)


def test_bill_once_per_month_and_exact_annual_total(app):
    prof = ExpenseAccount.query.filter_by(name="Professional Services").one()   # $14,000/yr
    operations.pay_bill(prof.id)
    with pytest.raises(BusinessError):
        operations.pay_bill(prof.id)
    for _ in range(11):
        operations.month_end_close()
        operations.pay_bill(prof.id)
    assert sum(p.amount for p in operations.payments_this_year(prof)) == 14_000 * D


def test_low_stock_warning(app):
    assert all(p.needs_reorder for p in purchasing.bom_parts())
    wheels = Part.query.filter_by(name="Wheels").one()
    purchasing.create_po(wheels.id, wheels.reorder_point)
    assert not wheels.needs_reorder
