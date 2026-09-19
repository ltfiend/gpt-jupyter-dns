# dnsdist (server under test)

PowerDNS dnsdist — a DNS proxy / load balancer, the only non-resolver
forwarder in the roster. Pinned image `powerdns/dnsdist-20:2.0.9`.

## Capability verification (2.0.9)

- **DoT listener**: `addTLSLocal('0.0.0.0:853', cert, key)` serves TLS with
  the lab-issued cert; validated by dnspython and kdig against the lab CA.
- **DoT upstream**: `newServer({tls='openssl', subjectName=..., caStore=lab
  CA, validateCertificates=true})` against the DoT-only `lab-auth-dot`
  upstream returns the `transport-marker.lab.test TXT "dot"` — TLS proven by
  answer content. With a wrong CA the backend health check fails closed
  (SERVFAIL to clients), proving validation is enforced.

## Notes

- The image entrypoint execs `dnsdist --supervised --disable-syslog <args>`;
  the manifest passes only `-C <config>`.
- Lab profiles pin the backend health check to `lab.test/SOA` because the
  auth-only lab upstreams would fail dnsdist's default `a.root-servers.net`
  probe and be marked down.
- dnsdist proxies everything to its backend pool; there is no per-zone
  forwarding in these profiles.
