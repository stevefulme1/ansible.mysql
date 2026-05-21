#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible MySQL collection contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_slow_log

short_description: Configure MySQL slow query log settings

description:
  - Configure MySQL slow query log global variables.
  - Sets C(slow_query_log), C(long_query_time), C(slow_query_log_file),
    C(log_output), and C(log_slow_extra) via C(SET GLOBAL).
  - Use this module for declarative slow-log configuration instead of
    calling M(ansible.mysql.mysql_variables) multiple times.

version_added: "5.1.0"

author:
  - Ansible MySQL collection contributors (@ansible-collections)

options:
  slow_query_log:
    description:
      - Enable or disable the slow query log.
    type: bool
  long_query_time:
    description:
      - Queries taking longer than this many seconds are logged.
      - Accepts float values for sub-second precision.
    type: float
  slow_query_log_file:
    description:
      - Path to the slow query log file.
    type: str
  log_output:
    description:
      - Where to write slow query log output.
      - V(FILE), V(TABLE), or V(NONE).
    type: str
    choices: ['FILE', 'TABLE', 'NONE']
  log_slow_extra:
    description:
      - Whether to log extra information in the slow query log.
      - Available in MySQL 8.0.14+.
    type: bool

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
  - ansible.mysql.mysql

notes:
  - Changes are applied at runtime via C(SET GLOBAL) and do not persist across server restarts.
  - To persist, also update the MySQL configuration file or use M(ansible.mysql.mysql_variables) with C(mode=persist).
  - C(log_slow_extra) is only available in MySQL 8.0.14 or later.
  - Compatible with MySQL and MariaDB (MariaDB may not support all options).
'''

EXAMPLES = r'''
- name: Enable slow query log with 2-second threshold
  ansible.mysql.mysql_slow_log:
    slow_query_log: true
    long_query_time: 2.0

- name: Log slow queries to a table
  ansible.mysql.mysql_slow_log:
    slow_query_log: true
    log_output: TABLE

- name: Configure all slow log settings
  ansible.mysql.mysql_slow_log:
    slow_query_log: true
    long_query_time: 1.5
    slow_query_log_file: /var/log/mysql/slow.log
    log_output: FILE
    log_slow_extra: true

- name: Disable slow query log
  ansible.mysql.mysql_slow_log:
    slow_query_log: false
'''

RETURN = r'''
queries:
  description: List of executed queries which modified state.
  returned: changed
  type: list
  sample: ["SET GLOBAL `slow_query_log` = 1", "SET GLOBAL `long_query_time` = 2.0"]
settings:
  description: Current slow log settings after applying changes.
  returned: always
  type: dict
  sample:
    slow_query_log: "ON"
    long_query_time: "2.000000"
    slow_query_log_file: "/var/lib/mysql/slow.log"
    log_output: "FILE"
'''

import warnings

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.database import mysql_quote_identifier
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect, mysql_driver, mysql_driver_fail_msg, mysql_common_argument_spec,
)
from ansible.module_utils.common.text.converters import to_native


SLOW_LOG_VARS = [
    'slow_query_log',
    'long_query_time',
    'slow_query_log_file',
    'log_output',
    'log_slow_extra',
]


def get_current_settings(cursor):
    """Return dict of current slow-log related variable values."""
    settings = {}
    for var in SLOW_LOG_VARS:
        cursor.execute("SHOW VARIABLES LIKE %s", (var,))
        row = cursor.fetchone()
        if row:
            settings[var] = row[1]
    return settings


def normalize_value(var_name, param_value):
    """Convert module param value to the string MySQL uses for comparison."""
    if param_value is None:
        return None
    if var_name in ('slow_query_log', 'log_slow_extra'):
        return 'ON' if param_value else 'OFF'
    if var_name == 'long_query_time':
        return str(param_value)
    return str(param_value)


def set_value_for_query(var_name, param_value):
    """Return the value to pass to SET GLOBAL."""
    if var_name in ('slow_query_log', 'log_slow_extra'):
        return 1 if param_value else 0
    return param_value


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        slow_query_log=dict(type='bool'),
        long_query_time=dict(type='float'),
        slow_query_log_file=dict(type='str'),
        log_output=dict(type='str', choices=['FILE', 'TABLE', 'NONE']),
        log_slow_extra=dict(type='bool'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[['slow_query_log', 'long_query_time', 'slow_query_log_file',
                          'log_output', 'log_slow_extra']],
    )

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)
    else:
        warnings.filterwarnings('error', category=mysql_driver.Warning)

    try:
        cursor, db_conn = mysql_connect(
            module,
            module.params['login_user'],
            module.params['login_password'],
            module.params['config_file'],
            module.params['client_cert'],
            module.params['client_key'],
            module.params['ca_cert'],
            'mysql',
            connect_timeout=module.params['connect_timeout'],
            check_hostname=module.params['check_hostname'],
        )
    except Exception as e:
        module.fail_json(msg="unable to connect to database: %s" % to_native(e))

    current = get_current_settings(cursor)
    changed = False
    queries = []

    for var_name in SLOW_LOG_VARS:
        param_value = module.params.get(var_name)
        if param_value is None:
            continue

        desired = normalize_value(var_name, param_value)
        actual = current.get(var_name)

        if actual is None:
            # Variable not present (e.g., log_slow_extra on older MySQL)
            module.warn("Variable '%s' not available on this server version" % var_name)
            continue

        # For long_query_time, compare as float
        if var_name == 'long_query_time':
            needs_change = abs(float(actual) - float(desired)) > 0.000001
        else:
            needs_change = actual != desired

        if needs_change:
            changed = True
            query_val = set_value_for_query(var_name, param_value)
            query = "SET GLOBAL %s = " % mysql_quote_identifier(var_name, 'vars')
            if not module.check_mode:
                cursor.execute(query + "%s", (query_val,))
            queries.append("SET GLOBAL %s = %s" % (mysql_quote_identifier(var_name, 'vars'), query_val))

    # Re-read settings after changes
    if not module.check_mode:
        final_settings = get_current_settings(cursor)
    else:
        final_settings = current

    module.exit_json(changed=changed, queries=queries, settings=final_settings)


if __name__ == '__main__':
    main()
