# SPDX-License-Identifier: Apache-2.0
import pytest

from zephyr_labgrid import pty


class FakeSerial:
    def __init__(self):
        self.events = []

    def __setattr__(self, name, value):
        if name in ('dtr', 'rts'):
            self.events.append((name, value))
        super().__setattr__(name, value)


def test_reset_rts_pulses_rts_with_dtr_low(monkeypatch):
    monkeypatch.setattr(pty.time, 'sleep', lambda s: None)
    ser = FakeSerial()
    pty.reset_rts(ser)
    assert ser.events == [('dtr', False), ('rts', True), ('rts', False)]


def test_usage_error_without_env_and_place(clean_env, capsys):
    with pytest.raises(SystemExit) as e:
        pty.main([])
    assert e.value.code == 2
    assert '--place' in capsys.readouterr().err


def test_defaults_come_from_environment(clean_env, monkeypatch):
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV', '/e.yaml')
    monkeypatch.setenv('LG_PLACE', 'p1')
    monkeypatch.setenv('LG_PTY_NO_PURGE', '1')
    args = pty.build_parser().parse_args([])
    assert (args.env, args.place, args.purge) == ('/e.yaml', 'p1', 'off')
    args = pty.build_parser().parse_args(['-e', '/x.yaml', '-p', 'p2', '--purge', 'auto'])
    assert (args.env, args.place, args.purge) == ('/x.yaml', 'p2', 'auto')
