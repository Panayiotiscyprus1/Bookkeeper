"""2026 payroll tax calculation.

Sources (checked Sept 2026):
- Federal: IRS Publication 15-T (2026), Worksheet 1A + Annual Percentage Method,
  STANDARD withholding (Form W-4 2020 or later, Step 2 box not checked).
- Social Security: 6.2% up to the 2026 wage base of $184,500.
- Medicare: 1.45%, plus 0.9% Additional Medicare on YTD wages above $200,000.
- Illinois: flat 4.95%; each IL-W-4 line-1 allowance exempts $2,925/year (Booklet IL-700-T, 2026).
"""
from dataclasses import dataclass
from decimal import Decimal

from money import round_cents

YEAR = 2026
SS_RATE = Decimal("0.062")
SS_WAGE_BASE = 184_500_00           # cents
MEDICARE_RATE = Decimal("0.0145")
ADDL_MEDICARE_RATE = Decimal("0.009")
ADDL_MEDICARE_THRESHOLD = 200_000_00
IL_RATE = Decimal("0.0495")
IL_ALLOWANCE = 2_925_00             # cents per allowance per year

# Worksheet 1A line 1g: subtracted when the W-4 Step 2 box is not checked
STANDARD_ADJUSTMENT = {"single": 8_600_00, "hoh": 8_600_00, "married": 12_900_00}

# Annual Percentage Method, STANDARD schedules: (at least, base tax, rate), amounts in dollars
FEDERAL_BRACKETS = {
    "single": [(0, 0, 0), (7_500, 0, 10), (19_900, 1_240, 12), (57_900, 5_800, 22),
               (113_200, 17_966, 24), (209_275, 41_024, 32), (263_725, 58_448, 35),
               (648_100, 192_979.25, 37)],
    "married": [(0, 0, 0), (19_300, 0, 10), (44_100, 2_480, 12), (120_100, 11_600, 22),
                (230_700, 35_932, 24), (422_850, 82_048, 32), (531_750, 116_896, 35),
                (788_000, 206_583.50, 37)],
    "hoh": [(0, 0, 0), (15_550, 0, 10), (33_250, 1_770, 12), (83_000, 7_740, 22),
            (121_250, 16_155, 24), (217_300, 39_207, 32), (271_750, 56_631, 35),
            (656_150, 191_171, 37)],
}


@dataclass
class Paycheck:
    gross: int
    federal: int
    state: int
    social_security: int
    medicare: int
    employer_ss: int
    employer_medicare: int

    @property
    def withholding(self):
        return self.federal + self.state + self.social_security + self.medicare

    @property
    def net(self):
        return self.gross - self.withholding


def federal_withholding(gross_cents, periods, filing_status="single") -> int:
    """Pub 15-T Worksheet 1A: annualize, subtract standard adjustment, apply annual table."""
    annual = Decimal(gross_cents) * periods / 100
    adjusted = max(Decimal(0), annual - Decimal(STANDARD_ADJUSTMENT[filing_status]) / 100)
    brackets = FEDERAL_BRACKETS[filing_status]
    floor, base, rate = brackets[0]
    for row in brackets:
        if adjusted >= row[0]:
            floor, base, rate = row
    annual_tax = Decimal(str(base)) + (adjusted - floor) * Decimal(rate) / 100
    return round_cents(annual_tax * 100 / periods)


def illinois_withholding(gross_cents, periods, allowances=0) -> int:
    exempt_per_period = Decimal(allowances * IL_ALLOWANCE) / periods
    taxable = max(Decimal(0), Decimal(gross_cents) - exempt_per_period)
    return round_cents(taxable * IL_RATE)


def compute_paycheck(gross_cents, ytd_wages_cents=0, periods=12,
                     filing_status="single", state_allowances=0) -> Paycheck:
    # Social Security stops at the wage base
    ss_taxable = max(0, min(gross_cents, SS_WAGE_BASE - ytd_wages_cents))
    ss = round_cents(Decimal(ss_taxable) * SS_RATE)
    # Medicare: 1.45% on all wages + 0.9% employee-only above $200k YTD
    medicare = round_cents(Decimal(gross_cents) * MEDICARE_RATE)
    over = max(0, ytd_wages_cents + gross_cents - max(ADDL_MEDICARE_THRESHOLD, ytd_wages_cents))
    addl = round_cents(Decimal(over) * ADDL_MEDICARE_RATE)
    return Paycheck(
        gross=gross_cents,
        federal=federal_withholding(gross_cents, periods, filing_status),
        state=illinois_withholding(gross_cents, periods, state_allowances),
        social_security=ss,
        medicare=medicare + addl,
        employer_ss=ss,
        employer_medicare=medicare,
    )
