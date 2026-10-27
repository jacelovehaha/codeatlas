"""Order handling for the demo shop."""

from shop.pricing import discount, total_with_tax


class Order:
    """A customer order."""

    def total(self, price):
        """Total for this order."""
        return total_with_tax(price)


class DiscountedOrder(Order):
    """An order with a loyal-customer discount."""

    def total(self, price):
        """Discounted total."""
        return discount(price, 10)
