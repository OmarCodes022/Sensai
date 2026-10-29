"""Validate profile preferences sent by the page, with the same rules as a --profile-file."""


def clean_preferences(data: object) -> dict[str, str]:
    if not isinstance(data, dict):
        raise ValueError("preferences must be a JSON object")
    preferences: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str) or not key.strip() or not value.strip():
            raise ValueError(f"profile entry {key!r} must map a nonempty key to a nonempty string")
        if key.strip() in preferences:
            raise ValueError(f"duplicate profile key: {key.strip()}")
        preferences[key.strip()] = value.strip()
    return preferences
