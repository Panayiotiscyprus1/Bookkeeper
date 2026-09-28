"""Web pages. Each menu button maps to one route; routes only call services."""
from flask import Blueprint, render_template, request, redirect, url_for, flash

from money import to_cents
from models import (db, Employee, Customer, Vendor, Part, Invoice, PurchaseOrder,
                    PayrollRun, ExpenseAccount, BillPayment, JournalEntry,
                    set_setting, current_date)
import ledger
from ledger import BusinessError
from services import purchasing, operations
from services.purchasing import finished_goods, buildable_units, bom_parts

bp = Blueprint("main", __name__)

US_STATES_HINT = "2-letter code, e.g. IL"


def field(name, label, type="text", required=False, value="", options=None, hint="", step=None):
    return dict(name=name, label=label, type=type, required=required, value=value,
                options=options, hint=hint, step=step)


def run_action(fn, success, redirect_to):
    """Run a service call; show business-rule errors to the user instead of crashing."""
    try:
        result = fn()
    except BusinessError as e:
        db.session.rollback()
        flash(str(e), "error")
        return None
    except (ValueError, TypeError):
        db.session.rollback()
        flash("Please check the numbers you entered.", "error")
        return None
    flash(success(result) if callable(success) else success, "ok")
    return redirect(redirect_to)


# ---------------------------------------------------------------- menu

@bp.route("/")
def menu():
    bs = ledger.balance_sheet()
    return render_template("menu.html", bs=bs, fg=finished_goods(),
                           buildable=buildable_units())


# ---------------------------------------------------------------- employees

@bp.route("/employees")
def employees():
    return render_template("employees.html", employees=Employee.query.order_by(Employee.last_name).all())


@bp.route("/employees/add", methods=["GET", "POST"])
def add_employee():
    fields = [field("first_name", "First name", required=True),
              field("last_name", "Last name", required=True),
              field("address1", "Address 1"), field("address2", "Address 2"),
              field("city", "City"), field("state", "State", hint=US_STATES_HINT),
              field("zipcode", "Zip code"),
              field("ssn", "Social Security Number", hint="Stored locally; shown masked in lists"),
              field("filing_status", "Federal filing status (W-4 Step 1c)", "select",
                    options=[("single", "Single or Married filing separately"),
                             ("married", "Married filing jointly"),
                             ("hoh", "Head of household")]),
              field("state_allowances", "Illinois allowances (IL-W-4 line 1)", "number", value="0"),
              field("salary", "Annual salary ($)", "number", required=True, step="0.01")]
    if request.method == "POST":
        f = request.form

        def add():
            if not f.get("first_name") or not f.get("last_name"):
                raise BusinessError("First and last name are required.")
            salary = to_cents(f["salary"])
            if salary <= 0:
                raise BusinessError("Salary must be positive.")
            db.session.add(Employee(first_name=f["first_name"], last_name=f["last_name"],
                                    address1=f.get("address1", ""), address2=f.get("address2", ""),
                                    city=f.get("city", ""), state=f.get("state", "").upper()[:2],
                                    zipcode=f.get("zipcode", ""), ssn=f.get("ssn", ""),
                                    filing_status=f.get("filing_status", "single"),
                                    state_allowances=int(f.get("state_allowances") or 0),
                                    annual_salary=salary))
            db.session.commit()
        resp = run_action(add, "Employee added.", url_for("main.employees"))
        if resp:
            return resp
    return render_template("form.html", title="Add Employee", fields=fields,
                           submit="Add Employee", back=url_for("main.employees"))


# ---------------------------------------------------------------- customers

@bp.route("/customers")
def customers():
    return render_template("customers.html", customers=Customer.query.order_by(Customer.id).all())


