#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_group_replication
short_description: Manage MySQL Group Replication
description:
  - Start, stop, and bootstrap MySQL Group Replication.
  - Switch between single-primary and multi-primary modes.
  - Query group replication member status.
version_added: '5.1.0'
author:
  - Steve Fulmer (@stevefulme1)
options:
  mode:
    description:
      - Module operating mode.
      - C(start) starts Group Replication on the target instance.
      - C(stop) stops Group Replication on the target instance.
      - C(bootstrap) bootstraps a new Group Replication group (starts GR with C(group_replication_bootstrap_group=ON)).
      - C(status) retrieves the current Group Replication member status.
      - C(switch_to_single_primary) switches the group to single-primary mode.
      - C(switch_to_multi_primary) switches the group to multi-primary mode.
    type: str
    choices:
      - start
      - stop
      - bootstrap
      - status
      - switch_to_single_primary
      - switch_to_multi_primary
    required: true
  primary_uuid:
    description:
      - The server UUID to become the new primary when switching to single-primary mode.
      - Only used with O(mode=switch_to_single_primary).
      - If not specified, the group elects a primary automatically.
    type: str

attributes:
  check_mode:
    support: partial
    details:
      - In check mode, O(mode=status) runs normally.
      - Other modes report what would change without executing SQL.
  idempotent:
    support: partial
    details:
      - C(start) is idempotent if Group Replication is already running.
      - C(stop) is idempotent if Group Replication is already stopped.
      - C(bootstrap), C(switch_to_single_primary), and C(switch_to_multi_primary) always report changed.

extends_documentation_fragment:
  - ansible.mysql.mysql

seealso:
  - module: ansible.mysql.mysql_innodb_cluster
  - module: ansible.mysql.mysql_replication
  - name: MySQL Group Replication documentation
    description: Official MySQL Group Replication reference.
    link: https://dev.mysql.com/doc/refman/8.0/en/group-replication.html

notes:
  - Compatible with MySQL 5.7.17+ and MySQL 8.0+.
  - Not compatible with MariaDB (MariaDB does not support Group Replication).
  - The C(switch_to_single_primary) and C(switch_to_multi_primary) modes require MySQL 8.0.13+.
'''

EXAMPLES = r'''
- name: Bootstrap a new Group Replication group
  ansible.mysql.mysql_group_replication:
    mode: bootstrap
    login_user: root
    login_password: secret
    login_host: 192.0.2.1

- name: Start Group Replication on a secondary member
  ansible.mysql.mysql_group_replication:
    mode: start
    login_user: root
    login_password: secret
    login_host: 192.0.2.2

- name: Stop Group Replication
  ansible.mysql.mysql_group_replication:
    mode: stop
    login_user: root
    login_password: secret

- name: Get Group Replication member status
  ansible.mysql.mysql_group_replication:
    mode: status
    login_user: root
    login_password: secret
  register: gr_status

- name: Switch to single-primary mode with a specific primary
  ansible.mysql.mysql_group_replication:
    mode: switch_to_single_primary
    primary_uuid: "3e11fa47-71ca-11e1-9e33-c80aa9429562"
    login_user: root
    login_password: secret

- name: Switch to multi-primary mode
  ansible.mysql.mysql_group_replication:
    mode: switch_to_multi_primary
    login_user: root
    login_password: secret
'''

RETURN = r'''
queries:
  description: List of executed queries which modified DB state.
  returned: always
  type: list
  sample: ["START GROUP_REPLICATION"]
members:
  description: List of group replication members (returned when O(mode=status)).
  returned: when mode is status
  type: list
  elements: dict
  contains:
    channel_name:
      description: The replication channel name.
      type: str
      returned: always
    member_id:
      description: The server UUID of the member.
      type: str
      returned: always
    member_host:
      description: The hostname of the member.
      type: str
      returned: always
    member_port:
      description: The port of the member.
      type: int
      returned: always
    member_state:
      description: The state of the member (C(ONLINE), C(RECOVERING), C(OFFLINE), C(ERROR), C(UNREACHABLE)).
      type: str
      returned: always
    member_role:
      description: The role of the member (C(PRIMARY), C(SECONDARY)).
      type: str
      returned: always
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

executed_queries = []


def get_gr_member_state(cursor):
    """Get the Group Replication state of the current member.

    Returns the MEMBER_STATE string or None if GR is not configured.
    """
    try:
        cursor.execute(
            "SELECT MEMBER_STATE FROM performance_schema.replication_group_members "
            "WHERE MEMBER_ID = @@server_uuid")
        row = cursor.fetchone()
        if row:
            if isinstance(row, dict):
                return row.get('MEMBER_STATE') or row.get('member_state')
            return row[0]
    except Exception:
        pass
    return None


def get_gr_members(cursor):
    """Get all Group Replication members from performance_schema."""
    members = []
    try:
        cursor.execute(
            "SELECT CHANNEL_NAME, MEMBER_ID, MEMBER_HOST, MEMBER_PORT, "
            "MEMBER_STATE, MEMBER_ROLE "
            "FROM performance_schema.replication_group_members")
        rows = cursor.fetchall()
        for row in rows:
            if isinstance(row, dict):
                members.append({
                    'channel_name': row.get('CHANNEL_NAME', ''),
                    'member_id': row.get('MEMBER_ID', ''),
                    'member_host': row.get('MEMBER_HOST', ''),
                    'member_port': int(row.get('MEMBER_PORT', 0)),
                    'member_state': row.get('MEMBER_STATE', ''),
                    'member_role': row.get('MEMBER_ROLE', ''),
                })
            else:
                members.append({
                    'channel_name': row[0],
                    'member_id': row[1],
                    'member_host': row[2],
                    'member_port': int(row[3]),
                    'member_state': row[4],
                    'member_role': row[5],
                })
    except Exception:
        pass
    return members


