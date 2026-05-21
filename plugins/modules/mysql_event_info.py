#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible MySQL collection contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_event_info

short_description: Gather information about MySQL scheduled events

description:
  - Returns a list of scheduled events from C(information_schema.EVENTS).

version_added: "5.1.0"

author:
  - Ansible MySQL collection contributors (@ansible-collections)

options:
  schema:
    description:
      - Filter events to a specific database/schema.
      - If not specified, events from all schemas are returned.
    type: str
  name:
    description:
      - Filter to a specific event by name.
      - Requires O(schema) to be specified.
    type: str

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
  - ansible.mysql.mysql

notes:
  - Compatible with MySQL 5.7+, MySQL 8.0+, and MariaDB.
'''

EXAMPLES = r'''
- name: Get all events
  ansible.mysql.mysql_event_info:
  register: event_info

- name: Get events in a specific schema
  ansible.mysql.mysql_event_info:
    schema: mydb
  register: event_info

- name: Get a specific event
  ansible.mysql.mysql_event_info:
    schema: mydb
    name: refresh_stats
  register: event_info

- name: Display events
  ansible.builtin.debug:
    var: event_info.events
'''

RETURN = r'''
events:
  description: List of event information dicts.
  returned: always
  type: list
  elements: dict
  contains:
    name:
      description: Event name.
      type: str
    schema:
      description: Schema the event belongs to.
      type: str
    schedule_type:
      description: V(at) for one-time, V(every) for recurring.
      type: str
    schedule_value:
      description: Schedule expression.
      type: str
    body:
      description: SQL statement(s) the event executes.
      type: str
    enabled:
      description: Whether the event is enabled.
      type: bool
    comment:
      description: Event comment.
      type: str
  sample:
    - name: refresh_stats
      schema: mydb
      schedule_type: every
      schedule_value: "1 HOUR"
      body: "CALL mydb.refresh_statistics()"
      enabled: true
      comment: ""
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
        schema=dict(type='str'),
        name=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_by={
            'name': 'schema',
        },
    )

    schema = module.params['schema']
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

    query = ("SELECT EVENT_NAME, EVENT_SCHEMA, EVENT_TYPE, EXECUTE_AT, "
             "INTERVAL_VALUE, INTERVAL_FIELD, EVENT_DEFINITION, STATUS, "
             "EVENT_COMMENT "
             "FROM information_schema.EVENTS")
    conditions = []
    params = []

    if schema is not None:
        conditions.append("EVENT_SCHEMA = %s")
        params.append(schema)
    if name is not None:
        conditions.append("EVENT_NAME = %s")
        params.append(name)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    try:
        cursor.execute(query, tuple(params))
    except Exception as e:
        module.fail_json(msg="Failed to query events: %s" % to_native(e))

    events = []
    for row in cursor.fetchall():
        schedule_type = 'at' if row[2] == 'ONE TIME' else 'every'
        if schedule_type == 'at':
            schedule_value = str(row[3]) if row[3] else None
        else:
            schedule_value = '%s %s' % (row[4], row[5]) if row[4] else None

        events.append({
            'name': row[0],
            'schema': row[1],
            'schedule_type': schedule_type,
            'schedule_value': schedule_value,
            'body': row[6],
            'enabled': row[7] == 'ENABLED',
            'comment': row[8] or '',
        })

    module.exit_json(changed=False, events=events)


if __name__ == '__main__':
    main()
