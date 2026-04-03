from types import SimpleNamespace

from sovara.cli.so_server import execute_server_command, server_command_parser


def test_server_command_parser_usage_mentions_infer_logs():
    parser = server_command_parser()
    assert "infer-logs" in parser.usage
    assert "_clear_cache" in parser.usage


def test_clear_logs_clears_main_and_inference_logs(monkeypatch, tmp_path):
    main_log = tmp_path / "main_server.log"
    inference_log = tmp_path / "inference_server.log"
    main_log.write_text("main log\n")
    inference_log.write_text("inference log\n")

    info_calls = []
    error_calls = []

    class FakeLogger:
        def info(self, message):
            info_calls.append(message)

        def error(self, message):
            error_calls.append(message)

    monkeypatch.setattr("sovara.cli.so_server.MAIN_SERVER_LOG", str(main_log))
    monkeypatch.setattr("sovara.cli.so_server.INFERENCE_SERVER_LOG", str(inference_log))
    monkeypatch.setattr("sovara.cli.so_server.logger", FakeLogger())

    execute_server_command(SimpleNamespace(command="clear-logs"))

    assert main_log.read_text() == ""
    assert inference_log.read_text() == ""
    assert error_calls == []
    assert info_calls == ["Server log files cleared."]


def test_clear_cache_invokes_priors_cache_clear(monkeypatch):
    info_calls = []
    error_calls = []
    clear_calls = []

    class FakeLogger:
        def info(self, message):
            info_calls.append(message)

        def error(self, message):
            error_calls.append(message)

    monkeypatch.setattr("sovara.cli.so_server.logger", FakeLogger())
    monkeypatch.setattr("sovara.cli.so_server._clear_priors_caches", lambda: clear_calls.append(True))

    execute_server_command(SimpleNamespace(command="_clear_cache"))

    assert clear_calls == [True]
    assert error_calls == []
    assert info_calls == ["Priors cache entries cleared."]


def test_stop_also_stops_child_servers(monkeypatch):
    info_calls = []
    warning_calls = []
    stopped_children = []

    class FakeLogger:
        def info(self, message):
            info_calls.append(message)

        def warning(self, message):
            warning_calls.append(message)

    monkeypatch.setattr("sovara.cli.so_server.logger", FakeLogger())
    monkeypatch.setattr("sovara.cli.so_server._server_http_request", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("sovara.cli.so_server._stop_child_servers", lambda: stopped_children.append(True))
    monkeypatch.setattr("sovara.cli.so_server.time.sleep", lambda _seconds: None)

    execute_server_command(SimpleNamespace(command="stop"))

    assert stopped_children == [True]
    assert warning_calls == []
    assert info_calls == ["Main server stop signal sent."]
