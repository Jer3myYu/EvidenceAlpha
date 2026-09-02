"""Shared fixtures for the parsing unit tests.

The whole parser subsystem is network-free by design (03 §1.0, §3.7),
so every test under this directory runs with sockets disabled — the
guarantee is asserted rather than assumed, for the conformance suite,
the adapter golden tests, and everything else alike.
"""

import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any attempt to open a socket during a parsing test."""

    def deny(*args, **kwargs):
        del args, kwargs
        raise AssertionError(
            "the parser subsystem must not touch the network (03 §1.0)"
        )

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
