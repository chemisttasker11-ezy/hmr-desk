"""Plain reporting for optional portal helpers that a build may not contain."""

MISSING = {
    'mims': 'The eMIMS list helper is not installed in this build, so no interaction lists can be prepared here. Medicines can still be confirmed and the interaction check documented manually.',
    'ppa': 'The PPA claim helper is not installed in this build, so no claim rows can be prepared here. Reports and records work without it.',
}


def respond(helper, key, rows, available):
    """Keep the existing response key and add `helper_available`, plus a `message` only when the helper is absent."""
    out = {key: rows, 'helper_available': bool(available)}
    if not available: out['message'] = MISSING[helper]
    return out
