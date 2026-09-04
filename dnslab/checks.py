"""Functional DoT checks and the per-server test matrix.

All query/assert logic lives here (not in notebook cells) so any notebook
can reuse it. Checks return CheckResult with status PASS / FAIL / SKIP —
SKIP is used when the target's verified capabilities say the behavior is
unsupported, so a missing feature is reported honestly instead of failing.
"""

from __future__ import annotations

import ssl
import subprocess
import time

import dns.message
import dns.query
import dns.rdatatype

from .model import CheckResult, Target

MARKER_QNAME = "transport-marker.lab.test"
LAB_ZONE_SOA = "lab.test"


def _query(target: Target, qname: str, qtype: str, *, dot: bool, timeout: float = 5):
    q = dns.message.make_query(qname, qtype)
    t0 = time.monotonic()
    if dot:
        sslctx = ssl.create_default_context(cafile=target.ca_file)
        resp = dns.query.tls(q, target.address, port=target.port_dot, timeout=timeout,
                             ssl_context=sslctx, server_hostname=target.tls_hostname)
    else:
        resp = dns.query.udp(q, target.address, port=target.port_do53, timeout=timeout)
    return resp, (time.monotonic() - t0) * 1000


def _txt_values(resp) -> list[str]:
    vals = []
    for rrset in resp.answer:
        if rrset.rdtype == dns.rdatatype.TXT:
            for rdata in rrset:
                vals.extend(s.decode() for s in rdata.strings)
    return vals


def _basic_probe(target: Target) -> tuple[str, str]:
    """Docker-tier targets answer the lab zone; anything else (ec2/external)
    can't reach the lab upstreams, so probe with a public name instead."""
    return (LAB_ZONE_SOA, "SOA") if target.provider == "docker" else PUBLIC_PROBE


def query_do53(target: Target, qname: str | None = None, qtype: str | None = None) -> CheckResult:
    """The server answers a plain UDP/53 query."""
    if qname is None or qtype is None:
        qname, qtype = _basic_probe(target)
    if target.port_do53 is None:
        return CheckResult("do53-query", target.name, "SKIP", "no Do53 listener in this profile")
    try:
        resp, ms = _query(target, qname, qtype, dot=False)
        rcode = dns.rcode.to_text(resp.rcode())
        if resp.rcode() == 0:
            return CheckResult("do53-query", target.name, "PASS", f"rcode={rcode}", ms)
        return CheckResult("do53-query", target.name, "FAIL", f"rcode={rcode}", ms)
    except Exception as e:  # noqa: BLE001 — any transport error is a functional FAIL
        return CheckResult("do53-query", target.name, "FAIL", repr(e))