@bp.route("/customers/add", methods=["GET", "POST"])
def add_customer():
    fields = [field("company", "Company name", required=True),
              field("contact_first", "Point of contact: first name"),
              field("contact_last", "Point of contact: last name"),
              field("address1", "Address 1"), field("address2", "Address 2"),
              field("city", "City"), field("state", "State", hint=US_STATES_HINT),
              field("zipcode", "Zip code"),
              field("unit_price", "Price per truck ($)", "number", value="2.50", step="0.01")]
    if request.method == "POST":
        f = request.form

        def add():
            if not f.get("company"):
                raise BusinessError("Company name is required.")
            price = float(f.get("unit_price") or 2.5)
            if price <= 0:
                raise BusinessError("Price must be positive.")
            db.session.add(Customer(company=f["company"], contact_first=f.get("contact_first", ""),
                                    contact_last=f.get("contact_last", ""),
                                    address1=f.get("address1", ""), address2=f.get("address2", ""),
                                    city=f.get("city", ""), state=f.get("state", "").upper()[:2],
                                    zipcode=f.get("zipcode", ""), unit_price=price))
            db.session.commit()
        resp = run_action(add, "Customer added.", url_for("main.customers"))
        if resp:
            return resp
    return render_template("form.html", title="Add Customer", fields=fields,
                           submit="Add Customer", back=url_for("main.customers"))


# ---------------------------------------------------------------- vendors

@bp.route("/vendors")
def vendors():
    return render_template("vendors.html", parts=Part.query.order_by(Part.id).all())


@bp.route("/vendors/add", methods=["GET", "POST"])
def add_vendor():
    fields = [field("company", "Company name", required=True),
              field("part", "Part supplied", required=True),
              field("unit_price", "Price per unit ($)", "number", required=True, step="0.0001"),
              field("qty_per_unit", "Quantity used per truck (0 = not in bill of materials)",
                    "number", value="0"),
              field("reorder_point", "Reorder point (units)", "number", value="0"),
              field("address1", "Address 1"), field("address2", "Address 2"),
              field("city", "City"), field("state", "State", hint=US_STATES_HINT),
              field("zipcode", "Zip code")]
    if request.method == "POST":
        f = request.form

        def add():
            if not f.get("company") or not f.get("part"):
                raise BusinessError("Company and part are required.")
            price = float(f["unit_price"])
            if price <= 0:
                raise BusinessError("Price must be positive.")
            v = Vendor(company=f["company"], address1=f.get("address1", ""),
                       address2=f.get("address2", ""), city=f.get("city", ""),
                       state=f.get("state", "").upper()[:2], zipcode=f.get("zipcode", ""))
            db.session.add(v)
            db.session.add(Part(name=f["part"], vendor=v, unit_price=price,
                                qty_per_unit=int(f.get("qty_per_unit") or 0),
                                reorder_point=int(f.get("reorder_point") or 0)))
            db.session.commit()
        resp = run_action(add, "Vendor added.", url_for("main.vendors"))
        if resp:
            return resp
    return render_template("form.html", title="Add Vendor", fields=fields,
                           submit="Add Vendor", back=url_for("main.vendors"))


# ---------------------------------------------------------------- payroll

@bp.route("/pay-employee", methods=["GET", "POST"])
def pay_employee():
    emps = Employee.query.order_by(Employee.last_name).all()
    if request.method == "POST":
        resp = run_action(
            lambda: operations.pay_employee(request.form["employee_id"], request.form.get("bonus") or 0),
            lambda run: f"Paid {run.employee.name}: net ${run.net / 100:,.2f}, "
                        f"withholding ${run.withholding / 100:,.2f}.",
            url_for("main.payroll"))
        if resp:
            return resp
    previews = {e.id: operations.preview_paycheck(e) for e in emps}
    return render_template("pay_employee.html", employees=emps, previews=previews,
                           employer_taxes=operations.employer_taxes_enabled())


@bp.route("/payroll")
def payroll():
    runs = PayrollRun.query.order_by(PayrollRun.id).all()
    return render_template("payroll.html", runs=runs,
                           total_net=sum(r.net for r in runs),
                           total_withholding=sum(r.withholding for r in runs),
                           total_gross=sum(r.gross for r in runs))


