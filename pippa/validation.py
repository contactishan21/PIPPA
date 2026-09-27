from __future__ import annotations


def valid_email(value: str) -> bool:
    """Validate the existing sign-in email shape without regex backtracking."""
    email = value.strip()
    if not email or any(character.isspace() for character in email):
        return False

    local_part, separator, domain = email.partition("@")
    if not separator or not local_part or not domain or "@" in domain:
        return False

    domain_name, dot, suffix = domain.rpartition(".")
    return bool(dot and domain_name and suffix)
