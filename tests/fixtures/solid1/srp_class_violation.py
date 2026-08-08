"""
    SRP violation fixture: UserService bundles three unrelated reasons to
    change — user persistence, email formatting, and report generation —
    so a change to any one of them requires editing the same class.
"""


class UserService:
    def create_user(self, name: str, email: str) -> dict:
        user = {"name": name, "email": email}
        print(f"INSERT INTO users VALUES ({name}, {email})")
        return user

    def send_welcome_email(self, email: str) -> None:
        subject = "Welcome!"
        body = "Thanks for signing up."
        print(f"Sending email to {email}: {subject} - {body}")

    def generate_signup_report(self, users: list[dict]) -> str:
        lines = [f"{user['name']} <{user['email']}>" for user in users]
        return "\n".join(lines)
