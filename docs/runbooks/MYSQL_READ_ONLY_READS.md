# Read-only MySQL reads on the data server

**Use `scripts/ktp_mysql_ro.py`, which reads as `ktp_ro`, a login that can only SELECT.**
Do not prove a session is read-only with a session flag, and never by the absence of an
error.

## Why a session flag is not the control

`SET SESSION TRANSACTION READ ONLY` is a request the SQL makes of its own session.
Measured on MySQL 8.0.46, the data server's version, in a throwaway container:

| In a session that ran `SET SESSION TRANSACTION READ ONLY`, as root | Result |
|---|---|
| `INSERT` into InnoDB, `INSERT` into MyISAM | ERROR 1792 |
| `CREATE TABLE`, `CREATE DATABASE`, `DROP TABLE`, `CREATE TEMPORARY TABLE`, `CREATE USER` | ERROR 1792 |
| `SET GLOBAL ...` | **succeeds** |
| `SET SESSION TRANSACTION READ WRITE`, then `INSERT` | **writes** |
| `SET SESSION transaction_read_only = 0`, then `INSERT` | **writes** |
| `START TRANSACTION READ WRITE`, then `INSERT`, `COMMIT` | **writes** |
| same, with the flag set by `mysql --init-command` | **writes** |

So the flag does bind root, but only on a path that sends it, and only until the same
session takes it back. A path that never sends it is plain read-write: that is how a
probe created a table in production while reading the silence as a refusal. On the
`mysql` CLI a write that succeeds prints **nothing**, so a refusal and a success are
indistinguishable unless you require the error text to be present.

A login granted only `SELECT` refuses every one of those writes with **ERROR 1142**,
including after `START TRANSACTION READ WRITE`, and cannot `CREATE TEMPORARY TABLE`
(ERROR 1044) or `SELECT ... INTO OUTFILE` (ERROR 1227). That holds whatever the SQL
says, which is what a control has to do.

## The login

`ktp_ro@localhost`: `GRANT SELECT ON hlstatsx.*`, nothing else, and **no password** —
it authenticates with `auth_socket`, so only the OS account `ktp_ro` can log in as it,
over the local socket. A root shell reaches it with:

```bash
runuser -u ktp_ro -- mysql --batch hlstatsx
```

It is created by an operator-applied migration plus one `useradd`; the SQL, the apply
steps and a VERIFY file that requires each refusal's error text to be present live in
the operator's migration queue, not in this repo.

## The helper

```bash
python scripts/ktp_mysql_ro.py query.sql      # one read
python scripts/ktp_mysql_ro.py --prove-only   # just the proof
```

Before sending anything it asks the server, over the same connection, and requires each
answer to be present:

1. `CURRENT_USER()` is exactly `ktp_ro@localhost`;
2. every `SHOW GRANTS` line grants nothing beyond `USAGE`, `SELECT`, `SHOW VIEW`
   (an `ALL PRIVILEGES`, a write privilege, `WITH GRANT OPTION` or a role grant fails);
3. a statement the server cannot run comes back as ERROR 1193 — otherwise a transport
   that swallows errors would make 1 and 2 pass on nothing.

Anything missing is exit 2 and the query is never sent. Each read is bounded by
`max_execution_time` (default 10 s, `--max-ms`). Until the login exists the helper
refuses with `runuser: user ktp_ro does not exist`, which is the intended direction.

## Writing your own probe

* Prefer the narrower credential. Reaching for root because it connects is how a
  read-only brief acquires write capability it never needed.
* Assert on a **present, expected** error string (`ERROR 1142`), and treat empty output
  as a failed control.
* Show the harness reports errors at all, with a statement that must fail.
* Make any deliberate write-probe a zero-row statement (`DELETE ... WHERE 1 = 0`) — the
  privilege check fires when the table is opened, so a correct grant still answers
  1142, and a wrong one changes nothing.
