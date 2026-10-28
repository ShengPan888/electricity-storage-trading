"""Competition rules: 96 slots, one optional cycle, eight slots per operation.

The provided competition formula treats each action as +/-1000 energy units.
No additional 0.25-hour multiplier, efficiency, fee, or degradation is inserted.
"""

from dataclasses import dataclass
from math import fsum, isfinite
from typing import Iterable

SLOTS = 96
BLOCK = 8
ENERGY = 1000
CAPACITY = 8000


def checked_prices(values: Iterable[float]) -> tuple[float, ...]:
    prices = tuple(float(value) for value in values)
    if len(prices) != SLOTS:
        raise ValueError(f"Expected 96 price slots, received {len(prices)}")
    if not all(isfinite(value) for value in prices):
        raise ValueError("Prices must be finite; NaN and infinity are invalid")
    return prices


@dataclass(frozen=True)
class Schedule:
    charge_start: int | None
    discharge_start: int | None
    power: tuple[int, ...]
    predicted_profit: float


def validate_power(values: Iterable[float]) -> tuple[int, ...]:
    actions = tuple(values)
    if len(actions) != SLOTS:
        raise ValueError("A day must contain exactly 96 actions")
    if any(value not in (-ENERGY, 0, ENERGY) for value in actions):
        raise ValueError("Actions must belong to {-1000, 0, 1000}")
    power = tuple(int(value) for value in actions)
    charge = [i for i, value in enumerate(power) if value < 0]
    discharge = [i for i, value in enumerate(power) if value > 0]
    if not charge and not discharge:
        return power
    if len(charge) != BLOCK or len(discharge) != BLOCK:
        raise ValueError("A trading day requires exactly 8 charge and 8 discharge slots")
    c, d = charge[0], discharge[0]
    if charge != list(range(c, c + BLOCK)):
        raise ValueError("Charging must be continuous for 8 slots")
    if discharge != list(range(d, d + BLOCK)):
        raise ValueError("Discharging must be continuous for 8 slots")
    if not (0 <= c <= 80 and c + BLOCK <= d <= 88):
        raise ValueError("Discharge must follow charging and finish within the day")
    soc = 0
    for value in power:
        soc -= value
        if not 0 <= soc <= CAPACITY:
            raise ValueError("SOC violates [0, 8000]")
    if soc != 0:
        raise ValueError("End-of-day SOC must return to zero")
    return power


def settle(prices: Iterable[float], power: Iterable[float]) -> float:
    actual = checked_prices(prices)
    actions = validate_power(power)
    return fsum(price * action for price, action in zip(actual, actions))


def optimize_day(predicted_prices: Iterable[float]) -> Schedule:
    """Maximize predicted profit over 3321 legal cycles and the no-trade action.

    Ties retain the earliest charge/discharge pair. Zero profit chooses no trade.
    Only predicted prices enter this function; realized prices are for settlement.
    """
    prices = checked_prices(predicted_prices)
    # Only 89 small windows: stable direct sums avoid artificial spreads caused
    # by subtracting floating-point cumulative sums on a constant price curve.
    windows = [fsum(prices[s:s + BLOCK]) for s in range(89)]
    best_profit = 0.0
    best_pair = None
    for c in range(81):
        for d in range(c + BLOCK, 89):
            profit = ENERGY * (windows[d] - windows[c])
            if profit > best_profit:
                best_profit, best_pair = profit, (c, d)
    power = [0] * SLOTS
    if best_pair is None:
        return Schedule(None, None, tuple(power), 0.0)
    c, d = best_pair
    power[c:c + BLOCK] = [-ENERGY] * BLOCK
    power[d:d + BLOCK] = [ENERGY] * BLOCK
    actions = validate_power(power)
    return Schedule(c, d, actions, settle(prices, actions))