# ---------------------------------------------------------------- inventory / production

@bp.route("/inventory")
def inventory():
    parts = Part.query.order_by(Part.id).all()
    fg = finished_goods()
    return render_template("inventory.html", parts=parts, fg=fg,
                           parts_total=sum(p.value for p in parts),
                           cost_per_unit=purchasing.bom_cost_per_unit(),
                           buildable=buildable_units())


@bp.route("/build", methods=["GET", "POST"])
def build():
    if request.method == "POST":
        resp = run_action(lambda: purchasing.build_units(request.form["units"]),
                          lambda cost: f"Built {int(request.form['units']):,} trucks "
                                       f"(${cost / 100:,.2f} moved from parts to finished goods).",
                          url_for("main.inventory"))
        if resp:
            return resp
    return render_template("build.html", buildable=buildable_units(), parts=bom_parts())


# ---------------------------------------------------------------- invoices

@bp.route("/invoices/new", methods=["GET", "POST"])
def create_invoice():
    if request.method == "POST":
        resp = run_action(
            lambda: operations.create_invoice(request.form["customer_id"], request.form["units"]),
            lambda inv: f"Invoice #{inv.id} created: {inv.quantity:,} trucks to "
                        f"{inv.customer.company} for ${inv.total / 100:,.2f} (due at month-end).",
            url_for("main.invoices"))
        if resp:
            return resp
    return render_template("invoice_form.html", customers=Customer.query.order_by(Customer.id).all(),
                           fg=finished_goods())


@bp.route("/invoices")
def invoices():
    invs = Invoice.query.order_by(Invoice.id).all()
    return render_template("invoices.html", invoices=invs,
                           total_sales=sum(i.total for i in invs),
                           total_cogs=sum(i.cogs for i in invs))


# ---------------------------------------------------------------- purchase orders

@bp.route("/po/new", methods=["GET", "POST"])
def create_po():
    if request.method == "POST":
        f = request.form
        resp = run_action(
            lambda: purchasing.create_po(f["part_id"], f["qty"], receive_now=bool(f.get("receive_now")),
                                         qty_received=f.get("qty_received") or None),
            lambda po: f"PO #{po.id} created for {po.qty_ordered:,} {po.part.name}"
                       + (f"; received {po.qty_received:,}, billed ${po.total / 100:,.2f} (payable at month-end)."
                          if po.received_date else " (waiting for delivery)."),
            url_for("main.purchase_orders"))
        if resp:
            return resp
    return render_template("po_form.html", parts=Part.query.order_by(Part.id).all())


@bp.route("/po")
def purchase_orders():
    return render_template("purchase_orders.html",
                           pos=PurchaseOrder.query.order_by(PurchaseOrder.id).all())


@bp.route("/po/<int:po_id>/receive", methods=["POST"])
def receive_po(po_id):
    resp = run_action(lambda: purchasing.receive_open_po(po_id, request.form["qty_received"]),
                      lambda po: f"PO #{po.id} received: {po.qty_received:,} {po.part.name}.",
                      url_for("main.purchase_orders"))
    return resp or redirect(url_for("main.purchase_orders"))


# ---------------------------------------------------------------- expenses / bills

@bp.route("/expenses")
def expenses():
    exps = ExpenseAccount.query.order_by(ExpenseAccount.id).all()
    rows = [dict(exp=e, monthly=e.annual_budget / 12, paid=sum(p.amount for p in operations.payments_this_year(e)),
                 paid_this_month=operations.paid_this_month(e), next_amount=operations.next_bill_amount(e))
            for e in exps]
    return render_template("expenses.html", rows=rows,
                           total_annual=sum(e.annual_budget for e in exps))


