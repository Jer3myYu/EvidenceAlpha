"""Normal command preserves an explicitly selected virtual environment."""

from evidencealpha import execution


def test_execution_keeps_virtual_environment_interpreter(tmp_path):
    base = tmp_path / "base-python"
    base.write_text("placeholder")
    selected = tmp_path / "venv" / "bin" / "python"
    selected.parent.mkdir(parents=True)
    selected.symlink_to(base)
    spec = {"settings": {"dense_python": "venv/bin/python"}}
    result = execution._paths(spec, tmp_path)
    assert result["settings"]["dense_python"] == str(selected)
    assert result["settings"]["dense_python"] != str(base)


def test_stop_prevents_queued_process_launch(tmp_path, monkeypatch):
    import sys
    import threading
    import pytest
    from evidencealpha import config
    from evidencealpha import providers

    monkeypatch.setattr(providers, "_STOP_REQUESTED", threading.Event())
    providers.cancel_all(stop_new=True)
    marker = tmp_path / "unexpected"
    request = providers.Request(
        "cancel-test",
        "",
        config.ModelSettings("codex", "unused"),
        tmp_path,
        5,
    )
    with pytest.raises(providers.ProviderCancelled):
        providers.execute(
            [sys.executable, "-c", "open('unexpected', 'w').write('bad')"],
            request,
        )
    assert not marker.exists()
