"""Feature construction: stock aggregation, HDD, fabric-weighted response.

Every feature carries an `as_of` semantics test in tests/. A feature that
cannot state the timestamp at which it became knowable does not ship.
"""
