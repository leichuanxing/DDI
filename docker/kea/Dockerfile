FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        default-mysql-client \
        kea-admin \
        kea-ctrl-agent \
        kea-dhcp4-server \
        kea-dhcp6-server \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/kea /var/lib/kea /var/log/kea

COPY entrypoint.sh /usr/local/bin/ddi-kea-entrypoint
RUN chmod +x /usr/local/bin/ddi-kea-entrypoint

EXPOSE 67/udp 547/udp 8000/tcp

CMD ["/usr/local/bin/ddi-kea-entrypoint"]
