"""Version parsing and comparison. Never guesses: unparseable input gives None."""
import re

_RE = re.compile(r"^[vV]?(\d+(?:\.\d+){0,3})(?:[-+_.]?([0-9A-Za-z][0-9A-Za-z.\-]*))?$")


def parse(text):
    """Return (numbers tuple, pre-release string or None), or None when not a version."""
    if not isinstance(text, str):
        return None
    m = _RE.match(text.strip())
    if not m:
        return None
    nums = [int(p) for p in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    pre = m.group(2)
    return tuple(nums), (pre.lower() if pre else None)


def clean(text):
    """'v0.1.2' -> '0.1.2'; anything unparseable -> None."""
    p = parse(text)
    if p is None:
        return None
    nums = list(p[0])
    while len(nums) > 3 and nums[-1] == 0:
        nums.pop()
    return ".".join(str(n) for n in nums) + ("-" + p[1] if p[1] else "")


def _pre_key(pre):
    return [(0, int(part), "") if part.isdigit() else (1, 0, part) for part in re.findall(r"\d+|[a-z]+", pre)]


def compare(a, b):
    """-1, 0 or 1; None when either side cannot be parsed."""
    pa, pb = parse(a), parse(b)
    if pa is None or pb is None:
        return None
    if pa[0] != pb[0]:
        return -1 if pa[0] < pb[0] else 1
    if pa[1] == pb[1]:
        return 0
    if pa[1] is None:      # 1.0.0 is newer than 1.0.0-rc1
        return 1
    if pb[1] is None:
        return -1
    ka, kb = _pre_key(pa[1]), _pre_key(pb[1])
    return -1 if ka < kb else (1 if ka > kb else 0)


def is_update(installed, latest):
    """True if latest is newer than installed; False if not; None if unknown."""
    c = compare(installed, latest)
    return None if c is None else c < 0
