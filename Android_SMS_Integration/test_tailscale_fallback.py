import copy
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sms_bridge import verify_tailscale_peer

TARGET = '100.64.1.50'
SELF = {'Online': False, 'InNetworkMap': True, 'TailscaleIPs': ['100.64.1.2']}
STATUS = {'BackendState': 'Running', 'Self': SELF,
          'Peer': {'synthetic': {'Online': True, 'TailscaleIPs': [TARGET]}}}


def runner(status):
    return lambda: (0, json.dumps(status), '')


def pong(target):
    return 0, f'pong from synthetic ({target}) via DERP(test) in 1ms\n', ''


class TestTailscaleFallback(unittest.TestCase):
    def test_verified_exact_target(self):
        calls = []
        def ping(target):
            calls.append(target)
            return pong(target)
        ok, message = verify_tailscale_peer(TARGET, runner(STATUS), ping)
        self.assertTrue(ok)
        self.assertEqual(calls, [TARGET])
        self.assertNotIn(TARGET, message)
        self.assertNotIn('synthetic', message)

    def test_all_unverified_conditions_fail_closed_without_ping(self):
        cases = []
        for key, value in [('Online', None), ('InNetworkMap', False), ('TailscaleIPs', []), ('TailscaleIPs', ['not-an-ip'])]:
            status = copy.deepcopy(STATUS); status['Self'][key] = value; cases.append(status)
        status = copy.deepcopy(STATUS); status['BackendState'] = 'Stopped'; cases.append(status)
        status = copy.deepcopy(STATUS); status['Self'] = None; cases.append(status)
        status = copy.deepcopy(STATUS); status['Peer']['synthetic']['Online'] = False; cases.append(status)
        status = copy.deepcopy(STATUS); status['Peer']['synthetic']['TailscaleIPs'] = ['100.64.1.51']; cases.append(status)
        status = copy.deepcopy(STATUS); status['Peer']['synthetic']['TailscaleIPs'] = TARGET; cases.append(status)
        for status in cases:
            with self.subTest(status=status):
                calls = []
                ok, _ = verify_tailscale_peer(TARGET, runner(status), lambda target: calls.append(target) or pong(target))
                self.assertFalse(ok)
                self.assertEqual(calls, [])
        for invalid in ['phone.example', '8.8.8.8', '100.128.0.1']:
            ok, _ = verify_tailscale_peer(invalid, runner(STATUS), pong)
            self.assertFalse(ok)

    def test_wrong_pong_nonzero_and_timeout_fail_without_details(self):
        responses = [lambda _: (0, 'pong from synthetic (100.64.1.51) via DERP(test) in 1ms', ''),
                     lambda _: (1, pong(TARGET)[1], 'private failure'),
                     lambda _: (0, 'unexpected private output', ''),
                     lambda _: (_ for _ in ()).throw(subprocess.TimeoutExpired('synthetic', 3))]
        for ping in responses:
            ok, message = verify_tailscale_peer(TARGET, runner(STATUS), ping)
            self.assertFalse(ok)
            self.assertNotIn(TARGET, message)
            self.assertNotIn('private', message)

    def test_custom_status_without_ping_never_accesses_network(self):
        with patch('sms_bridge.subprocess.run', side_effect=AssertionError('unexpected subprocess')):
            self.assertFalse(verify_tailscale_peer(TARGET, runner(STATUS))[0])
            online = copy.deepcopy(STATUS); online['Self']['Online'] = True
            self.assertTrue(verify_tailscale_peer(TARGET, runner(online))[0])
            self.assertTrue(verify_tailscale_peer('127.0.0.1', runner(STATUS))[0])

    def test_default_runner_uses_bounded_exact_target_ping(self):
        def execute(args, **kwargs):
            if args[1:] == ['status', '--json']:
                return SimpleNamespace(returncode=0, stdout=json.dumps(STATUS), stderr='')
            self.assertEqual(args[1:], ['ping', '--c', '1', '--timeout', '2s', TARGET])
            self.assertEqual(kwargs['timeout'], 3)
            return SimpleNamespace(returncode=0, stdout=pong(TARGET)[1], stderr='')
        with patch('sms_bridge.find_tailscale_bin', return_value='synthetic-tailscale'), patch('sms_bridge.subprocess.run', side_effect=execute):
            self.assertTrue(verify_tailscale_peer(TARGET)[0])


if __name__ == '__main__':
    unittest.main()
