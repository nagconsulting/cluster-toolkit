#!/bin/bash
# renew_guac_token_playbook.sh
#
# This script runs the login.yaml playbook with only the token renewal tasks.

PLAYBOOK_PATH="/tmp/ansible_setup/login.yaml"
EXTRA_ARGS="-e @/tmp/ansible_setup/vars.yaml"

cd /tmp/ansible_setup/ || exit 1
ansible-playbook "$PLAYBOOK_PATH" --tags renew_guac_token $EXTRA_ARGS
