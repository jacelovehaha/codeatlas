"""Pricing helpers for the demo shop."""


def discount(price, pct):
    """Apply a percentage discount."""
    return price * (1 - pct / 100)


def total_with_tax(price):
    """Compute a total including a flat tax."""
    return discount(price, 0) * 1.2
