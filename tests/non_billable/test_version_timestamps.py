from sovara.server.state import ServerState


def test_git_commit_timestamps_are_serialized_as_naive_utc_strings():
    assert (
        ServerState._serialize_git_commit_timestamp("2026-03-25T22:07:00+04:00")
        == "2026-03-25 18:07:00"
    )


def test_git_commit_timestamp_serializer_rejects_invalid_strings():
    assert ServerState._serialize_git_commit_timestamp("Version Mar 25, 22:07") is None
