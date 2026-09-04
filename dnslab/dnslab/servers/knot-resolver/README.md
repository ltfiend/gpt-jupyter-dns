# knot-resolver — Knot Resolver (kresd) 5.x

Pinned image: **`cznic/knot-resolver:v5.7.8`** — config dialect: **5.x lua**
(`kresd -c kresd.conf`), chosen over 6.x, whose YAML config requires the
separate manager process; 5.x is a single kresd process with one lua file,
which fits the one-container / one-bind-mounted-config model directly.

## How it is launched (verified on the pinned image)

- Image entrypoint is `/usr/sbin/kresd` and the container runs as **root**,
  so the manifest `command` is *argv appended to the entrypoint*, not a full
  command line: `["-c", "/dnslab/config/kresd.conf", "-n", "/tmp"]`.
- `-n` (non-interactive) is mandatory: without it kresd starts a stdin REPL,
  which gets EOF in a detached container.
- The trailing `/tmp` is kresd's *rundir* positional argument. The LMDB
  cache is created in the rundir, the default rundir is `.` (= `/`), and the
  image has **no `/var/cache/knot-resolver`** — pointing the rundir at
  `/tmp` gives the cache a writable home with no extra volumes.

## Profiles

| profile | lab.test path | proves |
|---|---|---|
| `recursive` | full recursion + `policy.STUB` of `lab.test` to `upstream_do53` | normal resolver with the lab zone reachable |
| `forwarder-do53` | `policy.STUB` of `lab.test` to `upstream_do53` (plain 53) | negative control: marker TXT `"do53"` |
| `forwarder-dot` | `policy.TLS_FORWARD` of `lab.test` to `upstream_dot` | marker TXT `"dot"` — TLS upstream really used |

All profiles listen on both 53 (`net.listen(..., {kind='dns'})`) and 853
(`net.tls(cert, key)` + `net.listen(..., {kind='tls'})`).

## Verified capability facts (live, against the running lab-auth pair)

- **DoT listener**: native. `net.tls('{{tls_cert_path}}', '{{tls_key_path}}')`
  followed by `net.listen('0.0.0.0', 853, {kind='tls'})`. Passed both the
  dnspython and kdig cross-checked `dot-query` and the `cert` SAN check.
- **DoT upstream forwarding**: native, with CA pinning:

  ```lua
  policy.add(policy.suffix(
      policy.TLS_FORWARD({
          { '<upstream_ip>@853',
            hostname = 'lab-auth-dot.dnslab.test',
            ca_file = '/dnslab/certs/dnslab-ca.pem' },
      }),
      {todname('lab.test')}))
  ```

  Verified end-to-end: marker TXT answered `"dot"` (the DoT-only upstream),
  and the `forwarder-do53` control answered `"do53"`.
  The `ip@port` form inside `TLS_FORWARD` entries is accepted by 5.7.8.

## Quirks / gotchas

- **DNSSEC validation is ON even with an empty config.** kresd is compiled
  with `keyfile_default`, i.e. a built-in root trust anchor — merely *not
  configuring* trust anchors does NOT disable validation. With validation
  on, the real root proves `.test` is undelegated/unsigned, and
  `TLS_FORWARD`ed answers for `lab.test` SERVFAIL as bogus. Every profile
  therefore sets `trust_anchors.set_insecure({'test.'})`. (`policy.STUB`
  paths dodge this by design — STUB skips validation — but the insecure
  mark is kept in all profiles for consistency.)
- `policy.STUB` is the right mode for the *authoritative-only* Do53
  upstream (no recursion expected), but it has no TLS variant in 5.x — DoT
  upstreams must use `policy.TLS_FORWARD`, which does work against the
  authoritative-only NSD upstream for in-zone queries (verified).
- kresd logs nothing at default log level even while SERVFAILing; every
  profile supports a `log_debug` boolean (template-level, via
  `dnslab.start('knot-resolver', profile=..., log_debug=True)`) that adds
  `log_level('debug')` for troubleshooting.
- `config_dialect: lua` in the manifest is informational only (records the
  5.x-vs-6.x decision).
