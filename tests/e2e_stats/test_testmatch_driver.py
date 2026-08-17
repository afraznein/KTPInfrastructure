import pytest

from tests.integration.match_flow import MatchDriver, MatchDriverError


class FakeHandle:
    def __init__(self, match_id="1700000000-TEST"):
        self.match_id = match_id
        self.commands = []

    def rcon(self, command):
        self.commands.append(command)
        if command.startswith("amx_ktp_testmatch"):
            if command == "amx_ktp_testmatch_status":
                return "KTP_TESTMATCH: LIVE match_id=1700000000-TEST bots_per_team=6"
            return "KTP_TESTMATCH: FILLING target_per_team=6"
        if command == "amx_ktp_test_get_state":
            return (
                'KTP_TEST_STATE: {"mt":0,"h":1,"l":1,"p":0,'
                f'"id":"{self.match_id}","s1":0,"s2":0,"tb1":300,'
                '"tb2":300,"pn":0,"c1":"A","c2":"B","rc":6}'
            )
        raise AssertionError(command)


def test_testmatch_uses_one_orchestrator_command_and_returns_test_id():
    handle = FakeHandle()
    assert MatchDriver(handle).testmatch(per_team=6) == "1700000000-TEST"
    assert handle.commands == [
        "amx_ktp_testmatch 6",
        "amx_ktp_testmatch_status",
        "amx_ktp_test_get_state",
    ]


def test_testmatch_rejects_any_non_test_match_id():
    with pytest.raises(MatchDriverError, match="non-test match_id"):
        MatchDriver(FakeHandle("1700000000-NY1")).testmatch()


def test_testmatch_surfaces_asynchronous_plugin_failure():
    class FailedHandle(FakeHandle):
        def rcon(self, command):
            if command == "amx_ktp_testmatch_status":
                return "KTP_TESTMATCH: ERROR reason=production_ktp_start_rejected"
            return super().rcon(command)

    with pytest.raises(MatchDriverError, match="production_ktp_start_rejected"):
        MatchDriver(FailedHandle()).testmatch()
