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


def test_interactive_only_for_a_person_at_a_terminal(monkeypatch):
    import os
    from zephyr_labgrid import common
    r, w = os.pipe()
    assert not pty.interactive(r)           # a pipe, as from sleep 60 | labgrid-pty
    os.close(r)
    os.close(w)
    monkeypatch.setattr(pty.os, 'isatty', lambda fd: True)
    monkeypatch.setattr(pty.os, 'tcgetpgrp', lambda fd: 7)
    monkeypatch.setattr(pty.os, 'getpgrp', lambda: 7)
    monkeypatch.setattr(common, 'twister_words', lambda: None)
    assert pty.interactive(0)
    monkeypatch.setattr(pty.os, 'getpgrp', lambda: 8)
    assert not pty.interactive(0)           # a background job
    monkeypatch.setattr(pty.os, 'getpgrp', lambda: 7)
    monkeypatch.setattr(common, 'twister_words', lambda: [b'twister'])
    assert not pty.interactive(0)           # Twister passes a pty


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
    assert not args.reset_rts
    places['esp']['tags']['zephyr_reset_rts'] = 'true'
    pty.resolve_place(args)
    assert args.reset_rts                   # from the tag of the place


def test_flash_before_place_needs_flash_before_in_twister(clean_env, monkeypatch,
                                                          place_info):
    from zephyr_labgrid import common
    places = {'esp': place_info('esp/esp32/procpu', acquired='h/u', zephyr_env='/e.yaml',
                                zephyr_flash_before='true')}
    monkeypatch.setattr(common, 'lab_places', lambda coordinator=None: places)
    monkeypatch.setattr(common, 'twister_flashes_after_console', lambda: True)
    with pytest.raises(common.PlaceSelectError, match='--flash-before'):
        pty.resolve_place(pty.build_parser().parse_args([]))
    monkeypatch.setattr(common, 'twister_flashes_after_console', lambda: False)
    args = pty.build_parser().parse_args([])
    pty.resolve_place(args)
    assert args.place == 'esp'


def test_defaults_come_from_environment(clean_env, monkeypatch):
    monkeypatch.setenv('ZEPHYR_LABGRID_ENV', '/e.yaml')
    monkeypatch.setenv('LG_PLACE', 'p1')
    args = pty.build_parser().parse_args([])
    assert (args.env, args.place) == ('/e.yaml', 'p1')
    args = pty.build_parser().parse_args(['-e', '/x.yaml', '-p', 'p2'])
    assert (args.env, args.place) == ('/x.yaml', 'p2')
