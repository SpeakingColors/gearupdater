"""One window only: a second start (for example from a studio87:// link) hands its link to the running one and exits."""
import hashlib
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name():
    who = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return "studio87-gearupdater-" + hashlib.sha1(who.encode()).hexdigest()[:12]


def send(message, name=None, timeout=800):
    """True when a running instance took the message. The message is only a link text or the word focus."""
    s = QLocalSocket()
    s.connectToServer(name or server_name())
    if not s.waitForConnected(timeout):
        return False
    s.write((message or "focus").encode("utf-8")[:1000])
    s.flush()
    s.waitForBytesWritten(timeout)
    s.disconnectFromServer()
    return True


class Receiver(QObject):
    got = Signal(str)

    def __init__(self, name=None, parent=None):
        super().__init__(parent)
        self.name = name or server_name()
        self.server = QLocalServer(self)
        QLocalServer.removeServer(self.name)           # a stale socket from a crash
        self.ok = self.server.listen(self.name)
        self.server.newConnection.connect(self._new)

    def _new(self):
        while self.server.hasPendingConnections():
            c = self.server.nextPendingConnection()
            c.waitForReadyRead(500)
            data = bytes(c.readAll())[:1000].decode("utf-8", "replace")
            c.disconnectFromServer()
            self.got.emit(data)
