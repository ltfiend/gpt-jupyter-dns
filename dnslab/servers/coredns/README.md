# CoreDNS (server under test)

CoreDNS — plugin-based DNS server, the Kubernetes default resolver. Pinned
image `coredns/coredns:1.14.7` (entrypoint `/coredns`, runs as nonroot
65532; unprivileged :53/:853 binds are fine under Docker defaults).

## Capability verification (1.14.7)

- **DoT listener**: `tls://zone:853` server block with `tls CERT KEY`;
  validated by dnspython and kdig against the lab CA.
- **DoT upstream**: `forward . tls://IP { tls_servername <name>; tls <CA> }`
  (the one-argument `tls` form is "CA used to validate the server") against
  the DoT-only `lab-auth-dot` upstream returns the marker TXT `"dot"`.
  With a wrong CA the forward fails, proving validation is enforced.

## Notes / limitations

- The forward plugin takes **one `tls_servername` per block**, so the
  `global-forwarder-dot` profile uses only the FIRST configured upstream —
  multiple DoT upstreams with different certificate names cannot share a
  block. This is a CoreDNS limitation, noted in the manifest capabilities.
- `tls` with zero arguments selects the system CA store (used when no
  `upstream_ca` is supplied to the global profile).
