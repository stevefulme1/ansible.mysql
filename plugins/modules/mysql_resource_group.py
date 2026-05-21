#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible MySQL collection contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_resource_group

short_description: Manage MySQL resource groups

description:
  - Create, alter, or drop MySQL resource groups.
  - Resource groups allow assigning threads to CPU and priority configurations.
  - Requires MySQL 8.0+ (resource groups are not available in MariaDB or MySQL 5.x).

version_added: "5.1.0"

author:
  - Ansible MySQL collection contributors (@ansible-collections)

options:
  name:
    description:
      - Name of the resource group.
    type: str
    required: true
  state:
    description:
      - Whether the resource group should exist.
    type: str
    choices: ['present', 'absent']
    default: present
  type:
    description:
      - Resource group type.
      - Required when O(state=present).
    type: str
    choices: ['USER', 'SYSTEM']
  vcpu:
    description:
      - VCPU affinity specification, e.g. V("0-3") or V("0,2,4-7").
    type: str
  thread_priority:
    description:
      - Thread priority. Range -20 to 19 for C(SYSTEM) groups, 0 to 19 for C(USER) groups.
    type: int
  enabled:
    description:
      - Whether the resource group is enabled.
    type: bool
    default: true

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
  - ansible.mysql.mysql

notes:
  - Requires MySQL 8.0.3 or later.
  - Not compatible with MariaDB.
  - Requires C(RESOURCE_GROUP_ADMIN) privilege.
'''

EXAMPLES = r'''
- name: Create a USER resource group for CPUs 0-3
  ansible.mysql.mysql_resource_group:
    name: batch_workers
    type: USER
    vcpu: "0-3"
    thread_priority: 10

- name: Create a SYSTEM resource group
  ansible.mysql.mysql_resource_group:
    name: system_critical
    type: SYSTEM
    vcpu: "0-1"
    thread_priority: -10

- name: Disable a resource group
  ansible.mysql.mysql_resource_group:
    name: batch_workers
    enabled: false

- name: Remove a resource group
  ansible.mysql.mysql_resource_group:
    name: batch_workers
    state: absent
'''

RETURN = r'''
queries:
  description: List of executed queries which modified state.
  returned: changed
  type: list
  sample: ["CREATE RESOURCE GROUP `batch_workers` TYPE = USER VCPU = 0-3 THREAD_PRIORITY = 10"]
'''

import warnings

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.database import mysql_quote_identifier
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect, mysql_driver, mysql_driver_fail_msg, mysql_common_argument_spec,
)
from ansible.module_utils.common.text.converters import to_native


def get_resource_group(cursor, name):
    """Return resource group info dict or None."""
    cursor.execute(
        "SELECT RESOURCE_GROUP_NAME, RESOURCE_GROUP_TYPE, "
        "RESOURCE_GROUP_ENABLED, VCPU_IDS, THREAD_PRIORITY "
        "FROM information_schema.RESOURCE_GROUPS "
        "WHERE RESOURCE_GROUP_NAME = %s",
        (name,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        'name': row[0],
        'type': row[1],
        'enabled': bool(row[2]),
        'vcpu': row[3],
        'thread_priority': row[4],
    }


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        type=dict(type='str', choices=['USER', 'SYSTEM']),
        vcpu=dict(type='str'),
        thread_priority=dict(type='int'),
        enabled=dict(type='bool', default=True),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ('state', 'present', ['type']),
        ],
    )

    name = module.params['name']
    state = module.params['state']
    rg_type = module.params['type']
    vcpu = module.params['vcpu']
    thread_priority = module.params['thread_priority']
    enabled = module.params['enabled']

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

    current = get_resource_group(cursor, name)
    changed = False
    queries = []

    if state == 'absent':
        if current is not None:
            changed = True
            query = "DROP RESOURCE GROUP %s FORCE" % mysql_quote_identifier(name, 'column')
            queries.append(query)
            if not module.check_mode:
                cursor.execute(query)
    else:
        # state == 'present'
        if current is None:
            # CREATE
            changed = True
            parts = ["CREATE RESOURCE GROUP %s" % mysql_quote_identifier(name, 'column')]
            parts.append("TYPE = %s" % rg_type)
            if vcpu is not None:
                parts.append("VCPU = %s" % vcpu)
            if thread_priority is not None:
                parts.append("THREAD_PRIORITY = %d" % thread_priority)
            if not enabled:
                parts.append("DISABLE")
            query = ' '.join(parts)
            queries.append(query)
            if not module.check_mode:
                cursor.execute(query)
        else:
            # ALTER if needed
            alter_parts = []
            if vcpu is not None and current['vcpu'] != vcpu:
                alter_parts.append("VCPU = %s" % vcpu)
            if thread_priority is not None and current['thread_priority'] != thread_priority:
                alter_parts.append("THREAD_PRIORITY = %d" % thread_priority)
            if current['enabled'] != enabled:
                alter_parts.append("ENABLE" if enabled else "DISABLE")

            if alter_parts:
                changed = True
                query = "ALTER RESOURCE GROUP %s %s" % (
                    mysql_quote_identifier(name, 'column'),
                    ' '.join(alter_parts),
                )
                queries.append(query)
                if not module.check_mode:
                    cursor.execute(query)

    module.exit_json(changed=changed, queries=queries)


if __name__ == '__main__':
    main()
