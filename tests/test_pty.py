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


def test_place_and_env_from_the_coordinator(clean_env, monkeypatch, place_info, tmp_path):
    from zephyr_labgrid import common
    places = {'p': place_info('b/q', acquired='h/u', zephyr_env='e.yaml'),
              'q': place_info('b/q')}
    monkeypatch.setattr(common, 'lab_places', lambda coordinator=None: places)
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV_DIR', str(tmp_path))
    args = pty.build_parser().parse_args([])
    pty.resolve_place(args)
    assert (args.place, args.env) == ('p', str(tmp_path / 'e.yaml'))
    args = pty.build_parser().parse_args(['-p', 'q'])
    with pytest.raises(common.PlaceSelectError, match='labgrid-client -p q acquire'):
        pty.resolve_place(args)


def test_usage_error_without_any_place(clean_env, monkeypatch, capsys):
    from zephyr_labgrid import common
    monkeypatch.setattr(common, 'lab_places', lambda coordinator=None: {})
    with pytest.raises(SystemExit) as e:
        pty.main([])
    assert e.value.code == 2
    assert 'you hold no place' in capsys.readouterr().err


def test_place_from_twister_platform(clean_env, monkeypatch, place_info):
    from zephyr_labgrid import common
    places = {'stm': place_info('stm/q', acquired='h/u', zephyr_env='/s.yaml'),
              'esp': place_info('esp/esp32/procpu', acquired='h/u', zephyr_env='/e.yaml')}
    monkeypatch.setattr(common, 'lab_places', lambda coordinator=None: places)
    monkeypatch.setenv('TWISTER_PLATFORM', 'esp/esp32/procpu')
    args = pty.build_parser().parse_args([])
    pty.resolve_place(args)
    assert (args.place, args.env) == ('esp', '/e.yaml')


def test_defaults_come_from_environment(clean_env, monkeypatch):
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV', '/e.yaml')
    monkeypatch.setenv('LG_PLACE', 'p1')
    monkeypatch.setenv('LG_PTY_NO_PURGE', '1')
    args = pty.build_parser().parse_args([])
    assert (args.env, args.place, args.purge) == ('/e.yaml', 'p1', 'off')
    args = pty.build_parser().parse_args(['-e', '/x.yaml', '-p', 'p2', '--purge', 'auto'])
    assert (args.env, args.place, args.purge) == ('/x.yaml', 'p2', 'auto')
