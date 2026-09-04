# NSD server-under-test for dnslab. Built locally by the docker provider
# (tag dnslab/nsd:local) because NLnet Labs publishes no official NSD image
# on Docker Hub. Alpine 3.22 ships nsd-4.12.0-r0 (>= 4.3.11, the release
# that introduced the native DoT listener via tls-service-key/pem+tls-port).
FROM alpine:3.22

RUN apk add --no-cache nsd drill

# -d keeps NSD in the foreground; config is bind-mounted read-only by the
# provider. NSD drops privileges itself per the username: setting.
CMD ["nsd", "-d", "-c", "/dnslab/config/nsd.conf"]
