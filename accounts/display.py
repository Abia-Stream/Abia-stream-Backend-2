FALLBACK_NAME = 'Abia Stream user'


def display_name(user):
    """
    The public name for a user: profile full name, else channel name.

    Use this anywhere one user's identity is shown to another (comments,
    chat, notifications). Never fall back to the email address — it is
    private.
    """
    try:
        if user.profile.full_name:
            return user.profile.full_name
    except Exception:  # noqa: BLE001 - no profile
        pass
    try:
        if user.channel.channel_name:
            return user.channel.channel_name
    except Exception:  # noqa: BLE001 - no channel
        pass
    return FALLBACK_NAME
