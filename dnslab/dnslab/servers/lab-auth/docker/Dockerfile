# Minimal NSD authoritative server for the dnslab transport-isolated
# upstream pair. Built locally by the docker provider (tag dnslab/lab-auth:local)
# so the framework's critical piece never depends on external image availability.
FROM alpine:3.22

RUN apk add --no-cache nsd drill

# nsd drops privileges itself when username is set in the config; the lab
# config runs it in the foreground with a bind-mounted config.
CMD ["nsd", "-d", "-c", "/dnslab/config/nsd.conf"]
