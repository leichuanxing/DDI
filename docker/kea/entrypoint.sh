#!/bin/sh
set -eu

MYSQL_HOST="${MYSQL_HOST:-ddi-mysql}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATABASE="${MYSQL_DATABASE:-kea}"
MYSQL_USER="${MYSQL_USER:-ddi}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-ddi_password}"

until mysqladmin ping -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" --silent; do
  echo "waiting for MySQL lease database ${MYSQL_HOST}:${MYSQL_PORT}..."
  sleep 2
done

if ! kea-admin db-version mysql -h "${MYSQL_HOST}" -P "${MYSQL_PORT}" -u "${MYSQL_USER}" -p "${MYSQL_PASSWORD}" -n "${MYSQL_DATABASE}" >/dev/null 2>&1; then
  echo "initializing Kea MySQL lease schema..."
  kea-admin db-init mysql -h "${MYSQL_HOST}" -P "${MYSQL_PORT}" -u "${MYSQL_USER}" -p "${MYSQL_PASSWORD}" -n "${MYSQL_DATABASE}"
fi

kea-dhcp4 -c /etc/kea/kea-dhcp4.conf &
kea-dhcp6 -c /etc/kea/kea-dhcp6.conf &
exec kea-ctrl-agent -c /etc/kea/kea-ctrl-agent.conf
