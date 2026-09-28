"""Sales (invoices), payroll, monthly bills and month-end close."""
import calendar
from datetime import date, timedelta

from money import to_cents, round_cents
from models import (db, Customer, Employee, ExpenseAccount, Invoice, PurchaseOrder,
                    PayrollRun, BillPayment, current_date, set_setting, get_setting)
import ledger
from ledger import BusinessError
from services.purchasing import finished_goods
from services.tax import compute_paycheck

PAY_PERIODS = 12   # monthly payroll


# ---------------------------------------------------------------- sales

def create_invoice(customer_id, units) -> Invoice:
    """Sale on net-30 terms: revenue + receivable now, cash at month-end close."""
    customer = db.session.get(Customer, int(customer_id))
    if customer is None:
        raise BusinessError("Unknown customer.")
    units = int(units)
    if units <= 0:
        raise BusinessError("Number of units must be positive.")
    fg = finished_goods()
    if units > fg.qty_on_hand:
        raise BusinessError(f"Only {fg.qty_on_hand:,} complete units in stock. "
                            "Build more units first.")
    total = to_cents(units * customer.unit_price)
    cogs = round_cents(fg.value * units / fg.qty_on_hand) if units < fg.qty_on_hand else fg.value
    fg.qty_on_hand -= units
    fg.value -= cogs
    inv = Invoice(date=current_date(), customer=customer, quantity=units,
                  unit_price=customer.unit_price, total=total, cogs=cogs)
    db.session.add(inv)
    db.session.flush()
    entry = ledger.post(inv.date, "invoice",
                        f"Invoice #{inv.id}: {units:,} trucks to {customer.company}",
                        [(ledger.AR, total, 0), (ledger.SALES, 0, total),
                         (ledger.COGS, cogs, 0), (ledger.FINISHED_GOODS, 0, cogs)])
    inv.entry_id = entry.id
    db.session.commit()
    return inv


# ---------------------------------------------------------------- payroll

def employer_taxes_enabled() -> bool:
    return get_setting("employer_taxes", "0") == "1"


def preview_paycheck(employee, bonus_cents=0):
    salary = round_cents(employee.annual_salary / PAY_PERIODS)
    year = current_date().year
    ytd = sum(r.gross for r in PayrollRun.query.filter_by(employee_id=employee.id)
              if r.date.year == year)
    check = compute_paycheck(salary + bonus_cents, ytd, PAY_PERIODS,
                             employee.filing_status, employee.state_allowances)
    return salary, check


def pay_employee(employee_id, bonus=0, on_date=None, commit=True) -> PayrollRun:
    """Pay one month of salary. Withholdings are remitted immediately, so the full
    gross leaves cash: net pay goes to the Payroll expense account and the taxes
    withheld go to the separate Payroll Withholding (tax) expense account."""
    emp = db.session.get(Employee, int(employee_id))
    if emp is None:
        raise BusinessError("Unknown employee.")
    bonus_cents = to_cents(bonus or 0)
    if bonus_cents < 0:
        raise BusinessError("Bonus cannot be negative.")
    salary, check = preview_paycheck(emp, bonus_cents)
    employer = (check.employer_ss + check.employer_medicare) if employer_taxes_enabled() else 0
    cash_out = check.gross + employer
    if cash_out > ledger.balances()[ledger.CASH]:
        raise BusinessError("Not enough cash to run this payroll.")
    run = PayrollRun(date=on_date or current_date(), employee=emp, gross=check.gross,
                     salary=salary, bonus=bonus_cents, federal=check.federal,
                     state=check.state, social_security=check.social_security,
                     medicare=check.medicare, employer_taxes=employer, net=check.net)
    db.session.add(run)
    db.session.flush()
    entry = ledger.post(run.date, "payroll",
                        f"Payroll #{run.id}: {emp.name} (net pay + taxes withheld)",
                        [(ledger.PAYROLL, check.net, 0),
                         (ledger.PAYROLL_WITHHOLDING, check.withholding, 0),
                         (ledger.EMPLOYER_TAXES, employer, 0),
                         (ledger.CASH, 0, cash_out)],
                        cf=("operating", "Payroll and payroll taxes"))
    run.entry_id = entry.id
    if commit:
        db.session.commit()
    return run


