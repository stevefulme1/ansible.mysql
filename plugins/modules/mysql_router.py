#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_router
short_description: Manage MySQL Router bootstrap and configuration
description:
  - Bootstrap MySQL Router against an InnoDB Cluster.
  - Start, stop, or restart MySQL Router.
  - Requires C(mysqlrouter) to be installed on the target host.
version_added: '5.1.0'
author:
  - Steve Fulmer (@stevefulme1)
options:
  state:
    description:
      - Desired state of MySQL Router.
      - C(bootstrapped) bootstraps MySQL Router against a cluster URI.
      - C(started) ensures MySQL Router is running (via systemd or direct invocation).
      - C(stopped) ensures MySQL Router is stopped.
      - C(restarted) restarts MySQL Router.
    type: str
    choices: [bootstrapped, started, stopped, restarted]
    default: bootstrapped
  bootstrap_uri:
    description:
      - Connection URI for bootstrapping MySQL Router against an InnoDB Cluster.
      - Format is C(user:password@host:port) or C(user@host:port).
      - Required when O(state=bootstrapped).
    type: str
  directory:
    description:
      - Directory to use for MySQL Router configuration.
      - Passed as C(--directory) to the bootstrap command.
    type: path
  account:
    description:
      - MySQL account for Router to use at runtime.
      - Passed as C(--account) to the bootstrap command.
    type: str
  account_create:
    description:
      - How to handle Router account creation during bootstrap.
      - C(if-not-exists) creates the account only if it does not exist.
      - C(always) always creates the account.
      - C(never) never creates the account.
    type: str
    choices: [if-not-exists, always, never]
    default: if-not-exists
  force:
    description:
      - Force re-bootstrap even if the Router is already configured.
    type: bool
    default: false
  mysqlrouter_path:
    description:
      - Path to the C(mysqlrouter) binary.
      - If not specified, the module searches C(PATH) for C(mysqlrouter).
    type: path
  service_name:
    description:
      - Name of the systemd service for MySQL Router.
      - Used when O(state) is C(started), C(stopped), or C(restarted).
    type: str
    default: mysqlrouter

attributes:
  check_mode:
    support: partial
    details:
      - The module reports what would change but does not execute commands in check mode.
  idempotent:
    support: partial
    details:
      - Bootstrap is idempotent when O(force=false) and the Router is already configured.

extends_documentation_fragment:
  - ansible.mysql.mysql

seealso:
  - module: ansible.mysql.mysql_router_info
  - module: ansible.mysql.mysql_innodb_cluster
  - name: MySQL Router documentation
    description: Official MySQL Router reference.
    link: https://dev.mysql.com/doc/mysql-router/en/

notes:
  - This module requires C(mysqlrouter) to be installed on the target host.
  - Bootstrap operation writes configuration files to the target host.
  - Start/stop/restart operations use the system service manager (systemd).
'''

EXAMPLES = r'''
- name: Bootstrap MySQL Router against an InnoDB Cluster
  ansible.mysql.mysql_router:
    state: bootstrapped
    bootstrap_uri: "root:secret@192.0.2.1:3306"
    directory: /opt/mysqlrouter
    account: myrouter
    account_create: if-not-exists

- name: Force re-bootstrap MySQL Router
  ansible.mysql.mysql_router:
    state: bootstrapped
    bootstrap_uri: "root:secret@192.0.2.1:3306"
    force: true

- name: Start MySQL Router
  ansible.mysql.mysql_router:
    state: started

- name: Stop MySQL Router
  ansible.mysql.mysql_router:
    state: stopped

- name: Restart MySQL Router
  ansible.mysql.mysql_router:
    state: restarted
'''

RETURN = r'''
msg:
  description: Human-readable status message.
  returned: always
  type: str
  sample: "MySQL Router bootstrapped successfully"
changed:
  description: Whether any changes were made.
  returned: always
  type: bool
stdout:
  description: Standard output from the command.
  returned: when a command is executed
  type: str
