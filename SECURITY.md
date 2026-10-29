# Security policy

## Supported versions

Security fixes are applied to the latest release on the `main` branch.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private
vulnerability reporting instead: open the **Security** tab of this repository and choose
**Report a vulnerability**. You will get an acknowledgement within a few days.

## Security model

QueryDoctor is a local developer tool. Its safety rests on four layers:

1. **Read-only SQL.** Every query is parsed with sqlglot and must be a single `SELECT`
   (or `WITH ... SELECT` / `UNION`). Anything else, including `PRAGMA`, `ATTACH`,
   `load_extension()`, writes and multiple statements, is rejected before execution.
2. **A private copy.** Analysis runs on a copy of the database made with SQLite's backup API.
   The original file is opened read-only (`mode=ro`) and is never modified.
3. **Query-only connection.** While user SQL runs in the sandbox, the connection has
   `PRAGMA query_only = ON`, so even a validator bypass could not write.
4. **Fixed database path.** The dashboard API never accepts a file path from the browser.
   The database is chosen at server start, which rules out path traversal.

## Things to know

- The dashboard has **no authentication**. It binds to `127.0.0.1` by default. Do not expose it
  to a network without putting an authenticating reverse proxy in front of it.
- Only one analysis runs at a time; a second request receives HTTP 429.
- Query text is sent to your own server only. QueryDoctor makes no outbound network calls and
  needs no API keys.
