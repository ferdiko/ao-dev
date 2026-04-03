from pathlib import Path

from sovara.server.graph_analysis import inference_server


def test_start_spawns_inference_server_process_and_stop_terminates_it(monkeypatch, tmp_path):
    popen_calls = []

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.wait_calls = []

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    fake_process = FakeProcess()

    def fake_popen(args, stdout=None, stderr=None, close_fds=None):
        popen_calls.append(
            {
                "args": args,
                "stdout": stdout,
                "stderr": stderr,
                "close_fds": close_fds,
            }
        )
        return fake_process

    monkeypatch.setattr("sovara.common.constants.HOST", "127.0.0.1")
    monkeypatch.setattr("sovara.common.constants.INFERENCE_PORT", 6124)
    monkeypatch.setattr("sovara.common.constants.INFERENCE_SERVER_LOG", str(tmp_path / "inference_server.log"))
    monkeypatch.setattr(inference_server.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(inference_server, "_is_inference_server_running", lambda host, port, timeout=1.0: False)
    inference_server._process = None

    try:
        inference_server.start()

        assert len(popen_calls) == 1
        assert popen_calls[0]["args"][-4:] == ["--host", "127.0.0.1", "--port", "6124"]
        assert Path(tmp_path / "inference_server.log").exists()

        inference_server.start()
        assert len(popen_calls) == 1

        inference_server.stop()
        assert fake_process.terminated is True
        assert fake_process.killed is False
        assert inference_server._process is None
    finally:
        inference_server._process = None


def test_start_reuses_existing_healthy_inference_server(monkeypatch, tmp_path):
    popen_calls = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        raise AssertionError("start() should not spawn when inference server is already healthy")

    monkeypatch.setattr("sovara.common.constants.HOST", "127.0.0.1")
    monkeypatch.setattr("sovara.common.constants.INFERENCE_PORT", 6124)
    monkeypatch.setattr("sovara.common.constants.INFERENCE_SERVER_LOG", str(tmp_path / "inference_server.log"))
    monkeypatch.setattr(inference_server, "_is_inference_server_running", lambda host, port, timeout=1.0: True)
    monkeypatch.setattr(inference_server.subprocess, "Popen", fake_popen)
    inference_server._process = None

    try:
        inference_server.start()
        assert popen_calls == []
        assert inference_server._process is None
    finally:
        inference_server._process = None


def test_stop_terminates_untracked_inference_server_from_pid_file(monkeypatch, tmp_path):
    pid_file = tmp_path / "inference_server.pid"
    pid_file.write_text("54321\n", encoding="utf-8")

    terminated = []

    monkeypatch.setattr("sovara.common.constants.INFERENCE_SERVER_PID", str(pid_file))
    monkeypatch.setattr(inference_server, "_pid_is_alive", lambda pid: pid == 54321)
    monkeypatch.setattr(inference_server, "_terminate_pid", lambda pid, timeout=5.0: terminated.append((pid, timeout)))
    inference_server._process = None

    inference_server.stop()

    assert terminated == [(54321, 5.0)]
    assert not pid_file.exists()
