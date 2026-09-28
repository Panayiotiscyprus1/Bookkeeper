# ENG/TE 566 Bookkeeper: Mr. Truck Inc.

A small bookkeeping program for a toy-truck manufacturer. Every business activity
(pay an employee, create an invoice, create a PO, build units, pay a bill, month-end close)
posts a balanced double-entry journal entry, and the **income statement, balance sheet and
cash flow statement are computed from the journal**, so they update automatically and
always balance. All history (payroll, invoices, POs, bills, journal) is kept for review,
and every page prints to PDF.

## Run it (macOS)

```bash
cd bookkeeper
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app app seed               # $200,000 cash on Jan 1 2026 (initial conditions)
flask --app app run                # open http://127.0.0.1:5000
```

`flask --app app seed --preset turnin` resets to the turn-in starting point instead
(see below). Both resets are also available in the app under **Month-End Close & Testing**.

Run the tests: `python -m pytest -q`

## Business setup (instructional guide, parts 2-3)

| Item | Value |
|---|---|
| Initial investment | $200,000 (owner's capital), Jan 1 2026 |
| Product | Toy truck, sold at $2.50 to 10 customers |
| Bill of materials | 8 wheels, 1 windshield glass, 1 interior, 1 tank, 4 axles, 1 cab, 1 body, 1 box = **$0.57/truck**, 8 vendors |
| Terms | Net 30. Sales become receivables, purchases become payables; both settle at the month-end close |
| Expenses | 10 accounts, $200,000/year, paid as monthly bills (12 bills add up exactly to the budget) |
| Employee | John Smith, $150,000/yr, single, paid monthly |
| Payroll taxes (2026) | Federal: IRS Pub 15-T percentage method. Illinois 4.95% (IL-W-4 allowance $2,925). Social Security 6.2% to $184,500. Medicare 1.45% (+0.9% over $200k) |

Monthly paycheck: gross $12,500.00 → federal $2,061.17, Illinois $618.75,
Social Security $775.00, Medicare $181.25 → **net $8,863.83** (withholding $3,636.17).

## Accounting rules

| Event | Debit | Credit |
|---|---|---|
| Owner investment | Cash | Owner's Capital |
| PO received (billed for qty actually received) | Inventory - Raw Parts | Accounts Payable |
| Build units | Inventory - Finished Goods | Inventory - Raw Parts |
| Invoice | Accounts Receivable; COGS | Sales; Inventory - Finished Goods |
| Payroll | Payroll (net pay); Payroll Withholding (taxes) | Cash |
| Monthly bill | Expense account | Cash |
| Month-end close | Cash; Accounts Payable | Accounts Receivable; Cash |

Inventory is valued at moving-average cost. Withheld taxes are treated as remitted
immediately. Employer FICA match is optional (off by default, switch in Testing).
No corporate income tax is booked.

## Producing the turn-in PDF

1. **Month-End Close & Testing → Reset → Turn-in starting point.** Parts for 40,000 trucks
   were bought, built and paid for in January; the date is Feb 1 2026.
   Starting statements: cash $177,200, finished goods $22,800, net worth $200,000.
2. Print **All Statements** (Cmd+P → Save as PDF). These are the initial conditions.
3. **Create Invoice:** Smith Co., 20,000 units = **$50,000 sale** (receivable).
4. **Create PO:** Tank, 200,000 units @ $0.10 = **$20,000 inventory purchase** (payable).
5. **Pay Employee:** John Smith, one monthly payroll.
6. For each transaction, open **Journal / Before & After** and print its page.
   It shows the income statement and balance sheet right before and right after it.
7. Combine the PDFs and submit with this folder's code (zip it).

## Files

```
app.py              app factory, `flask seed` command
models.py           database tables
ledger.py           chart of accounts, post(), balance sheet / income statement / cash flow
money.py            cents helpers and formatting
seed.py             initial conditions (fresh / turnin)
routes.py           one route per menu button
services/
  tax.py            2026 federal, Illinois, Social Security, Medicare
  purchasing.py     POs, receiving, build units
  operations.py     invoices, payroll, bills, month-end close
templates/, static/ pages and styling (print-friendly)
tests/              tax math, turn-in transactions, full-year replay, every page
```
