# nsd — NLnet Labs NSD as authoritative server-under-test

**Image:** built locally (`dnslab/nsd:local`) from `alpine:3.22` because
NLnet Labs publishes no official NSD image on Docker Hub
(`docker manifest inspect nlnetlabs/nsd` → denied/not found).
**Verified version:** `nsd-4.12.0-r0` (Alpine 3.22 `main` apk), run as
`nsd -d -c /dnslab/config/nsd.conf` (foreground).

NSD is **authoritative-only**: no recursion, no forwarding, so
`dot_upstream_forwarding: false` and the `dot-upstream` check SKIPs by
role. It *does* have a native DoT listener (since NSD 4.3.11).

## TLS directives (exact)

```
server:
    tls-service-key: "/dnslab/certs/<instance>.key"
    tls-service-pem: "/dnslab/certs/<instance>.pem"
    tls-port: 853
    interface: 0.0.0.0@853
```

The rule (verified live): **any `interface:` whose port equals `tls-port`
serves TLS; every other interface stays plain DNS.** There is no
per-interface TLS flag in NSD — transport is selected purely by port
matching against `tls-port`.

## Profiles

| profile | listeners | zone file | marker TXT |
|---|---|---|---|
| `auth-do53` | 53/udp+tcp only | `lab.test.do53.zone` | `"do53"` |
| `auth-dot` | 853/TLS only | `lab.test.dot.zone` | `"dot"` |
| `auth-both` (default) | 53 **and** 853/TLS simultaneously | `lab.test.do53.zone` | `"do53"` |

`auth-both` is the realistic production shape (plain + TLS at once). It
serves a single zone copy, so the marker reads `"do53"` on *both*
transports — with one zone there is nothing transport-specific to prove;
use the transport-isolated profiles (or the framework's lab-auth pair)
for marker-based transport proofs.

## Quirks

- `database: ""` disables the legacy zone database (NSD 4 style); with
  `zonefiles-write: 0` the read-only zones mount is never written to.
- `username: ""` keeps NSD from switching to the `nsd` user, which would
  fail reading the bind-mounted key owned by the host user.
- Do53-only profile: omitting all TLS directives is enough; `tls-port`
  defaults to 853 but without `tls-service-key/pem` no TLS is served.
- `interface:` may be repeated; a bare `interface: 0.0.0.0` takes the
  global `port:` (53), `interface: 0.0.0.0@853` overrides per-interface.
- NSD answers `REFUSED` for anything outside its zones — checks here only
  query `lab.test`, which it owns.
