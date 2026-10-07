"""Where the crashreporter gets its relay secret, and what happens when it can't.

The daemon kept its own `RELAY_SECRET` in `/etc/ktp/crashreporter.conf`. When the
relay secret rotated into `/etc/ktp/discord-relay.conf`, that copy was left
behind on all five game hosts, so every crash alert since has been answered 401
and dropped after five retries — the core captured, the `.bt` written, nothing
posted. `ktp-scheduled-restart.sh` had already been moved to sourcing
`AUTH_SECRET` from the shared conf for this exact reason; this daemon had not.

So the precedence is the behaviour worth pinning, not an implementation detail:
the shared conf WINS over a local copy, and disagreement is reported rather than
silently preferred either way.

Fixture values here are invented; nothing is read from a real conf.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DAEMON = REPO / "monitoring" / "crashreporter" / "report_core.py"

LOCAL = 'RELAY_URL="https://relay.invalid/reply"\nCRASHES_CHANNEL_ID="1"\nKTP_REGION="ATL"\n'


def load_daemon():
    """Import report_core.py without its `requests` dependency installed."""
    if "requests" not in sys.modules:
        stub = types.ModuleType("requests")
        stub.RequestException = type("RequestException", (Exception,), {})
        stub.post = lambda *a, **k: None
        sys.modules["requests"] = stub
    spec = importlib.util.spec_from_file_location("ktp_report_core", DAEMON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def daemon():
    return load_daemon()


def write(tmp_path, local_extra="", shared=None):
    conf = tmp_path / "crashreporter.conf"
    conf.write_text(LOCAL + local_extra, encoding="utf-8")
    shared_path = tmp_path / "discord-relay.conf"
    if shared is not None:
        shared_path.write_text(shared, encoding="utf-8")
    return str(conf), str(shared_path)


def call(daemon, monkeypatch, conf, shared_path):
    monkeypatch.setattr(daemon, "SHARED_RELAY_CONF", shared_path)
    return daemon.load_config(conf)


def test_shared_conf_wins_over_the_local_copy(daemon, monkeypatch, tmp_path, capsys):
    conf, shared = write(tmp_path,
                         local_extra='RELAY_SECRET="stale-from-before-the-rotation"\n',
                         shared='AUTH_SECRET="current-shared-value"\n')
    cfg = call(daemon, monkeypatch, conf, shared)
    assert cfg["RELAY_SECRET"] == "current-shared-value"
    err = capsys.readouterr().err
    # Disagreement is said out loud, and the log names the FILE, never the value.
    assert "disagrees" in err
    assert "stale-from-before-the-rotation" not in err
    assert "current-shared-value" not in err


def test_local_copy_is_used_when_the_shared_conf_has_no_secret(daemon, monkeypatch, tmp_path):
    conf, shared = write(tmp_path, local_extra='RELAY_SECRET="only-local"\n',
                         shared="# nothing here\n")
    assert call(daemon, monkeypatch, conf, shared)["RELAY_SECRET"] == "only-local"


def test_local_copy_is_used_when_the_shared_conf_is_absent(daemon, monkeypatch, tmp_path):
    conf, shared = write(tmp_path, local_extra='RELAY_SECRET="only-local"\n', shared=None)
    assert not Path(shared).exists()
    assert call(daemon, monkeypatch, conf, shared)["RELAY_SECRET"] == "only-local"


def test_shared_conf_alone_is_enough(daemon, monkeypatch, tmp_path):
    """A host provisioned without a local RELAY_SECRET must still start."""
    conf, shared = write(tmp_path, shared='AUTH_SECRET="shared-only"\n')
    assert call(daemon, monkeypatch, conf, shared)["RELAY_SECRET"] == "shared-only"


def test_no_secret_anywhere_exits_2_and_names_both_sources(daemon, monkeypatch, tmp_path, capsys):
    conf, shared = write(tmp_path, shared="# empty\n")
    with pytest.raises(SystemExit) as exc:
        call(daemon, monkeypatch, conf, shared)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "AUTH_SECRET" in err and "RELAY_SECRET" in err


def test_a_missing_non_secret_key_still_exits_2(daemon, monkeypatch, tmp_path):
    """Control: dropping RELAY_SECRET from the required list must not drop the rest."""
    conf = tmp_path / "crashreporter.conf"
    conf.write_text('CRASHES_CHANNEL_ID="1"\nKTP_REGION="ATL"\n', encoding="utf-8")
    shared = tmp_path / "discord-relay.conf"
    shared.write_text('AUTH_SECRET="x"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        call(daemon, monkeypatch, str(conf), str(shared))
    assert exc.value.code == 2


def test_quoting_styles_both_parse(daemon, monkeypatch, tmp_path):
    conf, shared = write(tmp_path, shared="AUTH_SECRET='single-quoted'\n")
    assert call(daemon, monkeypatch, conf, shared)["RELAY_SECRET"] == "single-quoted"
