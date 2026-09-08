"""
    COUP false-positive fixture: a checkout coordinator calling several
    public methods on the cart it was handed to orchestrate a workflow.
    Should NOT be flagged as feature envy — this is delegation through a
    collaborator's declared public interface, the shape a coordinator is
    supposed to have, not this method manipulating another object's data
    itself.
"""


class Cart:
    def validate(self) -> None:
        pass

    def total(self) -> float:
        return 42.0

    def clear(self) -> None:
        pass


class CheckoutCoordinator:
    def complete(self, cart: Cart) -> float:
        cart.validate()
        total = cart.total()
        cart.clear()
        return total
