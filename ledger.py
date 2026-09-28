"""Double-entry ledger and financial statements.

post() is the only way money moves. Statements are pure queries over the journal,
optionally "as of" a given journal entry id, which is how the before/after views work.
"""
from sqlalchemy import func

from models import db, Account, JournalEntry, JournalLine

# Chart of accounts --------------------------------------------------------
CASH = "1000"
AR = "1100"
RAW_MATERIALS = "1200"
FINISHED_GOODS = "1210"
LAND = "1500"
EQUIPMENT = "1510"
FURNITURE = "1520"
AP = "2000"
NOTES_PAYABLE = "2100"
ACCRUALS = "2200"
MORTGAGE = "2500"
LONG_TERM_DEBT = "2600"
OWNER_CAPITAL = "3000"
SALES = "4000"
OTHER_INCOME = "4900"
COGS = "5000"
PAYROLL = "6000"              # net wages paid to employees
PAYROLL_WITHHOLDING = "6010"  # taxes withheld from wages (separate tax account)
EMPLOYER_TAXES = "6020"       # employer FICA match (only if enabled)
INCOME_TAX = "7000"

BASE_ACCOUNTS = [
    (CASH, "Cash", "asset"),
    (AR, "Accounts Receivable", "asset"),
    (RAW_MATERIALS, "Inventory - Raw Parts", "asset"),
    (FINISHED_GOODS, "Inventory - Finished Goods", "asset"),
    (LAND, "Land/Buildings", "asset"),
    (EQUIPMENT, "Equipment", "asset"),
    (FURNITURE, "Furniture and Fixtures", "asset"),
    (AP, "Accounts Payable", "liability"),
    (NOTES_PAYABLE, "Notes Payable", "liability"),
    (ACCRUALS, "Accruals", "liability"),
    (MORTGAGE, "Mortgage", "liability"),
    (LONG_TERM_DEBT, "Long Term Debt", "liability"),
    (OWNER_CAPITAL, "Owner's Capital", "equity"),
    (SALES, "Sales", "revenue"),
    (OTHER_INCOME, "Other Income", "revenue"),
    (COGS, "Cost of Goods Sold", "expense"),
    (PAYROLL, "Payroll", "expense"),
    (PAYROLL_WITHHOLDING, "Payroll Withholding", "expense"),
    (EMPLOYER_TAXES, "Employer Payroll Taxes", "expense"),
    (INCOME_TAX, "Income Taxes", "expense"),
]


class BusinessError(Exception):
    """Raised when a transaction would break a business rule (shown to the user)."""


def account(code) -> Account:
    acct = Account.query.filter_by(code=code).first()
    if acct is None:
        raise KeyError(f"Unknown account {code}")
    return acct


def post(date, kind, memo, lines, cf=None) -> JournalEntry:
    """Post a balanced journal entry.

    lines: list of (account_code, debit_cents, credit_cents)
    cf:    (section, label) for the cash flow statement if the entry moves cash
    """
    total_dr = sum(d for _, d, _ in lines)
    total_cr = sum(c for _, _, c in lines)
    if total_dr != total_cr:
        raise ValueError(f"Unbalanced entry '{memo}': debits {total_dr} != credits {total_cr}")
    if total_dr == 0:
        raise BusinessError("Transaction amount is zero.")
    entry = JournalEntry(date=date, kind=kind, memo=memo,
                         cf_section=cf[0] if cf else None, cf_label=cf[1] if cf else None)
    for code, dr, cr in lines:
        if dr or cr:
            entry.lines.append(JournalLine(account=account(code), debit=dr, credit=cr))
    db.session.add(entry)
    db.session.flush()
    return entry


# ---------------------------------------------------------------- balances

def balances(upto_entry_id=None) -> dict:
    """Return {account_code: natural-sign balance in cents}."""
    q = (db.session.query(Account.code, Account.type,
                          func.coalesce(func.sum(JournalLine.debit), 0),
                          func.coalesce(func.sum(JournalLine.credit), 0))
         .outerjoin(JournalLine, JournalLine.account_id == Account.id))
    if upto_entry_id is not None:
        q = q.filter((JournalLine.entry_id <= upto_entry_id) | (JournalLine.id.is_(None)))
    q = q.group_by(Account.code, Account.type)
    result = {}
    for code, typ, dr, cr in q:
        result[code] = (dr - cr) if typ in ("asset", "expense") else (cr - dr)
    for acct in Account.query.all():   # accounts with no lines in range
        result.setdefault(acct.code, 0)
    return result


