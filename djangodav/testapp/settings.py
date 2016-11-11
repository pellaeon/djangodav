import random
import string

from tempfile import gettempdir


INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.contenttypes',

    'djangodav',
)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
    },
}

ROOT_URLCONF = 'djangodav.tests.urls'
MIDDLEWARE_CLASSES = ()

WEBDAV_ROOT = gettempdir()

SECRET_KEY = ''.join([random.choice(string.ascii_letters) for x in range(40)])
