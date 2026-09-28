"""Money helpers. All amounts are stored as integer cents to avoid float rounding errors."""
from decimal import Decimal, ROUND_HALF_UP


def to_cents(value) -> int:
    """Convert dollars (str/float/int/Decimal) to integer cents, rounding half up."""
    d = Decimal(str(value)) * 100
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_cents(value) -> int:
    """Round a (possibly fractional) cents amount to whole cents, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt(cents, blank_zero=False) -> str:
    """Format cents as $1,234.56 (negative as -$1,234.56)."""
    if cents is None:
        return ""
    if blank_zero and cents == 0:
        return "-"
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def fmt_price(dollars) -> str:
    """Unit prices can be fractions of a cent, so show up to 4 decimals."""
    s = f"{Decimal(str(dollars)):.4f}".rstrip("0")
    if s.endswith("."):
        s += "00"
    elif len(s.split(".")[1]) < 2:
        s += "0"
    return f"${s}"
