# stubby (server under test)

The canonical DNS-over-TLS **stub resolver daemon** (getdns). Local Alpine
3.22 build (`stubby 0.4.3-r2`, no official image exists) — same pattern as
the nsd module. Listens on plain Do53 for clients; everything upstream goes
over DoT with strict authentication.

## Capability verification (0.4.3)

- **DoT upstream (strict)**: `GETDNS_TRANSPORT_TLS` +
  `GETDNS_AUTHENTICATION_REQUIRED` + `tls_auth_name` + `tls_ca_file` (lab
  CA) against the DoT-only `lab-auth-dot` upstream returns the marker TXT
  `"dot"`. With a wrong CA resolution fails, proving strict validation.
- **No DoT listener** — stubby is a stub daemon with a plaintext front;
  `dot_listener: false`, listener checks SKIP. `dot_client: true` — this
  is the tier-1 counterpart to the `windows-client-dot` EC2 module.

## Notes

- The global profile points `tls_ca_file` at the Alpine system bundle
  (`/etc/ssl/certs/ca-certificates.crt`) unless `upstream_ca` is supplied.
- `appdata_dir: /tmp` keeps getdns state writable regardless of user.
