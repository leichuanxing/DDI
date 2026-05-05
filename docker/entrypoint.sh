#!/bin/sh
set -e

mkdir -p /app/celery_queue/out /app/celery_queue/processed /app/staticfiles

until nc -z "${MYSQL_HOST:-ddi-mysql}" "${MYSQL_PORT:-3306}"; do
  echo "waiting for mysql..."
  sleep 2
done

python manage.py makemigrations --noinput
python manage.py migrate --noinput
python manage.py init_rbac || true
python manage.py collectstatic --noinput || true
python manage.py shell <<'PYSHELL'
from django.contrib.auth import get_user_model
User = get_user_model()
username = 'admin'
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, 'admin@example.com', 'admin123456')
PYSHELL

celery -A ddi_system worker --loglevel=INFO --concurrency=2 &
exec gunicorn ddi_system.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3}
