#!/bin/bash

set -ev

cd $(dirname $PROJECT_DIR)/executor
pip install -r requirements.txt
./bin/prepare-executor.sh local $(dirname $PROJECT_DIR)/scheduler/resources/public
tar -C $(dirname $PROJECT_DIR)/travis -xzf ./dist/cook-executor-local.tar.gz
