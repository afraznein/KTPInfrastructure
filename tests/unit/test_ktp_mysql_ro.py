"""ktp_mysql_ro must refuse to query unless the server itself says the login is SELECT-only.

The defect this guards against: a read-only control proved by the ABSENCE of an error.
A write that succeeds prints nothing on the mysql CLI, so silence and refusal look the
same, and an estate probe once created a table in production that way. Every test
below that expects a refusal feeds output that is plausible and wrong; PROOF_OK is
real output captured from MySQL 8.0.46 for a ktp_ro login made by the staged migration.
"""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from scripts import ktp_mysql_ro as ro

PROOF_OK = (
    "ERROR 1193 (HY000) at line 1: Unknown system variable 'ktp_ro_no_such_variable'\n"
    "IDENTITY=ktp_ro@localhost\n"
    "GRANT USAGE ON *.* TO `ktp_ro`@`localhost`\n"
    "GRANT SELECT ON `hlstatsx`.* TO `ktp_ro`@`localhost`\n"
)
ERR = "ERROR 1193 (HY000) at line 1: Unknown system variable 'ktp_ro_no_such_variable'\n"


def _with(*grant_lines, identity="ktp_ro@localhost", err=ERR):
    return err + f"IDENTITY={identity}\n" + "".join(g + "\n" for g in grant_lines)


class ProofTests(unittest.TestCase):
    def test_real_select_only_output_passes(self):
        self.assertEqual(ro.proof_problems(PROOF_OK), [])

    def test_show_view_is_allowed(self):
        out = _with("GRANT USAGE ON *.* TO `ktp_ro`@`localhost`",
                    "GRANT SELECT, SHOW VIEW ON `hlstatsx`.* TO `ktp_ro`@`localhost`")
        self.assertEqual(ro.proof_problems(out), [])

    def test_all_privileges_is_refused(self):
        out = _with("GRANT USAGE ON *.* TO `ktp_ro`@`localhost`",
                    "GRANT ALL PRIVILEGES ON `hlstatsx`.* TO `ktp_ro`@`localhost`")
        self.assertTrue(any("ALL PRIVILEGES" in p for p in ro.proof_problems(out)))

    def test_one_write_privilege_beside_select_is_refused(self):
        out = _with("GRANT SELECT, INSERT ON `hlstatsx`.* TO `ktp_ro`@`localhost`")
        self.assertTrue(any("INSERT" in p for p in ro.proof_problems(out)))

    def test_global_write_privilege_is_refused(self):
        out = _with("GRANT SELECT, UPDATE ON *.* TO `ktp_ro`@`localhost`")
        self.assertTrue(ro.proof_problems(out))

    def test_grant_option_is_refused(self):
        out = _with("GRANT SELECT ON `hlstatsx`.* TO `ktp_ro`@`localhost` WITH GRANT OPTION")
        self.assertTrue(ro.proof_problems(out))

    def test_role_grant_is_refused(self):
        out = _with("GRANT SELECT ON `hlstatsx`.* TO `ktp_ro`@`localhost`",
                    "GRANT `writer`@`%` TO `ktp_ro`@`localhost`")
        self.assertTrue(ro.proof_problems(out))

    def test_wrong_identity_is_refused(self):
        out = _with("GRANT SELECT ON `hlstatsx`.* TO `ktp_ro`@`localhost`",
                    identity="root@localhost")
        self.assertTrue(any("identity" in p for p in ro.proof_problems(out)))

    def test_missing_discriminator_is_refused(self):
        out = _with("GRANT SELECT ON `hlstatsx`.* TO `ktp_ro`@`localhost`", err="")
        self.assertTrue(any("silent answer" in p for p in ro.proof_problems(out)))

    def test_empty_output_is_refused_not_passed(self):
        self.assertGreaterEqual(len(ro.proof_problems("")), 3)

    def test_no_select_grant_is_refused(self):
        out = _with("GRANT USAGE ON *.* TO `ktp_ro`@`localhost`")
        self.assertTrue(any("no SELECT grant" in p for p in ro.proof_problems(out)))

    def test_login_failure_is_refused(self):
        out = "ERROR 1698 (28000): Access denied for user 'ktp_ro'@'localhost'\n"
        self.assertTrue(ro.proof_problems(out))


class RunTests(unittest.TestCase):
    def _exec(self, proof_out, query=("n\n1\n", "", 0)):
        calls = []

        def exec_(cmd, stdin_text):
            calls.append((cmd, stdin_text))
            return (proof_out, "", 0) if cmd == ro.PROOF_CMD else query
        return exec_, calls

    def _run(self, *a, **k):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            rc = ro.run(*a, **k)
        return rc, out.getvalue()

    def test_failed_proof_never_sends_the_query(self):
        exec_, calls = self._exec(_with("GRANT ALL PRIVILEGES ON `hlstatsx`.* TO `ktp_ro`@`localhost`"))
        rc, _ = self._run("SELECT 1", exec_)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in calls], [ro.PROOF_CMD])

    def test_passed_proof_sends_query_as_ktp_ro_with_a_time_bound(self):
        exec_, calls = self._exec(PROOF_OK)
        rc, out = self._run("SELECT COUNT(*) n FROM ktp_matches;", exec_, max_ms=5000)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "n\n1\n")
        cmd, stdin_text = calls[1]
        self.assertTrue(cmd.startswith("runuser -u ktp_ro -- mysql"))
        self.assertTrue(stdin_text.startswith("SET SESSION max_execution_time=5000;\n"))

    def test_mysql_error_is_exit_1(self):
        exec_, _ = self._exec(PROOF_OK, query=("", "ERROR 1146 (42S02) ...\n", 1))
        self.assertEqual(self._run("SELECT x FROM nope", exec_)[0], 1)

    def test_prove_only_sends_nothing_else(self):
        exec_, calls = self._exec(PROOF_OK)
        self.assertEqual(self._run(None, exec_)[0], 0)
        self.assertEqual(len(calls), 1)

    def test_proof_runs_as_ktp_ro_not_the_ssh_user(self):
        self.assertTrue(ro.PROOF_CMD.startswith("runuser -u ktp_ro -- mysql"))
        self.assertTrue(ro.QUERY_CMD.startswith("runuser -u ktp_ro -- mysql"))


if __name__ == "__main__":
    unittest.main()