stderr:
  description: Standard error from the command.
  returned: when a command is executed
  type: str
'''

import os

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_common_argument_spec,
)


def find_mysqlrouter(module):
    """Find the mysqlrouter binary."""
    path = module.params.get('mysqlrouter_path')
    if path:
        return path
    return module.get_bin_path('mysqlrouter', required=True)


def is_router_configured(directory):
    """Check if MySQL Router is already configured in the given directory."""
    if not directory:
        return False
    config_file = os.path.join(directory, 'mysqlrouter.conf')
    return os.path.exists(config_file)


def bootstrap_router(module, mysqlrouter, bootstrap_uri, directory, account, account_create, force):
    """Bootstrap MySQL Router."""
    cmd = [mysqlrouter, '--bootstrap', bootstrap_uri]

    if directory:
        cmd.extend(['--directory', directory])
    if account:
        cmd.extend(['--account', account])
    if account_create:
        cmd.extend(['--account-create', account_create])
    if force:
        cmd.append('--force')

    rc, stdout, stderr = module.run_command(cmd)
    return rc, stdout, stderr


def manage_service(module, action, service_name):
    """Start, stop, or restart MySQL Router via systemctl."""
    systemctl = module.get_bin_path('systemctl')
    if not systemctl:
        module.fail_json(msg="systemctl not found; cannot manage MySQL Router service")

    cmd = [systemctl, action, service_name]
    rc, stdout, stderr = module.run_command(cmd)
    return rc, stdout, stderr


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        state=dict(type='str', default='bootstrapped',
                   choices=['bootstrapped', 'started', 'stopped', 'restarted']),
        bootstrap_uri=dict(type='str', no_log=True),
        directory=dict(type='path'),
        account=dict(type='str'),
        account_create=dict(type='str', default='if-not-exists',
                            choices=['if-not-exists', 'always', 'never']),
        force=dict(type='bool', default=False),
        mysqlrouter_path=dict(type='path'),
        service_name=dict(type='str', default='mysqlrouter'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        required_if=[
            ('state', 'bootstrapped', ['bootstrap_uri']),
        ],
        supports_check_mode=True,
    )

    state = module.params['state']
    bootstrap_uri = module.params['bootstrap_uri']
    directory = module.params['directory']
    account = module.params['account']
    account_create = module.params['account_create']
    force = module.params['force']
    service_name = module.params['service_name']

    result = dict(changed=False, msg='')

    if state == 'bootstrapped':
        mysqlrouter = find_mysqlrouter(module)

        if not force and is_router_configured(directory):
            result['msg'] = "MySQL Router already configured in '%s'" % directory
            module.exit_json(**result)

        if module.check_mode:
            result['changed'] = True
            result['msg'] = "MySQL Router would be bootstrapped"
            module.exit_json(**result)

        rc, stdout, stderr = bootstrap_router(
            module, mysqlrouter, bootstrap_uri, directory,
            account, account_create, force)
        if rc != 0:
            module.fail_json(msg="Failed to bootstrap MySQL Router: %s" % stderr,
                             stdout=stdout, stderr=stderr)
        result['changed'] = True
        result['msg'] = "MySQL Router bootstrapped successfully"
        result['stdout'] = stdout
        result['stderr'] = stderr

    elif state in ('started', 'stopped', 'restarted'):
        action_map = {
            'started': 'start',
            'stopped': 'stop',
            'restarted': 'restart',
        }
        action = action_map[state]

        if module.check_mode:
            result['changed'] = True
            result['msg'] = "MySQL Router would be %s" % state
            module.exit_json(**result)

        rc, stdout, stderr = manage_service(module, action, service_name)
        if rc != 0:
            module.fail_json(msg="Failed to %s MySQL Router: %s" % (action, stderr),
                             stdout=stdout, stderr=stderr)
        result['changed'] = True
        result['msg'] = "MySQL Router %s successfully" % state
        result['stdout'] = stdout
        result['stderr'] = stderr

    module.exit_json(**result)


if __name__ == '__main__':
    main()
