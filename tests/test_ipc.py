import socket
import threading
import time
import unittest

from core.ipc import DaemonState, IpcClient, IpcServer


class IpcTests(unittest.TestCase):
    def setUp(self):
        self.state = DaemonState(platform="Linux", observe_only=True, armed=False)
        self.server = IpcServer(self.state, endpoint=("tcp", "127.0.0.1", 0))
        self.server.start_background()

        deadline = time.time() + 2
        while self.server.address is None and time.time() < deadline:
            time.sleep(0.01)

        assert self.server.address is not None
        _kind, host, port = self.server.address
        self.client = IpcClient(endpoint=("tcp", host, port))

    def tearDown(self):
        self.server.stop()

    def test_ping(self):
        self.assertTrue(self.client.ping())

    def test_get_state(self):
        self.state.update(cpu_percent=42.0, stress_score=0.42, level="MODERATE")
        state = self.client.get_state()
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state["cpu_percent"], 42.0)
        self.assertEqual(state["stress_score"], 0.42)
        self.assertEqual(state["level"], "MODERATE")
        self.assertTrue(state["observe_only"])

    def test_set_mode(self):
        state = self.client.set_mode("Gaming")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state["mode"], "Gaming")

    def test_set_armed_and_observe_only(self):
        armed_state = self.client.set_armed(True)
        observe_state = self.client.set_observe_only(False)
        self.assertTrue(armed_state["armed"])
        self.assertFalse(observe_state["observe_only"])

    def test_invalid_command(self):
        response = self.client.request({"type": "unknown"})
        self.assertFalse(response["ok"])


if __name__ == "__main__":
    unittest.main()
