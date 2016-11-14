from __future__ import unicode_literals
from builtins import range
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

# Deprecated in 1.10
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
)

# Introduced in 1.8
# https://docs.djangoproject.com/en/1.10/ref/templates/upgrading/
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
    },
]

ROOT_URLCONF = 'djangodav.tests.urls'
MIDDLEWARE_CLASSES = ()

WEBDAV_ROOT = gettempdir()

SECRET_KEY = ''.join([random.choice(string.ascii_letters) for x in range(40)])
