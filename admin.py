"""Small authorization helpers shared by page operations and tests."""


def is_dashboard_admin(username: object) -> bool:
    """Plugin Pages use dashboard JWT users; scoped API keys are not admins."""
    return (
        isinstance(username, str)
        and bool(username.strip())
        and not username.startswith("api_key:")
    )
