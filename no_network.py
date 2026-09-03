"""Run the test suite with every outbound connection refused.

The README says the suite reaches neither agency. That is a claim a machine
can check, so this runs the whole thing with name resolution refused and with
any connection to something other than loopback refused. A test that quietly
reaches openFDA or the USDA fails here instead of on somebody else's laptop.

    python no_network.py

Two shapes of this check were wrong before this one, and both are worth
knowing.

Dropping outbound traffic with a firewall rule on CI also severs the runner's
own link to GitHub and hangs the job.

Refusing `socket.socket` outright fails 7 of 34 tests, and not because they
touch the network. On Windows the asyncio event loop builds a loopback socket
pair to wake itself, so a suite that never leaves the machine still creates
sockets. Refusing the constructor measures the event loop, not the tests.
What is worth proving is narrower and truer, that nothing here resolves a name
or connects off the machine.
"""

from __future__ import annotations

import socket
import sys

LOOPBACK = ("127.0.0.1", "::1", "localhost", "")


class NetworkRefused(OSError):
    pass


def _refuse_name(*args, **_kwargs):
    # The trailing comma matters. Without it a tuple argument, which is what
    # create_connection is handed, gets unpacked by the format operator and
    # the guard dies of a TypeError instead of saying what it refused.
    raise NetworkRefused("the suite is not allowed to reach %r" % (args[0] if args else "",))


def _guard(original):
    def connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            raise NetworkRefused("the suite is not allowed to connect to %r" % (host,))
        return original(self, address, *args, **kwargs)
    return connect


def main() -> int:
    import pytest

    socket.socket.connect = _guard(socket.socket.connect)
    socket.socket.connect_ex = _guard(socket.socket.connect_ex)
    socket.getaddrinfo = _refuse_name
    socket.gethostbyname = _refuse_name
    socket.create_connection = _refuse_name

    return pytest.main(["-q"])


if __name__ == "__main__":
    raise SystemExit(main())
