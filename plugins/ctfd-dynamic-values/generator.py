"""
Deterministic, stateless value generator for ctfd-dynamic-values.

A value is a pure function of (scope_key, salt, challenge_id, name, mask).
Nothing random is stored: the same inputs always yield the same output, so a
participant refreshing the page sees a stable value. Per-user / per-team / global
scope is encoded into scope_key by the caller.

Mask tokens (everything else is emitted literally):

    {A-B}   integer in the inclusive range [A, B], decimal
    {N}     N decimal digits           (N is a positive integer)
    {xN}    N lowercase hex chars
    {XN}    N uppercase hex chars
    {aN}    N lowercase letters [a-z]
    {AN}    N uppercase letters [A-Z]
    {wN}    N word chars [a-zA-Z0-9]
    \\{ \\}  literal braces

Examples:
    10.{0-255}.{0-255}.{1-254}   -> 10.137.42.200
    {1024-65535}                 -> 49213
    host-{x8}                    -> host-3fa9c0b1
    USER-{A6}                    -> USER-KQWZPL
"""

import hashlib
import re

# A token is either a range {A-B} or a class+count like {x8} / {12} / {a4}.
# We parse the mask into a sequence of (literal | token) chunks.
_TOKEN_RE = re.compile(
    r"""
    \{
        (?:
            (?P<lo>\d+)\s*-\s*(?P<hi>\d+)        # {A-B} range
          | (?P<cls>[xXaAwW]?)(?P<count>\d+)     # {N} {xN} {aN} {AN} {wN} {XN}
        )
    \}
    """,
    re.VERBOSE,
)

_ALPHABETS = {
    "x": "0123456789abcdef",
    "X": "0123456789ABCDEF",
    "a": "abcdefghijklmnopqrstuvwxyz",
    "A": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "w": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "": "0123456789",  # bare {N} -> decimal digits
}

MAX_COUNT = 256  # cap token length to avoid absurd output


class _ByteStream:
    """Deterministic, effectively-unbounded byte stream seeded by a digest.

    We expand the 32-byte sha256 seed with a counter so masks that need more
    than 32 bytes of entropy stay deterministic without repeating.
    """

    def __init__(self, seed_bytes):
        self._seed = seed_bytes
        self._buf = b""
        self._counter = 0

    def _refill(self):
        block = hashlib.sha256(
            self._seed + self._counter.to_bytes(8, "big")
        ).digest()
        self._counter += 1
        self._buf += block

    def take(self, n):
        while len(self._buf) < n:
            self._refill()
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def int_below(self, bound):
        """Uniform-ish integer in [0, bound) using rejection sampling."""
        if bound <= 0:
            return 0
        if bound == 1:
            return 0
        # number of bytes needed to cover bound
        nbytes = (bound.bit_length() + 7) // 8
        limit = (256 ** nbytes)
        # largest multiple of bound <= limit, for unbiased rejection
        cutoff = limit - (limit % bound)
        while True:
            val = int.from_bytes(self.take(nbytes), "big")
            if val < cutoff:
                return val % bound


def make_seed(scope_key, salt, challenge_id, name):
    """Build the deterministic seed digest for a single variable."""
    raw = "|".join(
        [
            str(scope_key),
            str(salt or ""),
            str(challenge_id if challenge_id is not None else ""),
            str(name or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _emit_token(match, stream):
    lo, hi = match.group("lo"), match.group("hi")
    if lo is not None:
        a, b = int(lo), int(hi)
        if b < a:
            a, b = b, a
        span = b - a + 1
        return str(a + stream.int_below(span))

    cls = match.group("cls") or ""
    count = min(int(match.group("count")), MAX_COUNT)
    alphabet = _ALPHABETS[cls]
    chars = []
    for _ in range(count):
        chars.append(alphabet[stream.int_below(len(alphabet))])
    return "".join(chars)


def render_mask(mask, seed_bytes):
    """Render a mask string into a concrete value using the seeded stream.

    Tokens consume entropy left-to-right; literal text (including escaped
    \\{ and \\}) is copied verbatim. Order is fixed, so the result is stable.
    """
    if mask is None:
        return ""
    stream = _ByteStream(seed_bytes)
    out = []
    i = 0
    n = len(mask)
    while i < n:
        ch = mask[i]
        if ch == "\\" and i + 1 < n and mask[i + 1] in "{}\\":
            out.append(mask[i + 1])
            i += 2
            continue
        if ch == "{":
            m = _TOKEN_RE.match(mask, i)
            if m:
                out.append(_emit_token(m, stream))
                i = m.end()
                continue
            # not a recognized token: emit the brace literally
            out.append("{")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def generate(mask, scope_key, salt, challenge_id, name):
    """Top-level: deterministic value for the given variable + scope."""
    seed = make_seed(scope_key, salt, challenge_id, name)
    return render_mask(mask, seed)


def scope_key_for(scope, user_id, team_id):
    """Map a scope label + identity to the seed's scope component.

    scope: "user" | "team" | "global"
    Falls back gracefully: team scope without a team degrades to user.
    """
    if scope == "global":
        return "g"
    if scope == "team":
        if team_id:
            return "t:%s" % team_id
        # no team (user-mode CTF): fall back to per-user so it still works
        return "u:%s" % (user_id or 0)
    # default: per-user
    return "u:%s" % (user_id or 0)
