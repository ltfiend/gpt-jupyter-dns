# lab-auth — framework-owned transport-isolated upstream pair

Two NSD instances (Alpine, built locally as `dnslab/lab-auth:local`) serving
the same `lab.test` zone with **different transport-marker TXT values**:

| instance | listens | `transport-marker.lab.test TXT` |
|---|---|---|
| `lab-auth-do53` | 53/udp+tcp only | `"do53"` |
| `lab-auth-dot` | 853/TLS only | `"dot"` |

This is how forwarding-over-DoT is *proven* without packet capture:

1. `lab-auth-dot` has no Do53 listener at all — a forwarder pointed at it
   that resolves `lab.test` must have connected over TLS.
2. The marker TXT in the answer identifies which upstream served it, so a
   forwarder silently falling back to its Do53 upstream is caught by
   content, not just connectivity.

Forwarder profiles (`forwarder-do53` / `forwarder-dot` in the per-server
modules) receive both upstreams' addresses in their template context as
`upstream_do53` / `upstream_dot` (host, ip, port, tls_hostname) — the
docker provider fills in live container IPs, so **start `lab-auth` before
starting any forwarder**.

Verified: NSD treats any `interface:` whose port equals `tls-port` as a
TLS listener, giving a TLS-only instance when that is the only interface.
