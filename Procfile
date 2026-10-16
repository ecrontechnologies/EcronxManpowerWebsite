web: cd django_backend && python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn ecronx.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120
