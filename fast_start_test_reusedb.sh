#!/bin/bash
if [ ! -d test_venv ]; then
    virtualenv test_venv

    source test_venv/bin/activate
    pip install -r requirements.txt
    pip install -r requirements_test.txt
    pip install -r requirements_debug.txt
fi

source test_venv/bin/activate

echo "exporting NETWORKAPI_DEBUG"
export NETWORKAPI_DEBUG='1'
export NETWORKAPI_LOG_QUEUE=0

echo "exporting DJANGO_SETTINGS_MODULE"
export DJANGO_SETTINGS_MODULE='networkapi.settings_ci'

# Updates the SDN controller ip address
export REMOTE_CTRL_IP=$(nslookup netapi_odl | grep Address | tail -1 | awk '{print $2}')

echo "Starting tests.."
REUSE_DB=1 python manage.py test "$@"
