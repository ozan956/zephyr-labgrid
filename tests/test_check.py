# SPDX-License-Identifier: Apache-2.0
import io
from types import SimpleNamespace

from zephyr_labgrid import check


def test_unavailable_resource_fails_when_a_driver_uses_it(monkeypatch):
    def resource(name, avail):
        return SimpleNamespace(name=name, host='exporter1', avail=avail)
    serial, debugger, spare = (resource('USBSerialPort', True), resource('USBDebugger', False),
                               resource('USBFlashableDevice', False))
    monkeypatch.setattr(check, 'bound_resources', lambda target: [serial, debugger, spare])
    driver = SimpleNamespace(name=None, get_bound_resources=lambda: [serial, debugger])
    target = SimpleNamespace(drivers=[driver], get_driver=lambda *args, **kwargs: driver)
    out = io.StringIO()
    rep = check.Report(out)
    check.check_resources(rep, target, SimpleNamespace(acquired='h/u'))
    lines = out.getvalue().splitlines()
    assert lines[0].startswith('ok    resource SimpleNamespace USBSerialPort')
    assert lines[1].startswith('FAIL  resource SimpleNamespace USBDebugger on exporter1: '
                               'not available')
    assert lines[2].startswith('warn  resource SimpleNamespace USBFlashableDevice')
    assert (rep.failed, rep.warned) == (1, 1)
