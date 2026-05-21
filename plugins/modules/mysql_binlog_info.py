#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_binlog_info
short_description: Gather MySQL or MariaDB binary log information
description:
  - Retrieve binary log status and list of binary log files from a MySQL or MariaDB server.
  - Uses C(SHOW BINARY LOG STATUS) on MySQL 8.0.22+ and falls back to
    C(SHOW MASTER STATUS) on older versions.
  - Lists all binary log files via C(SHOW BINARY LOGS).
  - This is a read-only information module; it does not modify the server.
version_added: '5.1.0'
options: {}
author:
  - Ansible community (@ansible-collections)
notes:
  - Compatible with MariaDB or MySQL.
  - Requires C(REPLICATION CLIENT) or C(SUPER) privilege.
  - Uses C(SHOW BINARY LOG STATUS) (MySQL 8.0.22+) with automatic fallback
    to C(SHOW MASTER STATUS) for older versions.
attributes:
  check_mode:
    support: full
    details:
      - This module is read-only and works identically in check mode.
  idempotent:
    support: full
    details:
      - This module is read-only and always reports changed=false.
extends_documentation_fragment:
  - ansible.mysql.mysql
seealso:
  - module: ansible.mysql.mysql_binlog
  - module: ansible.mysql.mysql_replication
  - name: SHOW BINARY LOG STATUS
    description: MySQL SHOW BINARY LOG STATUS reference.
    link: https://dev.mysql.com/doc/refman/8.0/en/show-binary-log-status.html
  - name: SHOW BINARY LOGS
    description: MySQL SHOW BINARY LOGS reference.
    link: https://dev.mysql.com/doc/refman/8.0/en/show-binary-logs.html
'''

EXAMPLES = r'''
- name: Get binary log status and file list
  ansible.mysql.mysql_binlog_info:
    login_unix_socket: /run/mysqld/mysqld.sock
  register: binlog

- name: Display current binary log position
  ansible.builtin.debug:
    msg: "File: {{ binlog.status.file }}, Position: {{ binlog.status.position }}"

- name: Show all binary log files
  ansible.builtin.debug:
    var: binlog.logs
'''

RETURN = r'''
status:
  description: Current binary log status from SHOW BINARY LOG STATUS / SHOW MASTER STATUS.
  returned: always
  type: dict
  contains:
    file:
      description: Name of the current binary log file.
      type: str
      sample: "mysql-bin.000042"
    position:
      description: Current position in the binary log file.
      type: int
      sample: 154
    binlog_do_db:
      description: Databases being logged (if configured).
      type: str
      sample: ""
    binlog_ignore_db:
      description: Databases being ignored (if configured).
      type: str
      sample: ""
  sample:
    file: "mysql-bin.000042"
    position: 154
    binlog_do_db: ""
    binlog_ignore_db: ""
logs:
  description: List of all binary log files on the server.
  returned: always
  type: list
  elements: dict
  contains:
    log_name:
      description: Binary log file name.
      type: str
      sample: "mysql-bin.000001"
    file_size:
      description: Size of the binary log file in bytes.
      type: int
      sample: 177
  sample:
    - log_name: "mysql-bin.000001"
      file_size: 177
    - log_name: "mysql-bin.000002"
      file_size: 154
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
    mysql_common_argument_spec,
    get_server_version,
)
from ansible_collections.ansible.mysql.plugins.module_utils.version import LooseVersion
from ansible.module_utils.common.text.converters import to_native


def get_binlog_status(cursor, server_version):
    """Get current binary log status, with fallback for older MySQL."""
    # MySQL 8.0.22+ uses SHOW BINARY LOG STATUS
    # Older versions use SHOW MASTER STATUS
    if LooseVersion(server_version.split('-')[0]) >= LooseVersion("8.0.22"):
        try:
            cursor.execute("SHOW BINARY LOG STATUS")
            row = cursor.fetchone()
            if row is not None:
                return _parse_status_row(row)
        except Exception:
            pass

    # Fallback to SHOW MASTER STATUS
    try:
        cursor.execute("SHOW MASTER STATUS")
        row = cursor.fetchone()
        if row is not None:
            return _parse_status_row(row)
    except Exception as e:
        return {'error': to_native(e)}

    return {}


def _parse_status_row(row):
    """Parse a status row (dict or tuple) into a normalized dict."""
    if isinstance(row, dict):
        # Normalize key names (MySQL uses File/Position, some use lowercase)
        result = {}
        for key, value in row.items():
            normalized_key = key.lower().replace(' ', '_')
            if normalized_key == 'file':
                result['file'] = value
            elif normalized_key == 'position':
                result['position'] = int(value)
            elif normalized_key == 'binlog_do_db':
                result['binlog_do_db'] = value or ''
            elif normalized_key == 'binlog_ignore_db':
                result['binlog_ignore_db'] = value or ''
            elif normalized_key == 'executed_gtid_set':
                result['executed_gtid_set'] = value or ''
        return result
    else:
        # Tuple result
        return {
            'file': row[0],
            'position': int(row[1]),
            'binlog_do_db': row[2] if len(row) > 2 else '',
            'binlog_ignore_db': row[3] if len(row) > 3 else '',
        }


def get_binlog_list(cursor):
    """Get list of binary log files."""
    logs = []
    try:
        cursor.execute("SHOW BINARY LOGS")
        rows = cursor.fetchall()
        for row in rows:
            if isinstance(row, dict):
                logs.append({
                    'log_name': row.get('Log_name', row.get('log_name', '')),
                    'file_size': int(row.get('File_size', row.get('file_size', 0))),
                })
            else:
                logs.append({
                    'log_name': row[0],
                    'file_size': int(row[1]),
                })
    except Exception as e:
        return [], to_native(e)

    return logs, None


def main():
    argument_spec = mysql_common_argument_spec()

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
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

    server_version = get_server_version(cursor)
    status = get_binlog_status(cursor, server_version)
    logs, error = get_binlog_list(cursor)

    result = dict(
        changed=False,
        status=status,
        logs=logs,
    )

    if error:
        result['logs_error'] = error

    module.exit_json(**result)


if __name__ == '__main__':
    main()