def income_statement(upto_entry_id=None) -> dict:
    b = balances(upto_entry_id)
    from models import ExpenseAccount
    opex = [(e.name, b.get(e.account.code, 0)) for e in ExpenseAccount.query.order_by(ExpenseAccount.id)]
    sales = b[SALES]
    cogs = b[COGS]
    gross = sales - cogs
    payroll = b[PAYROLL]
    withholding = b[PAYROLL_WITHHOLDING]
    employer_taxes = b[EMPLOYER_TAXES]
    bills = sum(v for _, v in opex)
    total_expenses = payroll + withholding + employer_taxes + bills
    operating_income = gross - total_expenses
    other_income = b[OTHER_INCOME]
    income_taxes = b[INCOME_TAX]
    net_income = operating_income + other_income - income_taxes
    return dict(sales=sales, cogs=cogs, gross_profit=gross, payroll=payroll,
                payroll_withholding=withholding, employer_taxes=employer_taxes,
                opex=opex, bills=bills, total_expenses=total_expenses,
                operating_income=operating_income, other_income=other_income,
                income_taxes=income_taxes, net_income=net_income)


def balance_sheet(upto_entry_id=None) -> dict:
    b = balances(upto_entry_id)
    inc = income_statement(upto_entry_id)
    inventory = b[RAW_MATERIALS] + b[FINISHED_GOODS]
    current_assets = b[CASH] + b[AR] + inventory
    fixed_assets = b[LAND] + b[EQUIPMENT] + b[FURNITURE]
    total_assets = current_assets + fixed_assets
    current_liabilities = b[AP] + b[NOTES_PAYABLE] + b[ACCRUALS]
    long_term = b[MORTGAGE] + b[LONG_TERM_DEBT]
    total_liabilities = current_liabilities + long_term
    owner_capital = b[OWNER_CAPITAL]
    retained = inc["net_income"]
    net_worth = owner_capital + retained
    return dict(cash=b[CASH], ar=b[AR], raw=b[RAW_MATERIALS], finished=b[FINISHED_GOODS],
                inventory=inventory, current_assets=current_assets, land=b[LAND],
                equipment=b[EQUIPMENT], furniture=b[FURNITURE], fixed_assets=fixed_assets,
                total_assets=total_assets, ap=b[AP], notes_payable=b[NOTES_PAYABLE],
                accruals=b[ACCRUALS], current_liabilities=current_liabilities,
                mortgage=b[MORTGAGE], long_term_debt=b[LONG_TERM_DEBT],
                long_term=long_term, total_liabilities=total_liabilities,
                owner_capital=owner_capital, retained_earnings=retained,
                net_worth=net_worth, total_liab_and_worth=total_liabilities + net_worth,
                balanced=(total_assets == total_liabilities + net_worth))


CF_ORDER = {
    "operating": ["Collections from customers", "Payments to suppliers",
                  "Payroll and payroll taxes", "Operating expenses (bills)",
                  "Income taxes"],
    "investing": ["Purchase of fixed assets"],
    "financing": ["Owner investment", "Loans"],
}


def cash_flow(upto_entry_id=None) -> dict:
    """Direct-method cash flow: every cash movement grouped by its entry's label."""
    cash_acct = account(CASH)
    q = (db.session.query(JournalEntry.cf_section, JournalEntry.cf_label,
                          func.sum(JournalLine.debit - JournalLine.credit))
         .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
         .filter(JournalLine.account_id == cash_acct.id))
    if upto_entry_id is not None:
        q = q.filter(JournalEntry.id <= upto_entry_id)
    q = q.group_by(JournalEntry.cf_section, JournalEntry.cf_label)
    sections = {s: {label: 0 for label in labels} for s, labels in CF_ORDER.items()}
    for section, label, amount in q:
        section = section or "operating"
        label = label or "Other"
        sections.setdefault(section, {})
        sections[section][label] = sections[section].get(label, 0) + amount
    totals = {s: sum(v.values()) for s, v in sections.items()}
    net_change = sum(totals.values())
    return dict(sections=sections, totals=totals, beginning_cash=0,
                net_change=net_change, ending_cash=net_change)