def query_dot(target: Target, qname: str | None = None, qtype: str | None = None) -> CheckResult:
    """The server answers over TLS on 853 with a cert the lab CA validates.

    Primary path is dnspython dns.query.tls; kdig +tls-ca cross-checks when
    available so a dnspython quirk can't hide a broken server (or vice versa).
    """
    if qname is None or qtype is None:
        qname, qtype = _basic_probe(target)
    if target.port_dot is None:
        reason = "DoT listener unsupported" if not target.capabilities.dot_listener \
            else "no DoT listener in this profile"
        return CheckResult("dot-query", target.name, "SKIP", reason)
    try:
        resp, ms = _query(target, qname, qtype, dot=True)
        if resp.rcode() != 0:
            return CheckResult("dot-query", target.name, "FAIL",
                               f"rcode={dns.rcode.to_text(resp.rcode())}", ms)
    except Exception as e:  # noqa: BLE001
        return CheckResult("dot-query", target.name, "FAIL", f"dnspython: {e!r}")

    try:
        kdig = subprocess.run(
            ["kdig", f"+tls-ca={target.ca_file}", f"+tls-hostname={target.tls_hostname}",
             "-p", str(target.port_dot), f"@{target.address}", qname, qtype],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        return CheckResult("dot-query", target.name, "PASS",
                           "dnspython ok (kdig unavailable for cross-check)", ms)
    if kdig.returncode != 0:
        return CheckResult("dot-query", target.name, "FAIL",
                           f"dnspython ok but kdig failed: {kdig.stderr.strip()[:200]}", ms)
    return CheckResult("dot-query", target.name, "PASS", "dnspython + kdig agree", ms)


def check_cert(target: Target) -> CheckResult:
    """The presented certificate chains to the lab CA and covers tls_hostname."""
    if target.port_dot is None:
        return CheckResult("cert", target.name, "SKIP", "no DoT listener")
    try:
        sslctx = ssl.create_default_context(cafile=target.ca_file)
        with ssl.create_connection((target.address, target.port_dot), timeout=5) as sock:
            with sslctx.wrap_socket(sock, server_hostname=target.tls_hostname) as tls:
                cert = tls.getpeercert()
        sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
        exp = cert.get("notAfter", "?")
        if target.tls_hostname in sans:
            return CheckResult("cert", target.name, "PASS", f"SAN ok, expires {exp}")
        return CheckResult("cert", target.name, "FAIL",
                           f"{target.tls_hostname} not in SANs {sans}")
    except Exception as e:  # noqa: BLE001
        return CheckResult("cert", target.name, "FAIL", repr(e))


PUBLIC_PROBE = ("example.com", "A")


def check_forwarding(target: Target, *, dot: bool | None = None) -> CheckResult:
    """A forwarder/recursive target resolves through to its upstream.

    Docker-tier targets resolve the lab zone's marker record (their
    upstreams are the lab-auth pair; authoritative targets answer it from
    their own zone copy). Non-docker targets (ec2/external) cannot reach
    the docker-network lab upstreams, so they are probed with a public
    name instead — proving forwarding works, without a marker claim.
    """
    use_dot = target.port_do53 is None if dot is None else dot
    transport = "dot" if use_dot else "do53"
    if (use_dot and target.port_dot is None) or (not use_dot and target.port_do53 is None):
        return CheckResult("forwarding", target.name, "SKIP", f"no {transport} listener")
    if target.provider == "docker":
        qname, qtype = MARKER_QNAME, "TXT"
    else:
        qname, qtype = PUBLIC_PROBE
    try:
        resp, ms = _query(target, qname, qtype, dot=use_dot, timeout=10)
        if qtype == "TXT":
            vals = _txt_values(resp)
            if vals:
                return CheckResult("forwarding", target.name, "PASS",
                                   f"marker={vals[0]!r} via {transport}", ms)
            return CheckResult("forwarding", target.name, "FAIL",
                               f"no TXT answer (rcode={dns.rcode.to_text(resp.rcode())})", ms)
        if resp.rcode() == 0 and resp.answer:
            return CheckResult("forwarding", target.name, "PASS",
                               f"resolved {qname}/{qtype} via {transport}", ms)
        return CheckResult("forwarding", target.name, "FAIL",
                           f"{qname}/{qtype}: rcode={dns.rcode.to_text(resp.rcode())}, "
                           f"{len(resp.answer)} answer rrsets", ms)
    except Exception as e:  # noqa: BLE001
        return CheckResult("forwarding", target.name, "FAIL", repr(e))


def check_dot_upstream_marker(target: Target) -> CheckResult:
    """Prove the forwarder used the TLS upstream: the DoT-only lab upstream
    serves marker TXT "dot"; the Do53-only upstream serves "do53". Answer
    content therefore identifies the transport actually used upstream."""
    if "forwarder" not in target.capabilities.roles and \
            "recursive" not in target.capabilities.roles:
        return CheckResult("dot-upstream", target.name, "SKIP", "not a forwarder")
    if not target.capabilities.dot_upstream_forwarding:
        return CheckResult("dot-upstream", target.name, "SKIP",
                           "DoT upstream forwarding unsupported")
    if not target.profile.endswith("dot"):
        return CheckResult("dot-upstream", target.name, "SKIP",
                           f"profile {target.profile!r} does not forward over DoT")
    use_dot = target.port_do53 is None
    try:
        resp, ms = _query(target, MARKER_QNAME, "TXT", dot=use_dot, timeout=10)
        vals = _txt_values(resp)
        if "dot" in vals:
            return CheckResult("dot-upstream", target.name, "PASS",
                               'marker TXT == "dot" (DoT-only upstream answered)', ms)
        return CheckResult("dot-upstream", target.name, "FAIL",
                           f"marker={vals!r} — answer did not come from the DoT upstream", ms)
    except Exception as e:  # noqa: BLE001
        return CheckResult("dot-upstream", target.name, "FAIL", repr(e))


def query_report(target: Target, qname: str, qtype: str = "A", *,
                 dot: bool = True, want_dnssec: bool = True,
                 timeout: float = 10) -> dict:
    """One query against one target, reported in full detail.

    Success is rcode NOERROR only — answers are not matched. The row makes
    header flags and EDNS visible so DNSSEC behavior can be read off
    directly: AD in `flags` means the responding path validated, `do`
    echoes the DO bit, `ede` carries Extended DNS Errors (e.g. validation
    failure reasons), `rrsig` says whether signatures came back.
    """
    import dns.edns
    import dns.flags
    import dns.rcode

    transport = "dot" if dot else "do53"
    row = {"target": target.name, "qname": qname, "qtype": qtype,
           "transport": transport, "status": "SKIP", "rcode": "",
           "flags": "", "do": None, "edns_payload": None, "ede": "",
           "rrsig": None, "answers": None, "latency_ms": None}
    if (dot and target.port_dot is None) or (not dot and target.port_do53 is None):
        row["ede"] = f"no {transport} listener"
        return row

    q = dns.message.make_query(qname, qtype, use_edns=0, payload=1232,
                               want_dnssec=want_dnssec)
    t0 = time.monotonic()
    try:
        if dot:
            sslctx = ssl.create_default_context(cafile=target.ca_file)
            resp = dns.query.tls(q, target.address, port=target.port_dot,
                                 timeout=timeout, ssl_context=sslctx,
                                 server_hostname=target.tls_hostname)
        else:
            resp = dns.query.udp_with_fallback(
                q, target.address, port=target.port_do53, timeout=timeout)[0]
    except Exception as e:  # noqa: BLE001 — transport failure is a FAIL row
        row.update(status="FAIL", ede=repr(e),
                   latency_ms=round((time.monotonic() - t0) * 1000, 1))
        return row

    row["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    row["rcode"] = dns.rcode.to_text(resp.rcode())
    row["status"] = "PASS" if resp.rcode() == dns.rcode.NOERROR else "FAIL"
    row["flags"] = dns.flags.to_text(resp.flags)
    if resp.edns >= 0:
        row["do"] = bool(resp.ednsflags & dns.flags.DO)
        row["edns_payload"] = resp.payload
        edes = []
        for opt in resp.options:
            if isinstance(opt, dns.edns.EDEOption):
                try:
                    name = dns.edns.EDECode(opt.code).name
                except ValueError:
                    name = str(opt.code)
                edes.append(f"{int(opt.code)} {name}" + (f": {opt.text}" if opt.text else ""))
        row["ede"] = "; ".join(edes)
    row["rrsig"] = any(rr.rdtype == dns.rdatatype.RRSIG for rr in resp.answer)
    row["answers"] = sum(len(rr) for rr in resp.answer)
    return row


_DOT_CLIENT_PS = r"""
$ErrorActionPreference='Continue'
$names = @({names})
$block = ${block}
Write-Output "OS: $((Get-CimInstance Win32_OperatingSystem).Caption) $([Environment]::OSVersion.Version)"
# Ensure client DoT config is present (idempotent) so this report does not
# depend on user-data timing — netsh add is a no-op if already set.
netsh dns add global dot=yes | Out-Null
{ensure_encryption}
$servers = @({server_ips})
Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object {{ $_.ServerAddresses }} | ForEach-Object {{
    Set-DnsClientServerAddress -InterfaceIndex $_.InterfaceIndex -ServerAddresses $servers -ErrorAction SilentlyContinue
}}
Write-Output "--- netsh dns show encryption ---"
netsh dns show encryption
if ($block) {{
    New-NetFirewallRule -DisplayName 'dnslab-block-udp53' -Direction Outbound -Protocol UDP -RemotePort 53 -Action Block | Out-Null
    New-NetFirewallRule -DisplayName 'dnslab-block-tcp53' -Direction Outbound -Protocol TCP -RemotePort 53 -Action Block | Out-Null
    Write-Output "PLAINTEXT_53_BLOCKED: yes (resolution success now proves DoT)"
}}
Clear-DnsClientCache
Start-Sleep -Seconds 2
foreach ($n in $names) {{
    $r = Resolve-DnsName $n -Type A -ErrorAction SilentlyContinue
    $ips = ($r | Where-Object {{$_.IPAddress}} | Select-Object -First 3 -ExpandProperty IPAddress) -join ','
    if ($ips) {{ Write-Output "RESOLVE $n = NOERROR ($ips)" }} else {{ Write-Output "RESOLVE $n = FAILED" }}
}}
Start-Sleep -Seconds 1
$c = Get-NetTCPConnection -RemotePort 853 -ErrorAction SilentlyContinue
if ($c) {{ Write-Output ("DOT_853_CONNECTIONS: " + (($c | ForEach-Object {{$_.RemoteAddress}}) -join ',')) }}
else {{ Write-Output "DOT_853_CONNECTIONS: none" }}
if ($block) {{
    Remove-NetFirewallRule -DisplayName 'dnslab-block-udp53' -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName 'dnslab-block-tcp53' -ErrorAction SilentlyContinue
    Write-Output "PLAINTEXT_53_BLOCK_REMOVED: yes"
}}
Write-Output "DONE"
"""


def windows_dot_client_report(name: str = "windows-client-dot",
                              names=("example.com", "cloudflare.com", "quad9.net"),
                              block_plaintext: bool = True, timeout: float = 300):
    """Verify a Windows stub-resolver DoT client ON-BOX via SSM.

    Because the client answers no queries, it can't be tested from the
    notebook — this runs PowerShell on the instance that (optionally) blocks
    plaintext 53 outbound, resolves each name, and reports whether an 853/TLS
    connection to the upstream is established. With block_plaintext=True a
    successful resolution is proof DoT was used. Returns a dict with the parsed
    results and the raw transcript; the 53 block is always removed before it
    returns so the box is left usable.
    """
    from .providers import get_provider

    from .registry import get

    prov = get_provider("ec2")
    inst = next((i for i in prov.discover()
                 if name in (i.name, i.server)), None)
    if inst is None:
        raise RuntimeError(f"{name!r} is not running — dnslab.start({name!r}) first")

    # upstreams the instance was configured with, so the report can (re)apply
    # the netsh DoT config itself rather than trusting user-data timing
    spec = get(inst.server)
    prof = spec.profiles.get(inst.profile)
    upstreams = (prof.extra.get("upstreams") if prof else None) or []
    ensure = "\n".join(
        f"netsh dns add encryption server={u['ip']} dothost={u['tls_hostname']} "
        f"autoupgrade=yes | Out-Null"
        for u in upstreams if u.get("ip") and u.get("tls_hostname")
    )
    server_ips = ",".join(f"'{u['ip']}'" for u in upstreams if u.get("ip"))
    if not server_ips:
        raise RuntimeError(
            f"{name!r} profile {inst.profile!r} has no upstreams to configure DoT with"
        )
    ps = _DOT_CLIENT_PS.format(
        names=",".join(f"'{n}'" for n in names),
        block="true" if block_plaintext else "false",
        ensure_encryption=ensure,
        server_ips=server_ips,
    )
    res = prov.run_command(inst.id, ps, timeout=timeout)
    out = res.get("stdout", "")
    resolves, conns = {}, ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("RESOLVE "):
            body = line[len("RESOLVE "):]
            qn, _, verdict = body.partition(" = ")
            resolves[qn] = verdict
        elif line.startswith("DOT_853_CONNECTIONS:"):
            conns = line.split(":", 1)[1].strip()
    dot_used = conns not in ("", "none")
    all_ok = bool(resolves) and all(v.startswith("NOERROR") for v in resolves.values())
    return {
        "instance": inst.name, "id": inst.id, "ssm_status": res.get("status"),
        "plaintext_53_blocked": block_plaintext,
        "resolves": resolves,
        "dot_853_connections": conns,
        "dot_used": dot_used,
        # with 53 blocked, resolution success alone proves DoT; otherwise we
        # require an observed 853 connection too
        "verdict": "PASS" if (all_ok and (block_plaintext or dot_used)) else "FAIL",
        "raw": out,
    }


def run_query_matrix(targets: list[Target], queries: list,
                     transports: tuple[str, ...] = ("do53", "dot"),
                     want_dnssec: bool = True):
    """Query every name against every target over every transport.

    `queries` items are "name" or ("name", "TYPE"). Returns a DataFrame
    with one row per (target, name, transport) carrying full flag/EDNS
    detail; PASS means the response was NOERROR (answers are not matched).
    """
    import pandas as pd

    rows = []
    for t in targets:
        for item in queries:
            qname, qtype = item if isinstance(item, (tuple, list)) else (item, "A")
            for tr in transports:
                rows.append(query_report(t, qname, qtype, dot=(tr == "dot"),
                                         want_dnssec=want_dnssec))
    return pd.DataFrame(rows)


ALL_CHECKS = (query_do53, query_dot, check_cert, check_forwarding, check_dot_upstream_marker)


def run_checks(target: Target) -> list[CheckResult]:
    return [chk(target) for chk in ALL_CHECKS]


def run_matrix(targets: list[Target]):
    """rows = server instances, columns = checks, cells = PASS/FAIL/SKIP."""
    import pandas as pd

    rows = {}
    details = {}
    for t in targets:
        results = run_checks(t)
        rows[t.name] = {r.check: r.status for r in results}
        details[t.name] = results
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.attrs["details"] = details
    return df


def explain(df) -> None:
    """Print the detail line behind every non-PASS cell of a run_matrix result."""
    for name, results in df.attrs.get("details", {}).items():
        for r in results:
            if r.status != "PASS":
                print(f"{name:24s} {r.check:14s} {r.status:5s} {r.detail}")
