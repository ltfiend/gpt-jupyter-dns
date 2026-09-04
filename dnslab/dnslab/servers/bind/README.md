# bind — BIND 9 (ISC) server module

Pinned image: `internetsystemsconsortium/bind9:9.20`
(= **BIND 9.20.24 (Stable Release) \<id:e5d43f1\>** at verification time, 2026-09-03).

## Image quirks

- The image's entrypoint is `["/usr/sbin/named", "-u", "bind"]` and its default
  Cmd is only *arguments* (`-f -c /etc/bind/named.conf -L ...`). The manifest
  `command` therefore contains **arguments, not a full command line**:
  `["-g", "-c", "/dnslab/config/named.conf"]` →
  `/usr/sbin/named -u bind -g -c /dnslab/config/named.conf`.
  `-g` keeps named in the foreground and sends all logging to stderr
  (`docker logs`), overriding any `logging {}` config.
- `named -u bind` drops privileges after startup; the lab's world-readable
  key files (0644) are readable regardless of uid.
- `directory "/tmp"` — writable at any uid inside the container, and it also
  exists on lint hosts, so `named-checkconf` (run by `dnslab.selfcheck` via
  `lint: named-checkconf`) does not fail on a nonexistent working directory
  the way `/var/cache/bind` does outside the image.
- `pid-file none;` and empty `controls { };` — no pidfile, no rndc socket.

## Verified capabilities (live, against this pinned image)

| capability | verdict | evidence |
|---|---|---|
| Do53 listener | works | `do53-query` PASS, all profiles |
| DoT listener (native) | works | `tls dnslab-tls { key-file; cert-file; }` + `listen-on port 853 tls dnslab-tls { any; };` — `dot-query` PASS (dnspython + kdig agree), `cert` PASS |
| **DoT upstream forwarding** | **works** | see below |

### Forwarders-over-TLS verdict: WORKS in 9.20.24

Grammar (accepted by `named-checkconf` on host 9.20.27 **and** in-image 9.20.24):

```
tls upstream-tls {
    ca-file "/dnslab/certs/dnslab-ca.pem";
    remote-hostname "lab-auth-dot.dnslab.test";
};
zone "lab.test" {
    type forward;
    forward only;
    forwarders { <upstream_dot.ip> port 853 tls upstream-tls; };
};
```

Functional proof (2026-09-03, `forwarder-dot` profile against the framework's
transport-isolated lab-auth pair):

- `dot-upstream` check **PASS**: marker TXT == `"dot"` — the answer came from
  `lab-auth-dot`, which has **no Do53 listener at all**, so BIND must have
  connected over TLS 853.
- Strict validation confirmed by negative test: restarting the same profile
  with `remote-hostname "wrong.dnslab.test"` (an override, the upstream cert's
  SAN is `lab-auth-dot.dnslab.test`) turned every `lab.test` query into
  SERVFAIL — BIND enforces `ca-file` + `remote-hostname`, it does not fall
  back to opportunistic/unvalidated TLS. `remote-hostname` is also used as SNI.

Hence `dot_upstream_forwarding: true` in the manifest.

## Profiles

| profile | listeners | lab.test resolution |
|---|---|---|
| `recursive` (default) | 53 + 853 | `type static-stub; server-addresses { <upstream_do53.ip>; };` — genuine iterative resolution to the lab authoritative, no public delegation needed |
| `forwarder-do53` | 53 + 853 | `type forward; forward only;` to `<upstream_do53.ip>` port 53, plaintext |
| `forwarder-dot` | 53 + 853 | `type forward; forward only;` to `<upstream_dot.ip>` port 853 `tls upstream-tls` (strict) |

All profiles: `recursion yes` (BIND forwarding happens inside recursion),
`allow-query { any; }` / `allow-recursion { any; }` (lab network only — never
expose a resolver like this publicly), `dnssec-validation no;` (lab.test is
unsigned), `listen-on-v6 { none; }`.

## Check results at verification

- `forwarder-do53`: do53-query PASS, dot-query PASS, cert PASS,
  forwarding PASS (marker `"do53"`), dot-upstream SKIP (profile).
- `forwarder-dot`: do53-query PASS, dot-query PASS, cert PASS,
  forwarding PASS (marker `"dot"`), **dot-upstream PASS**.
- `recursive`: do53-query PASS, dot-query PASS, cert PASS,
  forwarding PASS (marker `"do53"` via static-stub), dot-upstream SKIP.

## Dialect notes

- TLS contexts are named `tls <name> { ... };` blocks referenced by name from
  both listeners (`listen-on ... tls <name>`) and forwarders
  (`forwarders { ip port 853 tls <name>; }`). The built-in name `ephemeral`
  (self-signed on the fly) exists for listeners; the lab uses real lab-CA
  certs instead.
- A forward zone needs recursion enabled or forwarding never triggers;
  `forward only;` prevents silent iterative fallback on forwarder failure
  (with a broken upstream you get SERVFAIL, not a wrong-transport answer).
- `pid-file none;` uses the bare keyword `none` (unquoted).
