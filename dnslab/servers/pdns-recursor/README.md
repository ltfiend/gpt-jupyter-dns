# PowerDNS Recursor (server under test)

Pinned image `powerdns/pdns-recursor-53:5.3.10`. New-style YAML config
(old-style removed in 5.2); the entrypoint wrapper execs
`pdns_recursor --disable-syslog --config-dir=/dnslab/config`, reading
`recursor.yml` from the mounted directory.

## Capability verification (5.3.10)

- **DoT upstream**: `forward_zones` to `IP:853` with
  `outgoing.dot_to_port_853: true` reaches the DoT-only `lab-auth-dot`
  upstream and returns the marker TXT `"dot"` — TLS proven by answer
  content (that upstream has no port 53 at all).
- **No DoT listener** — by design: PowerDNS delegates TLS termination to
  dnsdist. `dot_listener: false`, so listener checks SKIP honestly. Pair
  with the `dnsdist` module for the full PowerDNS DoT stack.

## Limitation worth knowing

Outgoing DoT to forwarders performs **no certificate validation** (no
CA/hostname knob exists for forwarders as of 5.3). The lab marker test
proves the transport is TLS, but the upstream is not authenticated;
`upstream_ca` passed to `dnslab.start()` has no effect for this server.
