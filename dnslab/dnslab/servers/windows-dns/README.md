# windows-dns — Windows Server 2025 DNS Server role on EC2 (tier 2)

A real (non-container) DNS implementation for the DoT test matrix: the
Windows **DNS Server role** on a Windows Server 2025 EC2 instance,
configured entirely via EC2 user-data (PowerShell) as a recursing
forwarder on udp+tcp/53.

Its job in this framework is largely to be an **honest negative**: Windows
DNS Server cannot terminate DNS-over-TLS, so the DoT rows of the check
matrix SKIP with a documented reason instead of failing mysteriously.

## The Windows DoT gap (verified 2026-09)

Claim under test: *"the Windows DNS Server role has no DoT listener; DoT
client support lives in the Windows stub resolver, not the server role."*

Verdict: **still true for DoT, with one 2026 twist — the server role
gained a DoH (not DoT) listener.**

1. **No DoT listener in the DNS Server role.** Microsoft confirmed in
   Aug 2024 that "on Windows Server, the DNS Server role does not support
   DNS over HTTPS (DoH) or DNS over TLS (DoT)" (server-side), for both
   Server 2022 and the Server 2025 preview.
   [Microsoft Q&A: DoT support for the DNS Server role](https://learn.microsoft.com/en-us/answers/questions/2195043/dns-over-tls-(dot)-support-for-the-dns-server-role)
2. **The 2026 change is DoH-only.** Windows Server 2025 gained a
   server-side **DoH** listener: public preview with the 2026-02 update
   (KB5075899), GA with the 2026-06 security update (KB5094125). It binds
   a certificate to tcp/443 via `netsh http add sslcert` and enables with
   `Set-DnsServerEncryptionProtocol -EnableDoh $true -UriTemplate ...`.
   [Enable DNS over HTTPS in DNS Server on Windows Server](https://learn.microsoft.com/en-us/windows-server/networking/dns/enable-dns-over-https-server) ·
   [DoH GA announcement](https://techcommunity.microsoft.com/blog/networkingblog/doh-is-now-generally-available-on-windows-dns-server/4526839)
3. **The new cmdlet has no DoT switch.** `Set-DnsServerEncryptionProtocol`
   (available "on Windows Server 2025 or later beginning with 2026-02
   Security Update") exposes exactly `-EnableDoh` and `-UriTemplate` —
   there is no `-EnableDot`, no port-853 anything.
   [Set-DnsServerEncryptionProtocol reference](https://learn.microsoft.com/en-us/powershell/module/dnsserver/set-dnsserverencryptionprotocol?view=windowsserver2025-ps)
4. **Encrypted-DNS client support lives in the stub resolver / ZTDNS, not
   the server role.** Windows' DoH/DoT support as a *client* is a DNS
   client (stub resolver) feature, and Zero Trust DNS (ZTDNS) is
   client-side enforcement: it locks the Windows DNS client to a
   Protective DNS server that must speak DoH or DoT — it does not make
   the Windows DNS *Server* role speak them.
   [Deploying Zero Trust DNS](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/zero-trust-dns/deploying-zero-trust-dns) ·
   [ZTDNS GA blog](https://techcommunity.microsoft.com/blog/networkingblog/zero-trust-dns-is-here-elevating-enterprise-security-on-windows-11/4468743)
5. Consequently the DNS Server role's **forwarders are plain Do53** — there
   is no supported way to have the role forward to an upstream over TLS,
   so `dot_upstream_forwarding: false` as well.

Manifest consequences: `dot_listener: false`, `dot_upstream_forwarding:
false` → `dot-query`, `cert`, and `dot-upstream` checks all **SKIP**.
(A future `doh_listener` capability would be true on patched Server 2025,
but this framework currently tests DoT/853, not DoH/443.)

### Documented-but-not-implemented: `windows-dot-proxy`

A second profile could bolt DoT termination *in front of* the role with an
stunnel/nginx-stream TLS proxy on 853 forwarding to 127.0.0.1:53, flagged
`dot_listener_via_proxy: true` (the `Capabilities` model already has the
flag, and `target()` already honors it). That proves nothing about Windows
DNS itself — it is deliberately left unimplemented until the matrix needs
a via-proxy row. Sketch: user-data installs stunnel (or `nginx -with
stream`) with the lab/self-signed cert, `accept = 853`, `connect =
127.0.0.1:53`; SG already opens tcp/853.

## Cost guardrails — this launches real, billed EC2 instances

* Every instance/volume/SG is tagged `dnslab=1`, `dnslab-server`,
  `dnslab-instance`, `dnslab-session` (uuid4) and
  `dnslab-expires` (UTC now+4h, ISO8601).
* `dnslab.status()` shows running-hours and flags anything past its
  `dnslab-expires` tag with `EXPIRED` — the framework does **not**
  auto-terminate; the tag exists so you (or an external reaper) can.
* The security group `dnslab-<session>` only admits **your public IP /32**
  (udp/53, tcp/53, tcp/853, plus tcp/3389 only if the manifest sets
  `rdp: true`) — this is not an open resolver.
* **`dnslab.nuke()` is the cleanup.** It terminates every `dnslab=1`
  instance in the region and then deletes all `dnslab-*` security groups
  (retrying `DependencyViolation` while ENIs detach). Run it when done,
  and after any failed/interrupted start. Double-check in the console:
  EC2 → Instances → tag `dnslab=1`.
* t3.medium is roughly $0.05/h on-demand plus a ~30 GB gp3 root volume;
  a forgotten instance is a real bill.

## Manual verification (nothing here runs in CI — it costs money)

The framework's automation makes **no** AWS calls at import or selfcheck
time. Verifying this module end-to-end is a deliberate manual step:

### 0. Credentials + region

```bash
aws configure            # or export AWS_PROFILE=..., AWS_REGION=...
aws sts get-caller-identity   # must succeed
```

The boto3 default chain is used as-is; the IAM principal needs
`ec2:RunInstances/Describe*/TerminateInstances/CreateSecurityGroup/
AuthorizeSecurityGroupIngress/DeleteSecurityGroup/CreateTags/
GetConsoleOutput` and `ssm:GetParameter` (public AMI parameters), and the
region needs a default VPC whose default subnet assigns public IPs.

### 1. Start (expect ~5–10 min: Windows boot + EC2Launch user-data)

```bash
python3 -c "import dnslab; print(dnslab.start('windows-dns', timeout=600))"
```

This resolves the current Windows Server 2025 AMI via the SSM public
parameter, creates the session SG scoped to your /32, launches t3.medium
with the rendered PowerShell user-data (kept locally at
`<workspace>/dnslab-state/windows-dns/userdata.ps1`), and blocks until
udp/53 answers from the instance's public IP.

### 2. Status / discovery (kernel-restart safe — tags are the truth)

```bash
python3 -c "import dnslab; print(dnslab.status())"
```

### 3. Checks

```bash
python3 -c "
import dnslab
t = dnslab.target('windows-dns')
for r in dnslab.checks.run_checks(t):
    print(f'{r.check:14s} {r.status:5s} {r.detail}')"
```

Expected matrix for `windows-dns` / `forwarder-do53`:

| check         | expected | why |
|---------------|----------|-----|
| `do53-query`  | **PASS** | role answers `. SOA` via its forwarders |
| `dot-query`   | **SKIP** | `DoT listener unsupported` (the gap above) |
| `cert`        | **SKIP** | no DoT listener |
| `forwarding`  | FAIL (expected) | it queries `transport-marker.lab.test`, which only exists on the docker-network lab upstreams — unreachable from EC2 |
| `dot-upstream`| **SKIP** | `DoT upstream forwarding unsupported` |

Spot-check by hand from the same machine (the SG only admits your IP):

```bash
dig @<public-ip> example.com A            # NOERROR + answer
kdig +tls @<public-ip> -p 853 example.com # must FAIL to connect — no DoT
```

### 4. Cleanup — do not skip

```bash
python3 -c "import dnslab; print(dnslab.nuke())"
aws ec2 describe-instances \
  --filters Name=tag:dnslab,Values=1 \
            Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].InstanceId'   # expect []
```

## Notes

* `config_path` in the manifest is descriptive only for the ec2 provider —
  configuration reaches the instance as user-data, not a mounted file.
* Forwarders default to `1.1.1.1 1.0.0.1` (the lab-auth pair is not
  reachable from EC2); override per start:
  `dnslab.start('windows-dns', forwarders='9.9.9.9 149.112.112.112')`.
* Set `rdp: true` in the manifest (before starting) to open tcp/3389 to
  your /32 for interactive debugging; retrieve the Administrator password
  with `aws ec2 get-password-data` and your key pair — note this module
  launches without a key pair by default, so prefer AWS Systems Manager
  Fleet Manager / session access or bake a key pair in if you need a
  desktop.
* `dnslab.logs('windows-dns')` fetches the EC2 console output; the
  user-data transcript lives on the instance at `C:\dnslab\userdata.log`
  and the completion marker at `C:\dnslab\ready.txt`.
