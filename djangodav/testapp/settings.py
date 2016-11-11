import random
import string

from django.conf import settings

INSTALLED_APPS = (
        'djangodav',
        'django.contrib.auth',
        'django.contrib.contenttypes',
        # 'djangodav.tests',
        ),
DATABASES = dict(
        default = dict(
            ENGINE = 'django.db.backends.sqlite3'
            )
        ),
ROOT_URLCONF = 'djangodav.tests.urls',
MIDDLEWARE_CLASSES = ()

from tempfile import gettempdir
WEBDAV_ROOT = gettempdir()

SECRET_KEY = ''.join([random.choice(string.ascii_letters) for x in range(40)])