# ---------------------------------------------------------------- monthly bills

def payments_this_year(expense):
    year = current_date().year
    return [p for p in BillPayment.query.filter_by(expense_id=expense.id) if p.date.year == year]


def next_bill_amount(expense) -> int:
    """Annual budget spread over 12 bills; the rounding remainder lands in the last one,
    so 12 payments add up exactly to the annual budget."""
    n = len(payments_this_year(expense))
    if n >= 12:
        return 0
    a = expense.annual_budget
    return a * (n + 1) // 12 - a * n // 12


def paid_this_month(expense) -> bool:
    today = current_date()
    return any(p.date.month == today.month for p in payments_this_year(expense))


def pay_bill(expense_id, on_date=None, commit=True) -> BillPayment:
    exp = db.session.get(ExpenseAccount, int(expense_id))
    if exp is None:
        raise BusinessError("Unknown expense account.")
    if paid_this_month(exp):
        raise BusinessError(f"{exp.name} has already been paid this month.")
    amount = next_bill_amount(exp)
    if amount == 0:
        raise BusinessError(f"All 12 {exp.name} bills for the year are paid.")
    pay = BillPayment(date=on_date or current_date(), expense=exp, amount=amount)
    db.session.add(pay)
    db.session.flush()
    entry = ledger.post(pay.date, "bill", f"Paid monthly bill: {exp.name}",
                        [(exp.account.code, amount, 0), (ledger.CASH, 0, amount)],
                        cf=("operating", "Operating expenses (bills)"))
    pay.entry_id = entry.id
    if commit:
        db.session.commit()
    return pay


def pay_all_bills() -> int:
    paid = 0
    for exp in ExpenseAccount.query.order_by(ExpenseAccount.id):
        if not paid_this_month(exp) and next_bill_amount(exp) > 0:
            pay_bill(exp.id, commit=False)
            paid += 1
    db.session.commit()
    return paid


# ---------------------------------------------------------------- month-end close

def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def month_end_close(run_payroll=False, pay_bills=False) -> dict:
    """End of month: optionally run payroll and pay the fixed bills, then post all
    receivables to cash and pay all vendor bills (net 30, settled monthly even if
    not quite 30 days), then advance to the 1st of next month."""
    close_date = month_end(current_date())
    payrolls = bills = 0
    if run_payroll:
        for emp in Employee.query.order_by(Employee.id):
            pay_employee(emp.id, on_date=close_date, commit=False)
            payrolls += 1
    if pay_bills:
        for exp in ExpenseAccount.query.order_by(ExpenseAccount.id):
            if not paid_this_month(exp) and next_bill_amount(exp) > 0:
                pay_bill(exp.id, on_date=close_date, commit=False)
                bills += 1
    collected = paid = 0
    for inv in Invoice.query.filter(Invoice.paid_date.is_(None)).order_by(Invoice.id):
        inv.paid_date = close_date
        ledger.post(close_date, "collection",
                    f"Collected invoice #{inv.id} from {inv.customer.company}",
                    [(ledger.CASH, inv.total, 0), (ledger.AR, 0, inv.total)],
                    cf=("operating", "Collections from customers"))
        collected += inv.total
    for po in (PurchaseOrder.query.filter(PurchaseOrder.received_date.isnot(None),
                                          PurchaseOrder.paid_date.is_(None))
               .order_by(PurchaseOrder.id)):
        po.paid_date = close_date
        ledger.post(close_date, "vendor_payment",
                    f"Paid PO #{po.id} to {po.vendor.company}",
                    [(ledger.AP, po.total, 0), (ledger.CASH, 0, po.total)],
                    cf=("operating", "Payments to suppliers"))
        paid += po.total
    new_date = close_date + timedelta(days=1)
    set_setting("current_date", new_date.isoformat())
    db.session.commit()
    return dict(close_date=close_date, collected=collected, paid=paid, new_date=new_date,
                payrolls=payrolls, bills=bills)
