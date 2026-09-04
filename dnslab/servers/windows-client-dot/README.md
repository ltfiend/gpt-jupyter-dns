# windows-client-dot — Windows stub-resolver DoT client

A **client**, not a server: this Windows box answers no DNS queries. Its
stub resolver is configured for native client-side DNS-over-TLS and it
*sends* its own lookups to the upstream(s) over DoT/853. It's the client
counterpart to the recursive-forwarder targets — useful for testing DoT
functionality "from as many different clients" as possible.

## Why Windows Server 2025

Native client DoT debuted in **Windows 11 Insider build 25158**. AWS EC2
does not offer a stock Windows 11 client AMI, so this module uses **Windows
Server 2025** (build **26100**), which carries the same client DoT stack.
Verified live: `netsh dns show global` reports `DoT settings: enabled`, and
DoT works end to end (see below).

## How it's configured (user-data)

`netsh dns` is the only interface (no GPO for DoT yet):

```powershell
netsh dns add global dot=yes
netsh dns add encryption server=<ip> dothost=<tls-hostname> autoupgrade=yes
Set-DnsClientServerAddress -InterfaceIndex <if> -ServerAddresses <ip>...
```

`dothost` is the SNI / certificate-validation name; `autoupgrade=yes` forces
DoT (no silent UDP fallback). Only the default DoT port 853 is supported —
custom ports can't be configured yet.

Upstreams come from the shared `upstreams` config (`ip` + `tls_hostname`);
override per run:

```python
dnslab.start('windows-client-dot',
             upstreams=[{'ip': '9.9.9.9', 'tls_hostname': 'dns.quad9.net'}])
```

## How it's verified (on-box, via SSM)

The client can't be queried from the notebook, so verification runs *on the
box* through SSM Run Command (the instance carries the `dnslab-ssm` instance
profile, created on demand with only `AmazonSSMManagedInstanceCore`):

```python
dnslab.checks.windows_dot_client_report('windows-client-dot')
```

It blocks plaintext 53 outbound, resolves the requested names, and checks for
an established TCP connection to the upstream on 853 — with 53 blocked, a
successful resolution is proof DoT was used. The 53 block is always removed
before the call returns. Verified result (Server 2025, 10.0.26100):

```
verdict: PASS
resolves: example.com/cloudflare.com/quad9.net = NOERROR
dot_853_connections: 1.1.1.1
```

## Lifecycle / cost

- No inbound listener, so readiness is "SSM Online", not a DNS probe.
- `dnslab.start('windows-client-dot')` launches (or **resumes** a stopped
  instance, or **reuses** a running one with unchanged config).
- Stop it to pause billing (compute stops, EBS remains): `aws ec2
  stop-instances --instance-ids <id>`; `dnslab.start(...)` resumes it.
- `dnslab.stop('windows-client-dot')` / `dnslab.nuke()` **terminate** it.

## Server vs client (why this is separate from windows-dns)

The Windows DNS **Server** role (the `windows-dns` module) still cannot
forward upstream over DoT/DoH even on Server 2025 — that's a different
subsystem from the DNS **client** stub resolver used here. These are
independent: `windows-dns` tests inbound/forwarding (Do53), this tests the
client DoT path.
