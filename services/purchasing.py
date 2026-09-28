"""Purchasing and production: purchase orders, receiving, building trucks."""
from money import to_cents, round_cents
from models import db, Part, PurchaseOrder, FinishedGoods, current_date
import ledger
from ledger import BusinessError


def finished_goods() -> FinishedGoods:
    fg = db.session.get(FinishedGoods, 1)
    if fg is None:
        fg = FinishedGoods(id=1, qty_on_hand=0, value=0)
        db.session.add(fg)
    return fg


def bom_parts():
    return Part.query.filter(Part.qty_per_unit > 0).order_by(Part.id).all()


def buildable_units() -> int:
    parts = bom_parts()
    if not parts:
        return 0
    return min(p.qty_on_hand // p.qty_per_unit for p in parts)


def bom_cost_per_unit() -> int:
    """Standard cost of one truck at current vendor prices, in (fractional) cents."""
    return sum(p.qty_per_unit * p.unit_price * 100 for p in bom_parts())


def create_po(part_id, qty_ordered, receive_now=True, qty_received=None) -> PurchaseOrder:
    part = db.session.get(Part, int(part_id))
    if part is None:
        raise BusinessError("Unknown part.")
    qty_ordered = int(qty_ordered)
    if qty_ordered <= 0:
        raise BusinessError("Quantity must be positive.")
    po = PurchaseOrder(date=current_date(), part=part, vendor=part.vendor,
                       qty_ordered=qty_ordered, unit_price=part.unit_price)
    db.session.add(po)
    db.session.flush()
    if receive_now:
        receive_po(po, qty_received if qty_received not in (None, "") else qty_ordered)
    db.session.commit()
    return po


def receive_po(po, qty_received) -> PurchaseOrder:
    """Goods arrive. We are billed for what actually arrived (may differ from ordered)."""
    if po.received_date is not None:
        raise BusinessError(f"PO #{po.id} was already received.")
    qty_received = int(qty_received)
    if qty_received <= 0:
        raise BusinessError("Received quantity must be positive.")
    total = to_cents(qty_received * po.unit_price)
    po.qty_received = qty_received
    po.total = total
    po.received_date = current_date()
    po.part.qty_on_hand += qty_received
    po.part.value += total
    diff = qty_received - po.qty_ordered
    note = "" if diff == 0 else f" ({'+' if diff > 0 else ''}{diff:,} vs ordered)"
    entry = ledger.post(po.received_date, "po_receipt",
                        f"PO #{po.id}: {qty_received:,} {po.part.name} from {po.vendor.company}{note}",
                        [(ledger.RAW_MATERIALS, total, 0), (ledger.AP, 0, total)])
    po.entry_id = entry.id
    return po


def receive_open_po(po_id, qty_received):
    po = db.session.get(PurchaseOrder, int(po_id))
    if po is None:
        raise BusinessError("Unknown PO.")
    receive_po(po, qty_received)
    db.session.commit()
    return po


def build_units(n) -> int:
    """Consume BOM parts (at moving-average cost) and add finished trucks. Non-cash."""
    n = int(n)
    if n <= 0:
        raise BusinessError("Number of units must be positive.")
    max_units = buildable_units()
    if n > max_units:
        raise BusinessError(f"Only {max_units:,} units can be built from parts on hand.")
    total = 0
    for p in bom_parts():
        used = p.qty_per_unit * n
        cost = round_cents(p.value * used / p.qty_on_hand) if used < p.qty_on_hand else p.value
        p.qty_on_hand -= used
        p.value -= cost
        total += cost
    fg = finished_goods()
    fg.qty_on_hand += n
    fg.value += total
    ledger.post(current_date(), "build", f"Built {n:,} trucks from parts inventory",
                [(ledger.FINISHED_GOODS, total, 0), (ledger.RAW_MATERIALS, 0, total)])
    db.session.commit()
    return total
