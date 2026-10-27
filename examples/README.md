# Examples

`demo_package/` is a tiny three-module package with known imports,
inheritance, and calls — handy for a first run:

```bash
PYTHONPATH=src python -m codeatlas build examples/demo_package -o /tmp/atlas.json
PYTHONPATH=src python -m codeatlas stats /tmp/atlas.json
PYTHONPATH=src python -m codeatlas query /tmp/atlas.json shop.orders.DiscountedOrder
PYTHONPATH=src python -m codeatlas search /tmp/atlas.json total
PYTHONPATH=src python -m codeatlas map /tmp/atlas.json
```

Expected shape: `shop.orders` imports `shop.pricing`,
`shop.orders.DiscountedOrder` inherits from `shop.orders.Order`, and
`shop.pricing.total_with_tax` calls `shop.pricing.discount`.
