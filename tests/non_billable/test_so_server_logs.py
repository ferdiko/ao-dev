from argparse import Namespace

from sovara.cli import so_server


def test_restart_clears_main_priors_and_inference_logs(tmp_path, monkeypatch):
    main_log = tmp_path / "main_server.log"
    priors_log = tmp_path / "priors_server.log"
    inference_log = tmp_path / "inference_server.log"

    main_log.write_text("main\n", encoding="utf-8")
    priors_log.write_text("priors\n", encoding="utf-8")
    inference_log.write_text("inference\n", encoding="utf-8")

    monkeypatch.setattr(so_server, "MAIN_SERVER_LOG", str(main_log))
    monkeypatch.setattr(so_server, "PRIORS_SERVER_LOG", str(priors_log))
    monkeypatch.setattr(so_server, "INFERENCE_SERVER_LOG", str(inference_log))
    monkeypatch.setattr(so_server, "_server_http_request", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(so_server, "launch_daemon_server", lambda: None)
    monkeypatch.setattr(so_server.time, "sleep", lambda _seconds: None)

    so_server.execute_server_command(Namespace(command="restart"))

    assert main_log.read_text(encoding="utf-8") == ""
    assert priors_log.read_text(encoding="utf-8") == ""
    assert inference_log.read_text(encoding="utf-8") == ""


def test_clear_logs_truncates_all_server_logs(tmp_path, monkeypatch):
    main_log = tmp_path / "main_server.log"
    priors_log = tmp_path / "priors_server.log"
    inference_log = tmp_path / "inference_server.log"

    main_log.write_text("main\n", encoding="utf-8")
    priors_log.write_text("priors\n", encoding="utf-8")
    inference_log.write_text("inference\n", encoding="utf-8")

    monkeypatch.setattr(so_server, "MAIN_SERVER_LOG", str(main_log))
    monkeypatch.setattr(so_server, "PRIORS_SERVER_LOG", str(priors_log))
    monkeypatch.setattr(so_server, "INFERENCE_SERVER_LOG", str(inference_log))

    so_server.execute_server_command(Namespace(command="clear-logs"))

    assert main_log.read_text(encoding="utf-8") == ""
    assert priors_log.read_text(encoding="utf-8") == ""
    assert inference_log.read_text(encoding="utf-8") == ""


def test_start_skips_when_startup_lock_is_fresh(tmp_path, monkeypatch):
    startup_lock = tmp_path / "server.starting.lock"
    startup_lock.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(so_server, "MAIN_SERVER_STARTUP_LOCK", str(startup_lock))
    monkeypatch.setattr(so_server, "MAIN_SERVER_LOG", str(tmp_path / "main_server.log"))
    monkeypatch.setattr(
        so_server.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("launch_daemon_server should not spawn")),
    )

    assert so_server.launch_daemon_server() is False
