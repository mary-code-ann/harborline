"""Payment plan rules.

The model must not invent a monthly amount, a term, or a discount. Call
`offer_plan()` and speak only the amounts on the PlanOffer it returns.
The written rules are in docs/procedure.md.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from app.policy import MAX_PLAN_MONTHS, MIN_PLAN_DOLLARS, MIN_PLAN_FRACTION

MONEY = Decimal("0.01")
ZERO = Decimal("0.00")

# Reason codes returned when the caller's request is outside the rules.
NO_WAIVER = "NO_WAIVER"
BELOW_MINIMUM = "BELOW_MINIMUM"
EXCEEDS_MAX_MONTHS = "EXCEEDS_MAX_MONTHS"
AMOUNT_RAISED_FOR_PAYOFF = "AMOUNT_RAISED_FOR_PAYOFF"
TERM_SHORTENED_FOR_MINIMUM = "TERM_SHORTENED_FOR_MINIMUM"
CAPPED_AT_BALANCE = "CAPPED_AT_BALANCE"
MONTHS_TOO_LOW = "MONTHS_TOO_LOW"
PAY_IN_FULL_ONLY = "PAY_IN_FULL_ONLY"


def money(value: Decimal | int | str) -> Decimal:
    """Quantize to cents. Floats are rejected so binary fractions cannot sneak in."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise TypeError("money must be Decimal, int, or str")
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if amount.is_nan() or amount.is_infinite():
        raise ValueError("money must be a finite amount")
    return amount.quantize(MONEY, rounding=ROUND_HALF_UP)


def ceil_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_CEILING)


def minimum_monthly(balance: Decimal | int | str) -> Decimal:
    """The floor: max(10% of balance, $25), rounded up to the cent.

    This is not always the amount we offer. A plan also has to collect the
    full balance in at most six months, and that can require a higher payment.
    """
    amount = money(balance)
    raw = max(amount * MIN_PLAN_FRACTION, MIN_PLAN_DOLLARS)
    return ceil_money(raw)


def _cents(amount: Decimal) -> int:
    return int(money(amount) * 100)


def _from_cents(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal(100)).quantize(MONEY)


def max_installments(balance: Decimal) -> int:
    """How many installments we can make without dropping below the floor."""
    amount = money(balance)
    floor = minimum_monthly(amount)
    if amount <= floor:
        return 1
    count = _cents(amount) // _cents(floor)
    return max(1, min(MAX_PLAN_MONTHS, count))


def split_even(balance: Decimal, months: int) -> tuple[Decimal, ...]:
    """Split a balance into `months` installments that sum to the exact cent.

    The first installments each take one leftover cent. Every installment is
    at least one cent.
    """
    if months < 1:
        raise ValueError("months must be at least 1")
    total = _cents(balance)
    if total <= 0:
        raise ValueError("balance must be positive")
    base, extra = divmod(total, months)
    if base == 0:
        raise ValueError("balance is too small to split into that many payments")
    larger = [_from_cents(base + 1)] * extra
    smaller = [_from_cents(base)] * (months - extra)
    return tuple(larger + smaller)


def months_needed(balance: Decimal, monthly: Decimal) -> int:
    balance_cents = _cents(balance)
    monthly_cents = _cents(monthly)
    if monthly_cents <= 0:
        raise ValueError("monthly payment must be positive")
    return (balance_cents + monthly_cents - 1) // monthly_cents


def schedule_fixed(
    balance: Decimal, monthly: Decimal, floor: Decimal
) -> tuple[Decimal, ...]:
    """Repeat `monthly` until the balance is gone.

    The last installment would be the unpaid remainder. If that remainder would
    be below the floor, it is added to the previous payment instead, so we never
    bill an installment under the minimum and we never drop the remainder.
    """
    if monthly <= 0:
        raise ValueError("monthly payment must be positive")
    remaining = money(balance)
    payment = money(monthly)
    least = money(floor)
    if payment > remaining:
        return (remaining,)
    amounts: list[Decimal] = []
    while remaining > payment and remaining - payment >= least:
        amounts.append(payment)
        remaining -= payment
    amounts.append(remaining)
    return tuple(amounts)


