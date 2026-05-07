#!/bin/sh
set -eu

RUNTIME_ENV="/etc/ddi-pdns/recursion.env"
DNSMASQ_CONF="/etc/dnsmasq.conf"

mkdir -p /etc/powerdns/pdns.d /run/dnsmasq /var/lib/powerdns

cat >/etc/powerdns/pdns.conf <<'EOF'
include-dir=/etc/powerdns/pdns.d
EOF

cat >/etc/powerdns/pdns.d/99-ddi-auth-local.conf <<'EOF'
local-address=127.0.0.1
local-port=5300
EOF

cat >/etc/powerdns/pdns.d/98-ddi-gmysql.conf <<EOF
launch=gmysql
gmysql-host=${PDNS_AUTH_GMYSQL_HOST:-ddi-mysql}
gmysql-user=${PDNS_AUTH_GMYSQL_USER:-ddi}
gmysql-password=${PDNS_AUTH_GMYSQL_PASSWORD:-ddi_password}
gmysql-dbname=${PDNS_AUTH_GMYSQL_DBNAME:-powerdns}
EOF

load_runtime_config() {
  RECURSION_ENABLED="${RECURSION_ENABLED:-1}"
  PDNS_FORWARD_ZONES="${PDNS_FORWARD_ZONES:-devnets.net}"
  PUBLIC_DNS_1="${PUBLIC_DNS_1:-223.5.5.5}"
  PUBLIC_DNS_2="${PUBLIC_DNS_2:-119.29.29.29}"
  if [ -f "$RUNTIME_ENV" ]; then
    . "$RUNTIME_ENV"
  fi
}

write_dnsmasq_config() {
  load_runtime_config
  cat >"$DNSMASQ_CONF" <<EOF
no-resolv
no-hosts
port=53
listen-address=0.0.0.0
bind-interfaces
cache-size=10000
domain-needed
log-queries
log-facility=-
log-async
EOF

  if [ "${RECURSION_ENABLED}" = "1" ]; then
    [ -n "${PUBLIC_DNS_1:-}" ] && echo "server=${PUBLIC_DNS_1}" >>"$DNSMASQ_CONF"
    [ -n "${PUBLIC_DNS_2:-}" ] && echo "server=${PUBLIC_DNS_2}" >>"$DNSMASQ_CONF"
  fi

  for zone in $(echo "$PDNS_FORWARD_ZONES" | tr ',' ' '); do
    zone=$(echo "$zone" | sed 's/[.]$//')
    if [ -n "$zone" ]; then
      echo "server=/${zone}/127.0.0.1#5300" >>"$DNSMASQ_CONF"
    fi
  done
}

runtime_checksum() {
  if [ -f "$RUNTIME_ENV" ]; then
    cksum "$RUNTIME_ENV"
  else
    echo "missing"
  fi
}

start_dnsmasq() {
  (
    _fifo="/run/dnsmasq/dns.stderr.fifo"
    trap 'kill "$_dm" 2>/dev/null; kill "$_fw" 2>/dev/null; rm -f "$_fifo"' EXIT INT TERM
    mkdir -p /run/dnsmasq
    rm -f "$_fifo"
    mkfifo "$_fifo"
    # 先启动读端，避免 dnsmasq 写 fifo 时阻塞
    python3 /usr/local/bin/dns-query-log-forwarder.py <"$_fifo" &
    _fw=$!
    dnsmasq --keep-in-foreground --conf-file="$DNSMASQ_CONF" 2>"$_fifo" &
    _dm=$!
    wait "$_dm"
    kill "$_fw" 2>/dev/null || true
  ) &
  DNSMASQ_PID="$!"
}

/usr/local/sbin/pdns_server-startup &
PDNS_PID="$!"

tries=0
until /usr/local/bin/sdig 127.0.0.1 5300 SOA . >/dev/null 2>&1 || [ "$tries" -ge 20 ]; do
  tries=$((tries + 1))
  sleep 1
done

write_dnsmasq_config
start_dnsmasq
LAST_SUM="$(runtime_checksum)"

trap 'kill "$DNSMASQ_PID" "$PDNS_PID" 2>/dev/null || true; exit 0' INT TERM

while kill -0 "$DNSMASQ_PID" 2>/dev/null; do
  sleep 1
  NEW_SUM="$(runtime_checksum)"
  if [ "$NEW_SUM" != "$LAST_SUM" ]; then
    write_dnsmasq_config
    kill "$DNSMASQ_PID" 2>/dev/null || true
    wait "$DNSMASQ_PID" 2>/dev/null || true
    start_dnsmasq
    LAST_SUM="$NEW_SUM"
  fi
done

wait "$DNSMASQ_PID"
