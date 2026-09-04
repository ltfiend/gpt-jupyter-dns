# unbound — recursive resolver / forwarder with native DoT both ways

## Image

Built locally from `alpine:3.22` (`build: docker`, tag `dnslab/unbound:local`),
giving **Unbound 1.23.1** compiled `--with-ssl` (OpenSSL 3.5.x, libevent).

Why not a pinned upstream image:

- `nlnetlabs/unbound` **does not exist** on Docker Hub (object not found).
- `mvance/unbound` (latest pin would be `1.22.0`) is Debian-based and its
  entrypoint bakes in `/opt/unbound/etc/unbound/unbound.conf` plus its own
  bootstrap; fighting that layout buys nothing over the 8 MB Alpine build,
  which also matches the lab-auth pattern (no external image availability
  risk for CI).

The Dockerfile `CMD` runs `unbound -d -c /dnslab/config/unbound.conf`
(`-d` = stay in foreground), so no manifest `command:` override is needed.

## Config dialect notes (all verified live on 1.23.1)

- **DoT listener**: `interface: 0.0.0.0@853` + `tls-port: 853` +
  `tls-service-key:` / `tls-service-pem:`. Any interface whose port equals
  `tls-port` serves TLS. Verified: dnspython and `kdig +tls-ca` both
  validate the lab cert; SAN and chain check out.
- **DoT upstream forwarding**: `forward-zone` with
  `forward-addr: <ip>@853#<auth-name>` + `forward-tls-upstream: yes`, and
  `tls-cert-bundle: /dnslab/certs/dnslab-ca.pem` in the `server:` clause for
  chain validation of the `#auth-name`. Verified: marker TXT came back
  `"dot"` from the DoT-only lab-auth instance, which has no port 53 at all.
- **RFC 6761 gotcha**: Unbound ships a default `local-zone: "test." static`
  that answers anything under `test.` with NXDOMAIN *before* forward-zones
  are consulted. The forwarder profiles add
  `local-zone: "lab.test." transparent` to punch the lab zone through to
  the forwarder (more surgical than `local-zone: "test." nodefault`).
- **Validation**: `module-config: "iterator"` drops the validator module —
  the lab zone is unsigned and the container has no root trust anchor
  provisioned. `domain-insecure: "lab.test."` is kept in the forwarder
  profiles as belt-and-braces documentation of intent.
- **In-container hygiene**: `username: ""`, `chroot: ""`, `directory: ""`,
  `pidfile: ""` (Alpine builds with empty run-dir/pidfile anyway),
  `do-ip6: no` (the dnslab network is IPv4-only),
  `access-control: 0.0.0.0/0 allow` (Unbound refuses non-localhost clients
  by default). `do-not-query-localhost` is untouched — upstreams are
  sibling containers, not localhost.

## Healthcheck

`health.dnslab.test A` is answered from `local-data` in **every** profile,
so container startup health never depends on upstream reachability or real
recursion. (`lab.test SOA` would deadlock the recursive profile: the
default `test.` zone NXDOMAINs it instantly.)

## Profiles and observed check results

| profile | do53-query | dot-query | cert | forwarding | dot-upstream |
|---|---|---|---|---|---|
| `forwarder-dot` (default) | PASS | PASS | PASS | PASS (`marker='dot'`) | PASS |
| `forwarder-do53` | PASS | PASS | PASS | PASS (`marker='do53'`) | SKIP (profile is not DoT) |
| `recursive` | FAIL* | FAIL* | PASS | FAIL* | SKIP |

\* Expected: the default checks query `lab.test`, which the recursive
profile answers NXDOMAIN from Unbound's built-in RFC 6761 `test.` local
zone — it has no path to the lab zone *by design* (negative control). The
profile itself is healthy: it starts, serves validated TLS on 853 (the
NXDOMAIN arrives over a lab-CA-validated session), and real recursion
works when the sandbox has internet (verified: `example.com A` → NOERROR
with answer).
