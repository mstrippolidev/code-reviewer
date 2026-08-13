"""
    BOUND out-of-scope fixture: UserRegistrar's only signal that
    build_welcome_email() is not meant to be called from outside is a
    docstring, not an actual naming convention, so nothing enforces the
    boundary the comment claims exists. Not a leaked mutable
    representation, not unmarked internal *state* (this is a method, and
    it is documented as internal, just not enforced), not an oversized
    surface on its own, and not a leaking library type, so it sits
    outside the four in-scope categories.
"""


class UserRegistrar:
    def register(self, email: str, display_name: str) -> str:
        body = self.build_welcome_email(display_name)
        return body

    def build_welcome_email(self, display_name: str) -> str:
        """Internal use only — do not call directly outside register()."""
        return f"Welcome, {display_name}!"
