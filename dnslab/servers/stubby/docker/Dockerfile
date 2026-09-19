# stubby server-under-test for dnslab. Built locally by the docker provider
# (tag dnslab/stubby:local) because getdns publishes no official image.
# Alpine 3.22 ships stubby-0.4.3-r2. ca-certificates supplies the system
# trust store for the global-forwarder-dot profile.
FROM alpine:3.22

RUN apk add --no-cache stubby ca-certificates drill

# Foreground; config is bind-mounted read-only by the provider.
CMD ["stubby", "-C", "/dnslab/config/stubby.yml"]
