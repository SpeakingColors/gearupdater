"""SysEx file checks for the gear updater. Pure Python, standard library only. Nothing here talks to a device."""
import hashlib
from dataclasses import dataclass, field


@dataclass
class SysexReport:
    size: int
    sha256: str
    messages: int = 0
    largest: int = 0
    problems: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.problems and self.messages > 0


def split_messages(data: bytes):
    """Split a .syx byte string into F0 ... F7 messages. Returns (messages, problems)."""
    msgs, problems, start = [], [], None
    for i, b in enumerate(data):
        if b == 0xF0:
            if start is not None:
                problems.append(f"F0 at byte {i} before the previous message ended")
            start = i
        elif b == 0xF7:
            if start is None:
                problems.append(f"F7 at byte {i} without a start")
            else:
                msgs.append(data[start:i + 1]); start = None
        elif b & 0x80:
            problems.append(f"status byte {b:#04x} at byte {i} inside or between SysEx messages")
        elif start is None:
            problems.append(f"data byte at {i} outside a message")
    if start is not None:
        problems.append("file ends inside a message (no F7)")
    return msgs, problems


def check(data: bytes) -> SysexReport:
    msgs, problems = split_messages(data)
    if not data:
        problems.append("file is empty")
    return SysexReport(size=len(data), sha256=hashlib.sha256(data).hexdigest(), messages=len(msgs),
                       largest=max((len(m) for m in msgs), default=0), problems=problems)
