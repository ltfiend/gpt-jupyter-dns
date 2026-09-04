# Unbound recursive/forwarding resolver for dnslab. Built locally by the
# docker provider (tag dnslab/unbound:local) following the lab-auth pattern,
# because nlnetlabs publishes no unbound image on Docker Hub and mvance/unbound
# bakes its own config layout into the entrypoint.
#
# Alpine 3.22 ships Unbound 1.23.1 built --with-ssl (DoT listener + DoT
# upstream both work; verified live against the lab-auth pair).
FROM alpine:3.22

RUN apk add --no-cache unbound drill ca-certificates

# Prime a root trust anchor so profiles with DNSSEC validation enabled
# (global-forwarder-dot) can use auto-trust-anchor-file without network
# access at startup. unbound-anchor exits non-zero when it updates the
# anchor, which is fine.
RUN unbound-anchor -a /etc/unbound/root.key || true

# -d = stay in foreground; the rendered profile config is bind-mounted
# read-only at /dnslab/config/unbound.conf by the docker provider.
CMD ["unbound", "-d", "-c", "/dnslab/config/unbound.conf"]
