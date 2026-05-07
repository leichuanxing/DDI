FROM powerdns/pdns-auth-48:latest

ARG DDI_VERSION=0.0.0
LABEL org.opencontainers.image.version=$DDI_VERSION

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends dnsmasq-base ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/dnsmasq /var/lib/powerdns

COPY dns_query_log_forwarder.py /usr/local/bin/dns-query-log-forwarder.py
COPY entrypoint.sh /usr/local/bin/ddi-pdns-entrypoint
RUN chmod +x /usr/local/bin/dns-query-log-forwarder.py /usr/local/bin/ddi-pdns-entrypoint

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/ddi-pdns-entrypoint"]
