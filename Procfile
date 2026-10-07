web: gunicorn abiastream.wsgi:application
worker: celery -A abiastream worker -l info
beat: celery -A abiastream beat -l info
