#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible MySQL collection contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_resource_group_info

short_description: Gather information about MySQL resource groups

description:
  - Returns a list of resource groups from C(information_schema.RESOURCE_GROUPS).
  - Requires MySQL 8.0+.

version_added: "5.1.0"

author:
  - Ansible MySQL collection contributors (@ansible-collections)

options:
  name:
    description:
      - Filter to a specific resource group by name.
      - If not specified, all resource groups are returned.
    type: str

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
'''

EXAMPLES = r'''
- name: Get all resource groups
  ansible.mysql.mysql_resource_group_info:
  register: rg_info

- name: Get a specific resource group
  ansible.mysql.mysql_resource_group_info:
    name: batch_workers
  register: rg_info

- name: Display resource groups
  ansible.builtin.debug:
    var: rg_info.resource_groups
'''

RETURN = r'''
resource_groups:
  description: List of resource group information dicts.
  returned: always
  type: list
  elements: dict
  contains:
    name:
      description: Resource group name.
      type: str
    type:
      description: Resource group type (USER or SYSTEM).
      type: str
    enabled:
      description: Whether the resource group is enabled.
      type: bool
    vcpu:
      description: VCPU affinity specification.
      type: str
    thread_priority:
      description: Thread priority value.
      type: int
  sample:
    - name: batch_workers
      type: USER
      enabled: true
      vcpu: "0-3"
      thread_priority: 10
'''

import warnings

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect, mysql_driver, mysql_driver_fail_msg, mysql_common_argument_spec,
)
from ansible.module_utils.common.text.converters import to_native


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        name=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params['name']

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

    query = ("SELECT RESOURCE_GROUP_NAME, RESOURCE_GROUP_TYPE, "
             "RESOURCE_GROUP_ENABLED, VCPU_IDS, THREAD_PRIORITY "
             "FROM information_schema.RESOURCE_GROUPS")
    params = ()

    if name is not None:
        query += " WHERE RESOURCE_GROUP_NAME = %s"
        params = (name,)

    try:
        cursor.execute(query, params)
    except Exception as e:
        module.fail_json(msg="Failed to query resource groups: %s" % to_native(e))

    resource_groups = []
    for row in cursor.fetchall():
        resource_groups.append({
            'name': row[0],
            'type': row[1],
            'enabled': bool(row[2]),
            'vcpu': row[3],
            'thread_priority': row[4],
        })

    module.exit_json(changed=False, resource_groups=resource_groups)


if __name__ == '__main__':
    main()
