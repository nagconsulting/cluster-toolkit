#!/bin/bash
# renew_guac_token_playbook.sh
#
# This script runs the login.yaml playbook with only the token renewal tasks.

PLAYBOOK_PATH="/tmp/ansible_setup/login.yaml"
INVENTORY="localhost,"
EXTRA_ARGS="--connection=local"

ansible-playbook "$PLAYBOOK_PATH" --tags renew_guac_token --inventory "$INVENTORY" $EXTRA_ARGS
