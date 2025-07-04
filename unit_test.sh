#!/bin/bash
set -exv

# check python version
python3 --version

python3 -m venv .unit_test_venv
source .unit_test_venv/bin/activate
pip3 install --upgrade pip
pip3 install .[test]
flake8 ./src 

if [$? != 0]; then
  echo "Failed to run unit test"
  exit 1
fi

deactivate
