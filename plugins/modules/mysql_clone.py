#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_clone
short_description: Manage MySQL Clone Plugin for local and remote cloning
description:
  - Install and manage the MySQL Clone Plugin (C(mysql_clone.so)).
  - Perform local clone operations to a specified data directory.
  - Perform remote clone operations from a donor MySQL instance.
  - Monitor clone progress via C(performance_schema.clone_status) and C(clone_progress).
  - Requires MySQL 8.0.17 or later (the Clone Plugin is not available in earlier versions).
  - This module is not compatible with MariaDB.
version_added: '5.1.0'
options:
  state:
    description:
      - C(present) ensures the Clone Plugin is installed.
      - C(absent) uninstalls the Clone Plugin.
      - C(clone_local) performs a local clone to I(data_directory).
      - C(clone_remote) performs a remote clone from the I(donor) instance.
    type: str
    choices: ['present', 'absent', 'clone_local', 'clone_remote']
    default: present
  data_directory:
    description:
      - Target directory for a local clone operation.
      - Required when I(state=clone_local).
      - The directory must not already exist; MySQL creates it during cloning.
    type: path
  donor_host:
    description:
      - Hostname or IP of the donor MySQL instance for remote cloning.
      - Required when I(state=clone_remote).
    type: str
  donor_port:
    description:
      - Port of the donor MySQL instance.
    type: int
    default: 3306
  donor_user:
    description:
      - MySQL user on the donor for the clone operation.
      - Requires C(BACKUP_ADMIN) privilege on the donor.
      - Required when I(state=clone_remote).
    type: str
  donor_password:
    description:
      - Password for I(donor_user) on the donor instance.
      - Required when I(state=clone_remote).
    type: str
author:
  - Ansible community (@ansible-collections)
requirements:
  - PyMySQL (Python 2.7 and Python 3.x)
  - MySQL 8.0.17 or later
notes:
  - This module is B(not compatible with MariaDB). The Clone Plugin is a MySQL-only feature.
  - Remote cloning replaces all data on the recipient; use with extreme caution.
  - The Clone Plugin must be installed on both donor and recipient for remote cloning.
  - The donor user requires C(BACKUP_ADMIN) privilege; the recipient user requires C(CLONE_ADMIN).
attributes:
  check_mode:
    support: partial
    details:
      - In check mode, plugin install/uninstall and clone operations are not performed.
  idempotent:
    support: partial
    details:
      - Plugin installation is idempotent.
      - Clone operations are not idempotent.
extends_documentation_fragment:
  - ansible.mysql.mysql
seealso:
  - module: ansible.mysql.mysql_backup
  - name: MySQL Clone Plugin
    description: MySQL Clone Plugin reference documentation.
    link: https://dev.mysql.com/doc/refman/8.0/en/clone-plugin.html
  - name: CLONE statement
    description: MySQL CLONE statement reference.
    link: https://dev.mysql.com/doc/refman/8.0/en/clone.html
'''

EXAMPLES = r'''
- name: Ensure the Clone Plugin is installed
  ansible.mysql.mysql_clone:
    state: present
    login_unix_socket: /run/mysqld/mysqld.sock

- name: Perform a local clone
  ansible.mysql.mysql_clone:
    state: clone_local
    data_directory: /var/lib/mysql-clone
    login_unix_socket: /run/mysqld/mysqld.sock

- name: Perform a remote clone from a donor
  ansible.mysql.mysql_clone:
    state: clone_remote
    donor_host: donor.example.com
    donor_port: 3306
    donor_user: clone_user
    donor_password: "{{ vault_clone_password }}"
    login_unix_socket: /run/mysqld/mysqld.sock

- name: Uninstall the Clone Plugin
  ansible.mysql.mysql_clone:
    state: absent
    login_unix_socket: /run/mysqld/mysqld.sock
'''

RETURN = r'''
plugin_installed:
  description: Whether the Clone Plugin is currently installed.
  returned: always
  type: bool
  sample: true
clone_status:
  description: Clone status from performance_schema.clone_status (most recent entry).
  returned: when a clone operation is performed
  type: dict
  contains:
    state:
      description: State of the clone operation.
      type: str
      sample: "Completed"
    error_no:
      description: Error number (0 means success).
      type: int
      sample: 0
    error_message:
      description: Error message (empty on success).
      type: str
      sample: ""
    source:
      description: Source of the clone (LOCAL or donor host).
      type: str
      sample: "LOCAL"
  sample:
    state: "Completed"
    error_no: 0
    error_message: ""
    source: "LOCAL"
