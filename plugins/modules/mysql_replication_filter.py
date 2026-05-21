#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_replication_filter
short_description: Manage MySQL replication filters
description:
- Manages MySQL replication filters using C(CHANGE REPLICATION FILTER).
- Supports C(REPLICATE_DO_DB), C(REPLICATE_IGNORE_DB), C(REPLICATE_DO_TABLE),
  C(REPLICATE_IGNORE_TABLE), C(REPLICATE_WILD_DO_TABLE), and C(REPLICATE_WILD_IGNORE_TABLE).
- Supports C(FOR CHANNEL) for multi-source replication.
- Filter state is read from C(SHOW REPLICA STATUS) for idempotency.
version_added: '5.1.0'
author:
- Steve Fulmer (@stevefulme1)
options:
  state:
    description:
    - Whether the filter rules should be present or absent.
    - C(present) sets the given filter rules (replaces existing rules for the specified filter types).
    - C(absent) clears the specified filter types.
    type: str
    choices: [present, absent]
    default: present
  replicate_do_db:
    description:
    - List of databases to replicate.
    type: list
    elements: str
  replicate_ignore_db:
    description:
    - List of databases to ignore during replication.
    type: list
    elements: str
  replicate_do_table:
    description:
    - List of tables to replicate (C(db.table) format).
    type: list
    elements: str
  replicate_ignore_table:
    description:
    - List of tables to ignore during replication (C(db.table) format).
    type: list
    elements: str
  replicate_wild_do_table:
    description:
    - List of wildcard patterns for tables to replicate (e.g., C(db%.t%)).
    type: list
    elements: str
  replicate_wild_ignore_table:
    description:
    - List of wildcard patterns for tables to ignore during replication.
    type: list
    elements: str
  channel:
    description:
    - Name of the replication channel.
    - When specified, the filter is applied C(FOR CHANNEL).
    type: str

notes:
- Compatible with MySQL 8.0+ and MariaDB 10.6+.
- Replication must be stopped before changing filters in most MySQL versions.

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
- ansible.mysql.mysql

seealso:
- module: ansible.mysql.mysql_replication
- name: MySQL CHANGE REPLICATION FILTER reference
  description: Official MySQL documentation for CHANGE REPLICATION FILTER.
  link: https://dev.mysql.com/doc/refman/8.0/en/change-replication-filter.html
'''

EXAMPLES = r'''
- name: Set replication filter to replicate only mydb
  ansible.mysql.mysql_replication_filter:
    replicate_do_db:
      - mydb
    state: present

- name: Ignore specific tables during replication
  ansible.mysql.mysql_replication_filter:
    replicate_ignore_table:
      - mydb.logs
      - mydb.tmp_data
    state: present

- name: Set wildcard replication filter for a channel
  ansible.mysql.mysql_replication_filter:
    replicate_wild_do_table:
      - "mydb.order%"
    channel: channel_1
    state: present

- name: Clear all DO_DB filters
  ansible.mysql.mysql_replication_filter:
    replicate_do_db: []
    state: absent

- name: Set multiple filter types at once
  ansible.mysql.mysql_replication_filter:
    replicate_do_db:
      - production
    replicate_ignore_table:
      - production.debug_log
    state: present
'''

RETURN = r'''
queries:
  description: List of executed queries which modified the server state.
  returned: always
  type: list
  sample: ["CHANGE REPLICATION FILTER REPLICATE_DO_DB = (mydb)"]
filters:
  description: The current replication filter state after changes.
  returned: success
  type: dict
  sample:
    replicate_do_db: ["mydb"]
    replicate_ignore_db: []
