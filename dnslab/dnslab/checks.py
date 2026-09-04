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


def query_do53(target: Target, qname: str = LAB_ZONE_SOA, qtype: str = "SOA") -> CheckResult:
    """The server answers a plain UDP/53 query."""
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


def query_dot(target: Target, qname: str = LAB_ZONE_SOA, qtype: str = "SOA") -> CheckResult:
    """The server answers over TLS on 853 with a cert the lab CA validates.

    Primary path is dnspython dns.query.tls; kdig +tls-ca cross-checks when
    available so a dnspython quirk can't hide a broken server (or vice versa).
    """
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

    kdig = subprocess.run(
        ["kdig", f"+tls-ca={target.ca_file}", f"+tls-hostname={target.tls_hostname}",
         "-p", str(target.port_dot), f"@{target.address}", qname, qtype],
        capture_output=True, text=True, timeout=15,
    )
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


def check_forwarding(target: Target, *, dot: bool | None = None) -> CheckResult:
    """A forwarder/recursive target resolves the lab zone's marker record.

    For authoritative targets the same query is answered from their own
    zone, which is equally a PASS — the check proves lab.test resolves
    through this target at all.
    """
    use_dot = target.port_do53 is None if dot is None else dot
    transport = "dot" if use_dot else "do53"
    if (use_dot and target.port_dot is None) or (not use_dot and target.port_do53 is None):
        return CheckResult("forwarding", target.name, "SKIP", f"no {transport} listener")
    try:
        resp, ms = _query(target, MARKER_QNAME, "TXT", dot=use_dot, timeout=10)
        vals = _txt_values(resp)
        if vals:
            return CheckResult("forwarding", target.name, "PASS",
                               f"marker={vals[0]!r} via {transport}", ms)
        return CheckResult("forwarding", target.name, "FAIL",
                           f"no TXT answer (rcode={dns.rcode.to_text(resp.rcode())})", ms)
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