@bp.route("/bills/pay", methods=["POST"])
def pay_bill():
    if request.form.get("expense_id") == "all":
        resp = run_action(operations.pay_all_bills, lambda n: f"Paid {n} monthly bills.",
                          url_for("main.paid_expenses"))
    else:
        resp = run_action(lambda: operations.pay_bill(request.form["expense_id"]),
                          lambda p: f"Paid {p.expense.name}: ${p.amount / 100:,.2f}.",
                          url_for("main.paid_expenses"))
    return resp or redirect(url_for("main.expenses"))


@bp.route("/bills")
def paid_expenses():
    pays = BillPayment.query.order_by(BillPayment.id).all()
    return render_template("paid_expenses.html", payments=pays, total=sum(p.amount for p in pays))


# ---------------------------------------------------------------- statements

@bp.route("/balance-sheet")
def balance_sheet():
    return render_template("balance_sheet_page.html", bs=ledger.balance_sheet())


@bp.route("/income-statement")
def income_statement():
    return render_template("income_statement_page.html", inc=ledger.income_statement())


@bp.route("/cash-flow")
def cash_flow():
    return render_template("cash_flow.html", cf=ledger.cash_flow(), bs=ledger.balance_sheet())


@bp.route("/statements")
def statements():
    """All three statements on one printable page."""
    return render_template("statements.html", bs=ledger.balance_sheet(),
                           inc=ledger.income_statement(), cf=ledger.cash_flow())


# ---------------------------------------------------------------- journal & before/after

@bp.route("/journal")
def journal():
    entries = JournalEntry.query.order_by(JournalEntry.id.desc()).all()
    return render_template("journal.html", entries=entries)


@bp.route("/journal/<int:entry_id>")
def before_after(entry_id):
    entry = db.get_or_404(JournalEntry, entry_id)
    before_id = entry_id - 1
    return render_template("before_after.html", entry=entry,
                           bs_before=ledger.balance_sheet(before_id), bs_after=ledger.balance_sheet(entry_id),
                           inc_before=ledger.income_statement(before_id),
                           inc_after=ledger.income_statement(entry_id))


# ---------------------------------------------------------------- testing features

@bp.route("/testing", methods=["GET"])
def testing():
    open_ar = sum(i.total for i in Invoice.query.filter(Invoice.paid_date.is_(None)))
    open_ap = sum(p.total for p in PurchaseOrder.query.filter(PurchaseOrder.received_date.isnot(None),
                                                               PurchaseOrder.paid_date.is_(None)))
    return render_template("testing.html", open_ar=open_ar, open_ap=open_ap,
                           employer_taxes=operations.employer_taxes_enabled(),
                           close_date=operations.month_end(current_date()))


@bp.route("/testing/close", methods=["POST"])
def close_month():
    f = request.form
    resp = run_action(
        lambda: operations.month_end_close(run_payroll=bool(f.get("run_payroll")),
                                           pay_bills=bool(f.get("pay_bills"))),
        lambda r: f"Closed {r['close_date']:%B %Y}: collected ${r['collected'] / 100:,.2f}, "
                  f"paid vendors ${r['paid'] / 100:,.2f}"
                  + (f", ran {r['payrolls']} payroll(s)" if r["payrolls"] else "")
                  + (f", paid {r['bills']} bills" if r["bills"] else "")
                  + f". Current date is now {r['new_date']:%Y-%m-%d}.",
        url_for("main.menu"))
    return resp or redirect(url_for("main.testing"))


@bp.route("/testing/settings", methods=["POST"])
def save_settings():
    set_setting("employer_taxes", "1" if request.form.get("employer_taxes") else "0")
    db.session.commit()
    flash("Settings saved.", "ok")
    return redirect(url_for("main.testing"))


@bp.route("/testing/reset", methods=["POST"])
def reset():
    from seed import seed
    preset = request.form.get("preset", "fresh")
    seed(preset)
    flash("Books reset to " + ("the turn-in starting point (40,000 trucks in stock, Feb 1)."
                               if preset == "turnin" else "the initial conditions ($200,000 cash, Jan 1)."), "ok")
    return redirect(url_for("main.menu"))
