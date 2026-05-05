FROM powerdns/pdns-auth-48:latest

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends dnsmasq-base ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/dnsmasq /var/lib/powerdns

COPY entrypoint.sh /usr/local/bin/ddi-pdns-entrypoint
RUN chmod +x /usr/local/bin/ddi-pdns-entrypoint

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/ddi-pdns-entrypoint"]