clone_progress:
  description: Clone progress stages from performance_schema.clone_progress.
  returned: when a clone operation is performed
  type: list
  elements: dict
  sample:
    - stage: "PAGE COPY"
      state: "Completed"
      estimate: 1048576
      data: 1048576
executed_commands:
  description: List of SQL commands executed.
  returned: always
  type: list
  sample: ["INSTALL PLUGIN clone SONAME 'mysql_clone.so'"]
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
    mysql_common_argument_spec,
    get_server_implementation,
    get_server_version,
)
from ansible_collections.ansible.mysql.plugins.module_utils.version import LooseVersion
from ansible.module_utils.common.text.converters import to_native


def is_plugin_installed(cursor):
    """Check if the clone plugin is currently installed."""
    cursor.execute("SELECT COUNT(*) AS cnt FROM information_schema.PLUGINS WHERE PLUGIN_NAME = 'clone'")
    row = cursor.fetchone()
    if isinstance(row, dict):
        return int(row.get('cnt', row.get('COUNT(*)', 0))) > 0
    return int(row[0]) > 0


def get_clone_status(cursor):
    """Get the most recent clone status from performance_schema."""
    try:
        cursor.execute("SELECT * FROM performance_schema.clone_status ORDER BY ID DESC LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return {
                'state': row.get('STATE', row.get('state', '')),
                'error_no': int(row.get('ERROR_NO', row.get('error_no', 0))),
                'error_message': row.get('ERROR_MESSAGE', row.get('error_message', '')),
                'source': row.get('SOURCE', row.get('source', '')),
            }
        return {
            'state': row[1] if len(row) > 1 else '',
            'error_no': int(row[3]) if len(row) > 3 else 0,
            'error_message': row[4] if len(row) > 4 else '',
            'source': row[2] if len(row) > 2 else '',
        }
    except Exception:
        return None