'''

import os
import warnings

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
    mysql_common_argument_spec,
)
from ansible.module_utils.common.text.converters import to_native


FILTER_TYPES = [
    'replicate_do_db',
    'replicate_ignore_db',
    'replicate_do_table',
    'replicate_ignore_table',
    'replicate_wild_do_table',
    'replicate_wild_ignore_table',
]

# Mapping from our parameter names to MySQL SHOW REPLICA STATUS column names
_STATUS_KEYS = {
    'replicate_do_db': 'Replicate_Do_DB',
    'replicate_ignore_db': 'Replicate_Ignore_DB',
    'replicate_do_table': 'Replicate_Do_Table',
    'replicate_ignore_table': 'Replicate_Ignore_Table',
    'replicate_wild_do_table': 'Replicate_Wild_Do_Table',
    'replicate_wild_ignore_table': 'Replicate_Wild_Ignore_Table',
}

# Also check Slave_ variants for older MySQL / MariaDB
_STATUS_KEYS_SLAVE = {
    'replicate_do_db': 'Replicate_Do_DB',
    'replicate_ignore_db': 'Replicate_Ignore_DB',
    'replicate_do_table': 'Replicate_Do_Table',
    'replicate_ignore_table': 'Replicate_Ignore_Table',
    'replicate_wild_do_table': 'Replicate_Wild_Do_Table',
    'replicate_wild_ignore_table': 'Replicate_Wild_Ignore_Table',
}

# Mapping from our parameter names to SQL filter clause names
_SQL_FILTER_NAMES = {
    'replicate_do_db': 'REPLICATE_DO_DB',
    'replicate_ignore_db': 'REPLICATE_IGNORE_DB',
    'replicate_do_table': 'REPLICATE_DO_TABLE',
    'replicate_ignore_table': 'REPLICATE_IGNORE_TABLE',
    'replicate_wild_do_table': 'REPLICATE_WILD_DO_TABLE',
    'replicate_wild_ignore_table': 'REPLICATE_WILD_IGNORE_TABLE',
}


def get_current_filters(cursor, channel=None):
    """Get current replication filters from SHOW REPLICA STATUS."""
    query = "SHOW REPLICA STATUS"
    if channel:
        query += " FOR CHANNEL '%s'" % channel

    try:
        cursor.execute(query)
    except Exception:
        # Fall back to SHOW SLAVE STATUS for older versions
        query = "SHOW SLAVE STATUS"
        if channel:
            query += " FOR CHANNEL '%s'" % channel
        try:
            cursor.execute(query)
        except Exception:
            return {}

    status = cursor.fetchone()
    if not status:
        return {}

    filters = {}
    for ftype in FILTER_TYPES:
        key = _STATUS_KEYS.get(ftype, '')
        val = ''
        if isinstance(status, dict):
            val = status.get(key, '')
        if val:
            filters[ftype] = [v.strip() for v in val.split(',') if v.strip()]
        else:
            filters[ftype] = []

    return filters


def build_filter_query(params, state, channel=None):
    """Build the CHANGE REPLICATION FILTER SQL statement."""
    clauses = []

    for ftype in FILTER_TYPES:
        values = params.get(ftype)
        if values is None:
            continue

        sql_name = _SQL_FILTER_NAMES[ftype]

        if state == 'absent':
            clauses.append("%s = ()" % sql_name)
        else:
            if values:
                formatted = ', '.join("'%s'" % v for v in values)
                clauses.append("%s = (%s)" % (sql_name, formatted))
            else:
                clauses.append("%s = ()" % sql_name)

    if not clauses:
        return None

    query = "CHANGE REPLICATION FILTER %s" % ', '.join(clauses)
    if channel:
        query += " FOR CHANNEL '%s'" % channel

    return query


def filters_match(current, desired, state):
    """Check if desired filters already match the current state."""
    for ftype in FILTER_TYPES:
        desired_val = desired.get(ftype)
        if desired_val is None:
            continue

        current_val = sorted(current.get(ftype, []))

        if state == 'absent':
            if current_val:
                return False
        else:
            if sorted(desired_val) != current_val:
                return False

    return True


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        state=dict(type='str', default='present', choices=['present', 'absent']),
        replicate_do_db=dict(type='list', elements='str'),
        replicate_ignore_db=dict(type='list', elements='str'),
        replicate_do_table=dict(type='list', elements='str'),
        replicate_ignore_table=dict(type='list', elements='str'),
        replicate_wild_do_table=dict(type='list', elements='str'),
        replicate_wild_ignore_table=dict(type='list', elements='str'),
        channel=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    state = module.params['state']
    channel = module.params['channel']

    # Collect desired filter values
    desired = {}
    any_filter_specified = False
    for ftype in FILTER_TYPES:
        val = module.params[ftype]
        if val is not None:
            desired[ftype] = val
            any_filter_specified = True

    if not any_filter_specified:
        module.fail_json(msg="At least one replication filter type must be specified.")

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)
    else:
        warnings.filterwarnings('error', category=mysql_driver.Warning)

    login_password = module.params["login_password"]
    login_user = module.params["login_user"]
    ssl_cert = module.params["client_cert"]
    ssl_key = module.params["client_key"]
    ssl_ca = module.params["ca_cert"]
    check_hostname = module.params["check_hostname"]
    connect_timeout = module.params['connect_timeout']
    config_file = module.params['config_file']

    try:
        cursor, db_conn = mysql_connect(
            module, login_user, login_password, config_file,
            ssl_cert, ssl_key, ssl_ca, None,
            cursor_class='DictCursor',
            connect_timeout=connect_timeout,
            check_hostname=check_hostname,
        )
    except Exception as e:
        if os.path.exists(config_file):
            module.fail_json(
                msg="unable to connect to database, check login_user and "
                    "login_password are correct or %s has the credentials. "
                    "Exception message: %s" % (config_file, to_native(e)))
        else:
            module.fail_json(
                msg="unable to find %s. Exception message: %s" % (config_file, to_native(e)))

    executed_queries = []

    # Get current state
    current_filters = get_current_filters(cursor, channel)

    # Check idempotency
    if filters_match(current_filters, desired, state):
        module.exit_json(
            changed=False,
            queries=executed_queries,
            filters=current_filters,
        )

    # Build and execute query
    query = build_filter_query(module.params, state, channel)
    if query is None:
        module.exit_json(changed=False, queries=executed_queries, filters=current_filters)

    if module.check_mode:
        module.exit_json(changed=True, queries=[query], filters=current_filters)

    try:
        executed_queries.append(query)
        cursor.execute(query)
    except Exception as e:
        module.fail_json(
            msg="Failed to execute replication filter change: %s" % to_native(e),
            queries=executed_queries,
        )

    # Read back current state
    new_filters = get_current_filters(cursor, channel)

    warnings.simplefilter("ignore")
    module.exit_json(changed=True, queries=executed_queries, filters=new_filters)


if __name__ == '__main__':
    main()