@dataclass(frozen=True)
class PlanOffer:
    """A legal plan. `spoken_amounts` is the only set of dollar figures a reply may use."""

    balance: Decimal
    monthly_amount: Decimal
    months: int
    total_amount: Decimal
    schedule: tuple[Decimal, ...]
    adjusted: bool
    waiver_refused: bool
    reasons: tuple[str, ...]
    requested_monthly: Decimal | None = None
    requested_months: int | None = None

    def __post_init__(self) -> None:
        if self.total_amount != self.balance:
            raise RuntimeError("a plan must total the full balance; waivers are not allowed")
        if sum(self.schedule, ZERO) != self.balance:
            raise RuntimeError("installments must sum to the balance")
        if self.months != len(self.schedule) or not 1 <= self.months <= MAX_PLAN_MONTHS:
            raise RuntimeError("term must be 1 to 6 months and match the schedule")
        if self.monthly_amount not in self.schedule:
            raise RuntimeError("quoted monthly amount must appear on the schedule")
        if any(part <= 0 for part in self.schedule):
            raise RuntimeError("every installment must be positive")
        floor = minimum_monthly(self.balance)
        if self.balance > floor and any(part < floor for part in self.schedule):
            raise RuntimeError("an installment is below the minimum monthly payment")

    @property
    def spoken_amounts(self) -> frozenset[Decimal]:
        return frozenset({self.balance, self.monthly_amount, self.total_amount, *self.schedule})

    def describe(self) -> str:
        """A factual sentence. The reply generator may quote this and must not add figures."""
        groups: list[list] = []
        for amount in self.schedule:
            if groups and groups[-1][0] == amount:
                groups[-1][1] += 1
            else:
                groups.append([amount, 1])
        parts: list[str] = []
        for amount, count in groups:
            label = "payment" if count == 1 else "payments"
            parts.append(f"{count} {label} of ${amount:.2f}")
        if len(parts) == 2:
            body = f"{parts[0]} and {parts[1]}"
        else:
            body = ", ".join(parts)
        return f"{body}, totaling ${self.total_amount:.2f} (the full balance)."


def offer_plan(
    balance: Decimal | int | str,
    requested_monthly: Decimal | int | str | None = None,
    requested_months: int | None = None,
    *,
    waive: bool = False,
) -> PlanOffer:
    """Return the closest legal plan for this balance.

    `waive=True` is how the state machine reports "waive my whole balance"
    or any other request to reduce what is owed. The returned total is still
    the full balance.
    """
    owed = money(balance)
    if owed <= 0:
        raise ValueError("balance must be positive")

    asked_monthly = None if requested_monthly is None else money(requested_monthly)
    asked_months = requested_months
    reasons: list[str] = []
    waiver_refused = False
    usable_monthly = asked_monthly
    usable_months = asked_months

    if waive or (asked_monthly is not None and asked_monthly <= 0):
        waiver_refused = True
        reasons.append(NO_WAIVER)
        usable_monthly = None
        usable_months = None

    floor = minimum_monthly(owed)
    longest = max_installments(owed)

    if owed <= floor:
        if usable_monthly not in (None, owed) or usable_months not in (None, 1):
            reasons.append(PAY_IN_FULL_ONLY)
        schedule = (owed,)
    else:
        months = _clamp_months(usable_months, longest, reasons)
        schedule = _schedule_for(owed, floor, months, usable_monthly, reasons)

    return _offer(
        owed,
        schedule,
        reasons,
        waiver_refused,
        asked_monthly,
        asked_months,
    )


def _clamp_months(requested: int | None, longest: int, reasons: list[str]) -> int:
    if requested is None:
        return longest
    if requested > MAX_PLAN_MONTHS:
        reasons.append(EXCEEDS_MAX_MONTHS)
        return min(MAX_PLAN_MONTHS, longest)
    if requested < 1:
        reasons.append(MONTHS_TOO_LOW)
        return 1
    if requested > longest:
        reasons.append(TERM_SHORTENED_FOR_MINIMUM)
        return longest
    return requested


def _schedule_for(
    balance: Decimal,
    floor: Decimal,
    months: int,
    requested_monthly: Decimal | None,
    reasons: list[str],
) -> tuple[Decimal, ...]:
    if requested_monthly is None:
        return split_even(balance, months)

    payment = requested_monthly
    if payment > balance:
        reasons.append(CAPPED_AT_BALANCE)
        return (balance,)
    if payment < floor:
        reasons.append(BELOW_MINIMUM)
        payment = floor

    needed = months_needed(balance, payment)
    if needed > months or needed > MAX_PLAN_MONTHS:
        reasons.append(AMOUNT_RAISED_FOR_PAYOFF)
        return split_even(balance, months)

    schedule = schedule_fixed(balance, payment, floor)
    if schedule[0] != payment:
        reasons.append(AMOUNT_RAISED_FOR_PAYOFF)
    return schedule


def _offer(
    balance: Decimal,
    schedule: tuple[Decimal, ...],
    reasons: list[str],
    waiver_refused: bool,
    requested_monthly: Decimal | None,
    requested_months: int | None,
) -> PlanOffer:
    return PlanOffer(
        balance=balance,
        monthly_amount=schedule[0],
        months=len(schedule),
        total_amount=balance,
        schedule=schedule,
        adjusted=bool(reasons),
        waiver_refused=waiver_refused,
        reasons=tuple(reasons),
        requested_monthly=requested_monthly,
        requested_months=requested_months,
    )