def get_clone_progress(cursor):
    """Get clone progress stages from performance_schema."""
    progress = []
    try:
        cursor.execute("SELECT * FROM performance_schema.clone_progress ORDER BY ID, STAGE")
        rows = cursor.fetchall()
        for row in rows:
            if isinstance(row, dict):
                progress.append({
                    'stage': row.get('STAGE', row.get('stage', '')),
                    'state': row.get('STATE', row.get('state', '')),
                    'estimate': int(row.get('ESTIMATE', row.get('estimate', 0))),
                    'data': int(row.get('DATA', row.get('data', 0))),
                })
            else:
                progress.append({
                    'stage': row[1] if len(row) > 1 else '',
                    'state': row[2] if len(row) > 2 else '',
                    'estimate': int(row[4]) if len(row) > 4 else 0,
                    'data': int(row[5]) if len(row) > 5 else 0,
                })
    except Exception:
        pass
    return progress


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        state=dict(type='str', choices=['present', 'absent', 'clone_local', 'clone_remote'], default='present'),
        data_directory=dict(type='path'),
        donor_host=dict(type='str'),
        donor_port=dict(type='int', default=3306),
        donor_user=dict(type='str'),
        donor_password=dict(type='str', no_log=True),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ('state', 'clone_local', ['data_directory']),
            ('state', 'clone_remote', ['donor_host', 'donor_user', 'donor_password']),
        ],
    )

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)

    try:
        cursor, db_conn = mysql_connect(
            module,
            module.params['login_user'],
            module.params['login_password'],
            module.params['config_file'],
            module.params['client_cert'],
            module.params['client_key'],
            module.params['ca_cert'],
            connect_timeout=module.params['connect_timeout'],
            check_hostname=module.params['check_hostname'],
        )
    except Exception as e:
        module.fail_json(msg="Unable to connect to database: %s" % to_native(e))

    # Validate MySQL version
    server_implementation = get_server_implementation(cursor)
    server_version = get_server_version(cursor)

    if server_implementation == 'mariadb':
        module.fail_json(msg="The MySQL Clone Plugin is not available on MariaDB")

    version_str = server_version.split('-')[0]
    if LooseVersion(version_str) < LooseVersion("8.0.17"):
        module.fail_json(msg="The MySQL Clone Plugin requires MySQL 8.0.17 or later (found %s)" % server_version)

    state = module.params['state']
    changed = False
    executed_commands = []
    result = dict(changed=False)

    plugin_present = is_plugin_installed(cursor)
    result['plugin_installed'] = plugin_present

    if state == 'present':
        if not plugin_present:
            query = "INSTALL PLUGIN clone SONAME 'mysql_clone.so'"
            executed_commands.append(query)
            if not module.check_mode:
                try:
                    cursor.execute(query)
                except Exception as e:
                    module.fail_json(msg="Failed to install clone plugin: %s" % to_native(e))
            changed = True
            result['plugin_installed'] = True

    elif state == 'absent':
        if plugin_present:
            query = "UNINSTALL PLUGIN clone"
            executed_commands.append(query)
            if not module.check_mode:
                try:
                    cursor.execute(query)
                except Exception as e:
                    module.fail_json(msg="Failed to uninstall clone plugin: %s" % to_native(e))
            changed = True
            result['plugin_installed'] = False

    elif state == 'clone_local':
        # Ensure plugin is installed first
        if not plugin_present:
            query = "INSTALL PLUGIN clone SONAME 'mysql_clone.so'"
            executed_commands.append(query)
            if not module.check_mode:
                try:
                    cursor.execute(query)
                except Exception as e:
                    module.fail_json(msg="Failed to install clone plugin: %s" % to_native(e))
            result['plugin_installed'] = True

        query = "CLONE LOCAL DATA DIRECTORY = '%s'" % module.params['data_directory']
        executed_commands.append(query)
        if module.check_mode:
            changed = True
        else:
            try:
                cursor.execute(query)
            except Exception as e:
                module.fail_json(msg="Local clone failed: %s" % to_native(e))
            changed = True
            result['clone_status'] = get_clone_status(cursor)
            result['clone_progress'] = get_clone_progress(cursor)

    elif state == 'clone_remote':
        # Ensure plugin is installed first
        if not plugin_present:
            query = "INSTALL PLUGIN clone SONAME 'mysql_clone.so'"
            executed_commands.append(query)
            if not module.check_mode:
                try:
                    cursor.execute(query)
                except Exception as e:
                    module.fail_json(msg="Failed to install clone plugin: %s" % to_native(e))
            result['plugin_installed'] = True

        # Set the donor as a valid clone source
        set_donor_query = "SET GLOBAL clone_valid_donor_list = '%s:%d'" % (
            module.params['donor_host'], module.params['donor_port'])
        executed_commands.append(set_donor_query)

        clone_query = "CLONE INSTANCE FROM '%s'@'%s':%d IDENTIFIED BY '***'" % (
            module.params['donor_user'],
            module.params['donor_host'],
            module.params['donor_port'],
        )
        # Actual query with real password
        clone_query_real = "CLONE INSTANCE FROM '%s'@'%s':%d IDENTIFIED BY '%s'" % (
            module.params['donor_user'],
            module.params['donor_host'],
            module.params['donor_port'],
            module.params['donor_password'],
        )
        executed_commands.append(clone_query)  # Log the redacted version

        if module.check_mode:
            changed = True
        else:
            try:
                cursor.execute(set_donor_query)
                cursor.execute(clone_query_real)
            except Exception as e:
                module.fail_json(msg="Remote clone failed: %s" % to_native(e))
            changed = True

            # Re-connect after clone (connection may be reset)
            try:
                cursor, db_conn = mysql_connect(
                    module,
                    module.params['login_user'],
                    module.params['login_password'],
                    module.params['config_file'],
                    module.params['client_cert'],
                    module.params['client_key'],
                    module.params['ca_cert'],
                    connect_timeout=module.params['connect_timeout'],
                    check_hostname=module.params['check_hostname'],
                )
                result['clone_status'] = get_clone_status(cursor)
                result['clone_progress'] = get_clone_progress(cursor)
            except Exception:
                result['clone_status'] = {'state': 'Connection reset after clone - check server status'}

    result['changed'] = changed
    result['executed_commands'] = executed_commands
    module.exit_json(**result)


if __name__ == '__main__':
    main()
