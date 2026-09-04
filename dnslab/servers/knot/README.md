# knot — Knot DNS (authoritative) under test

Authoritative-only server module. Serves its own copy of `lab.test` with
lab-auth's transport-marker convention (TXT `"do53"` in the zone the Do53
profiles load, `"dot"` in the DoT-only profile's zone), so it doubles as an
authoritative-over-DoT target with the same marker semantics the checks
already understand.

## Pinned image / verified version

- Image: `cznic/knot:v3.5.4`
- Verified: `docker run --rm --entrypoint knotd cznic/knot:v3.5.4 --version`
  → `knotd, Knot DNS 3.5.4`
- The image has **no entrypoint** (default Cmd is just `bash`), so the
  manifest overrides `command: ["knotd", "-c", "/dnslab/config/knot.conf"]`
  to run knotd in the foreground (PID 1, logs to stdout).

## DoT listener verdict: native, works

Knot DNS gained a general (plain TCP, non-XDP) TLS listener in 3.4:
`server: listen-tls: <addr>@<port>` with `server: cert-file:` /
`server: key-file:`. Verified on the pinned 3.5.4 image:

- `knotc conf-check` accepts `listen-tls` + `cert-file`/`key-file`.
- Startup log: `binding to TLS interface 0.0.0.0@853` — an ordinary socket
  bind, no XDP capability or host privileges needed.
- `dot-query` and `cert` checks PASS against the lab CA (kdig cross-check
  agrees).

XDP/QUIC is a separate, unrelated subsystem (`xdp:` section) and is not
used here. `dot_upstream_forwarding` is `false`: knotd is authoritative
only and never forwards.

## Profiles

| profile     | listeners   | zone file            | marker  |
|-------------|-------------|----------------------|---------|
| `auth-do53` | do53        | `lab.test.do53.zone` | `do53`  |
| `auth-dot`  | dot         | `lab.test.dot.zone`  | `dot`   |
| `auth-both` | do53 + dot  | `lab.test.do53.zone` | `do53`  |

`auth-dot` has **no** `listen:` line at all, so nothing serves plain 53 —
transport isolation by construction, like lab-auth-dot. `auth-both` proves
listener coexistence only; both transports answer from the same zone copy,
so its marker is `do53` on either transport (use the isolated profiles for
marker-based transport proofs). `default_profile` is `auth-dot`.

## Read-only mounts / writable-state quirks

Config and zones are bind-mounted read-only, so everything knotd wants to
write is redirected to `/tmp` (writable in the container, runs as root):

- `server: rundir: /tmp` — pidfile and the control socket
  (`/tmp/knot.sock`; the control socket cannot be disabled, unlike NSD's
  `control-enable: no`, so it must land somewhere writable).
- `database: storage: /tmp` — timer/catalog LMDB databases.
- Zone template: `zonefile-sync: -1` (never write the zonefile back),
  `zonefile-load: whole`, `journal-content: none` (no journal), with
  `storage:` pointing at the read-only `/dnslab/zones` mount for loading.

## Lint

`manifest.yaml` sets `lint: "knotc --config {config} conf-check"`, so
`python -m dnslab.selfcheck knot` syntax-checks every rendered profile
when `knotc` is on the host PATH (note: `--config` must precede the
`conf-check` action; `conf-check -c <file>` is not accepted).