def start_group_replication(cursor):
    """Start Group Replication."""
    query = "START GROUP_REPLICATION"
    executed_queries.append(query)
    cursor.execute(query)


def stop_group_replication(cursor):
    """Stop Group Replication."""
    query = "STOP GROUP_REPLICATION"
    executed_queries.append(query)
    cursor.execute(query)


def bootstrap_group_replication(cursor):
    """Bootstrap Group Replication (first member)."""
    q1 = "SET GLOBAL group_replication_bootstrap_group=ON"
    executed_queries.append(q1)
    cursor.execute(q1)

    q2 = "START GROUP_REPLICATION"
    executed_queries.append(q2)
    cursor.execute(q2)

    q3 = "SET GLOBAL group_replication_bootstrap_group=OFF"
    executed_queries.append(q3)
    cursor.execute(q3)


def switch_to_single_primary(cursor, primary_uuid=None):
    """Switch to single-primary mode."""
    if primary_uuid:
        query = "SELECT group_replication_switch_to_single_primary_mode('%s')" % primary_uuid
    else:
        query = "SELECT group_replication_switch_to_single_primary_mode()"
    executed_queries.append(query)
    cursor.execute(query)


def switch_to_multi_primary(cursor):
    """Switch to multi-primary mode."""
    query = "SELECT group_replication_switch_to_multi_primary_mode()"
    executed_queries.append(query)
    cursor.execute(query)


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        mode=dict(type='str', required=True, choices=[
            'start', 'stop', 'bootstrap', 'status',
            'switch_to_single_primary', 'switch_to_multi_primary']),
        primary_uuid=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    mode = module.params['mode']
    primary_uuid = module.params['primary_uuid']

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)

    warnings.filterwarnings('error', category=mysql_driver.Warning)

    login_user = module.params['login_user']
    login_password = module.params['login_password']
    config_file = module.params['config_file']
    ssl_cert = module.params['client_cert']
    ssl_key = module.params['client_key']
    ssl_ca = module.params['ca_cert']
    check_hostname = module.params['check_hostname']
    connect_timeout = module.params['connect_timeout']

    try:
        cursor, db_conn = mysql_connect(
            module, login_user, login_password, config_file,
            ssl_cert, ssl_key, ssl_ca, None,
            cursor_class='DictCursor',
            connect_timeout=connect_timeout,
            check_hostname=check_hostname)
    except Exception as e:
        if os.path.exists(config_file):
            module.fail_json(
                msg="unable to connect to database, check login_user and "
                    "login_password are correct or %s has the credentials. "
                    "Exception message: %s" % (config_file, to_native(e)))
        else:
            module.fail_json(
                msg="unable to find %s. Exception message: %s" % (config_file, to_native(e)))

    if mode == 'status':
        members = get_gr_members(cursor)
        module.exit_json(changed=False, members=members, queries=executed_queries)

    elif mode == 'start':
        state = get_gr_member_state(cursor)
        if state and state.upper() == 'ONLINE':
            module.exit_json(changed=False, msg="Group Replication already running",
                             queries=executed_queries)
        if module.check_mode:
            module.exit_json(changed=True, msg="Group Replication would be started",
                             queries=executed_queries)
        try:
            start_group_replication(cursor)
        except Exception as e:
            module.fail_json(msg="Failed to start Group Replication: %s" % to_native(e),
                             queries=executed_queries)
        module.exit_json(changed=True, msg="Group Replication started", queries=executed_queries)

    elif mode == 'stop':
        state = get_gr_member_state(cursor)
        if not state or state.upper() == 'OFFLINE':
            module.exit_json(changed=False, msg="Group Replication already stopped",
                             queries=executed_queries)
        if module.check_mode:
            module.exit_json(changed=True, msg="Group Replication would be stopped",
                             queries=executed_queries)
        try:
            stop_group_replication(cursor)
        except Exception as e:
            module.fail_json(msg="Failed to stop Group Replication: %s" % to_native(e),
                             queries=executed_queries)
        module.exit_json(changed=True, msg="Group Replication stopped", queries=executed_queries)

    elif mode == 'bootstrap':
        if module.check_mode:
            module.exit_json(changed=True, msg="Group Replication would be bootstrapped",
                             queries=executed_queries)
        try:
            bootstrap_group_replication(cursor)
        except Exception as e:
            module.fail_json(msg="Failed to bootstrap Group Replication: %s" % to_native(e),
                             queries=executed_queries)
        module.exit_json(changed=True, msg="Group Replication bootstrapped", queries=executed_queries)

    elif mode == 'switch_to_single_primary':
        if module.check_mode:
            module.exit_json(changed=True, msg="Would switch to single-primary mode",
                             queries=executed_queries)
        try:
            switch_to_single_primary(cursor, primary_uuid)
        except Exception as e:
            module.fail_json(msg="Failed to switch to single-primary mode: %s" % to_native(e),
                             queries=executed_queries)
        module.exit_json(changed=True, msg="Switched to single-primary mode", queries=executed_queries)

    elif mode == 'switch_to_multi_primary':
        if module.check_mode:
            module.exit_json(changed=True, msg="Would switch to multi-primary mode",
                             queries=executed_queries)
        try:
            switch_to_multi_primary(cursor)
        except Exception as e:
            module.fail_json(msg="Failed to switch to multi-primary mode: %s" % to_native(e),
                             queries=executed_queries)
        module.exit_json(changed=True, msg="Switched to multi-primary mode", queries=executed_queries)

    warnings.simplefilter("ignore")


if __name__ == '__main__':
    main()
