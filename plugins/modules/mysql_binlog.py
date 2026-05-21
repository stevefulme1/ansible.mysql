#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_binlog
short_description: Manage MySQL or MariaDB binary log settings and purge operations
description:
  - Configure binary log format and expiration via C(SET GLOBAL).
  - Purge binary logs older than a specified date or before a specific log file.
  - This module modifies runtime global variables; changes do not persist across
    restarts unless also written to C(my.cnf) or used with C(SET PERSIST) (MySQL 8.0+).
version_added: '5.1.0'
options:
  binlog_format:
    description:
      - Set the global binary log format.
      - Supported values are C(ROW), C(STATEMENT), and C(MIXED).
      - Not all MySQL versions support runtime changes to this variable.
    type: str
    choices: ['ROW', 'STATEMENT', 'MIXED']
  binlog_expire_logs_seconds:
    description:
      - Set C(binlog_expire_logs_seconds) globally.
      - Number of seconds after which binary logs are automatically purged.
      - Requires MySQL 8.0+ or MariaDB 10.6+.
      - Set to C(0) to disable automatic purging.
    type: int
  purge_before_date:
    description:
      - Purge binary logs created before this date.
      - Format should be C(YYYY-MM-DD HH:MM:SS).
      - Mutually exclusive with I(purge_before_log).
    type: str
  purge_before_log:
    description:
      - Purge binary logs before the specified log file name.
      - Example C(mysql-bin.000010).
      - Mutually exclusive with I(purge_before_date).
    type: str
author:
  - Ansible community (@ansible-collections)
notes:
  - Compatible with MariaDB or MySQL.
  - Purge operations require C(SUPER) or C(BINLOG ADMIN) privilege.
  - Setting C(binlog_format) at runtime may not be supported in all MySQL versions.
attributes:
  check_mode:
    support: partial
    details:
      - In check mode, SET GLOBAL and PURGE commands are not executed.
  idempotent:
    support: partial
    details:
      - SET GLOBAL operations are idempotent when the target value matches the current value.
      - PURGE operations are not idempotent.
extends_documentation_fragment:
  - ansible.mysql.mysql
seealso:
  - module: ansible.mysql.mysql_binlog_info
  - module: ansible.mysql.mysql_variables
  - name: Binary log configuration
    description: MySQL binary log configuration reference.
    link: https://dev.mysql.com/doc/refman/8.0/en/replication-options-binary-log.html
  - name: PURGE BINARY LOGS statement
    description: MySQL PURGE BINARY LOGS statement reference.
    link: https://dev.mysql.com/doc/refman/8.0/en/purge-binary-logs.html
'''

EXAMPLES = r'''
- name: Set binary log format to ROW
  ansible.mysql.mysql_binlog:
    binlog_format: ROW
    login_unix_socket: /run/mysqld/mysqld.sock

- name: Set binary log expiration to 7 days
  ansible.mysql.mysql_binlog:
    binlog_expire_logs_seconds: 604800

- name: Purge binary logs older than a specific date
  ansible.mysql.mysql_binlog:
    purge_before_date: "2024-01-01 00:00:00"

- name: Purge binary logs before a specific log file
  ansible.mysql.mysql_binlog:
    purge_before_log: mysql-bin.000010
'''

RETURN = r'''
binlog_format:
  description: The binary log format after module execution.
  returned: when binlog_format is set
  type: str
  sample: "ROW"
binlog_expire_logs_seconds:
  description: The binary log expiration setting after module execution.
  returned: when binlog_expire_logs_seconds is set
  type: int
  sample: 604800
purged:
  description: Whether a purge operation was executed.
  returned: when purge_before_date or purge_before_log is set
  type: bool
  sample: true
executed_commands:
  description: List of SQL commands executed.
  returned: always
  type: list
  sample: ["SET GLOBAL binlog_format = 'ROW'"]
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
    mysql_common_argument_spec,
)
from ansible.module_utils.common.text.converters import to_native


def get_global_variable(cursor, var_name):
    """Fetch a global variable value."""
    cursor.execute("SELECT @@GLOBAL.%s" % var_name)
    row = cursor.fetchone()
    if isinstance(row, dict):
        return list(row.values())[0]
    return row[0]


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        binlog_format=dict(type='str', choices=['ROW', 'STATEMENT', 'MIXED']),
        binlog_expire_logs_seconds=dict(type='int'),
        purge_before_date=dict(type='str'),
        purge_before_log=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        mutually_exclusive=[
            ('purge_before_date', 'purge_before_log'),
        ],
        required_one_of=[
            ('binlog_format', 'binlog_expire_logs_seconds', 'purge_before_date', 'purge_before_log'),
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

    changed = False
    executed_commands = []
    result = dict(changed=False)

    # Handle binlog_format
    if module.params['binlog_format'] is not None:
        target_format = module.params['binlog_format']
        try:
            current = get_global_variable(cursor, 'binlog_format')
        except Exception:
            current = None

        if current is None or str(current).upper() != target_format.upper():
            query = "SET GLOBAL binlog_format = '%s'" % target_format
            executed_commands.append(query)
            if not module.check_mode:
                try:
                    cursor.execute(query)
                except Exception as e:
                    module.fail_json(msg="Failed to set binlog_format: %s" % to_native(e))
            changed = True
        result['binlog_format'] = target_format

    # Handle binlog_expire_logs_seconds
    if module.params['binlog_expire_logs_seconds'] is not None:
        target_val = module.params['binlog_expire_logs_seconds']
        try:
            current = int(get_global_variable(cursor, 'binlog_expire_logs_seconds'))
        except Exception:
            current = None

        if current is None or current != target_val:
            query = "SET GLOBAL binlog_expire_logs_seconds = %d" % target_val
            executed_commands.append(query)
            if not module.check_mode:
                try:
                    cursor.execute(query)
                except Exception as e:
                    module.fail_json(msg="Failed to set binlog_expire_logs_seconds: %s" % to_native(e))
            changed = True
        result['binlog_expire_logs_seconds'] = target_val

    # Handle purge operations
    if module.params['purge_before_date'] is not None:
        query = "PURGE BINARY LOGS BEFORE '%s'" % module.params['purge_before_date']
        executed_commands.append(query)
        if not module.check_mode:
            try:
                cursor.execute(query)
            except Exception as e:
                module.fail_json(msg="Failed to purge binary logs: %s" % to_native(e))
        changed = True
        result['purged'] = True

    if module.params['purge_before_log'] is not None:
        query = "PURGE BINARY LOGS TO '%s'" % module.params['purge_before_log']
        executed_commands.append(query)
        if not module.check_mode:
            try:
                cursor.execute(query)
            except Exception as e:
                module.fail_json(msg="Failed to purge binary logs: %s" % to_native(e))
        changed = True
        result['purged'] = True

    result['changed'] = changed
    result['executed_commands'] = executed_commands
    module.exit_json(**result)


if __name__ == '__main__':
    main()
