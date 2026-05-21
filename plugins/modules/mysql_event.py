#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible MySQL collection contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_event

short_description: Manage MySQL scheduled events

description:
  - Create, alter, or drop MySQL scheduled events (C(CREATE EVENT), C(ALTER EVENT), C(DROP EVENT)).
  - Requires the C(EVENT) privilege on the target schema.
  - The MySQL event scheduler must be enabled (C(SET GLOBAL event_scheduler = ON)) for events to execute.

version_added: "5.1.0"

author:
  - Ansible MySQL collection contributors (@ansible-collections)

options:
  name:
    description:
      - Name of the event.
    type: str
    required: true
  schema:
    description:
      - Database/schema in which the event resides.
    type: str
    required: true
  state:
    description:
      - Whether the event should exist.
    type: str
    choices: ['present', 'absent']
    default: present
  schedule_type:
    description:
      - V(at) for a one-time event, V(every) for a recurring event.
      - Required when O(state=present) and the event does not yet exist.
    type: str
    choices: ['at', 'every']
  schedule_value:
    description:
      - Schedule expression.
      - For O(schedule_type=at), a timestamp string like V("2025-12-31 23:59:59").
      - For O(schedule_type=every), an interval like V("1 HOUR") or V("30 MINUTE").
      - Required when O(state=present) and the event does not yet exist.
    type: str
  body:
    description:
      - SQL statement(s) the event executes.
      - Required when O(state=present) and the event does not yet exist.
    type: str
  enabled:
    description:
      - Whether the event is enabled (C(ENABLE)) or disabled (C(DISABLE)).
    type: bool
    default: true
  comment:
    description:
      - Optional comment for the event.
    type: str
    default: ''

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
  - ansible.mysql.mysql

notes:
  - Compatible with MySQL 5.7+ and MySQL 8.0+.
  - MariaDB also supports events with the same syntax.
  - The event scheduler must be enabled globally for events to fire.
'''

EXAMPLES = r'''
- name: Create a one-time event
  ansible.mysql.mysql_event:
    name: cleanup_old_data
    schema: mydb
    schedule_type: at
    schedule_value: "2025-12-31 23:59:59"
    body: "DELETE FROM mydb.logs WHERE created < DATE_SUB(NOW(), INTERVAL 90 DAY)"
    comment: "Year-end log cleanup"

- name: Create a recurring event
  ansible.mysql.mysql_event:
    name: refresh_stats
    schema: mydb
    schedule_type: every
    schedule_value: "1 HOUR"
    body: "CALL mydb.refresh_statistics()"

- name: Disable an existing event
  ansible.mysql.mysql_event:
    name: refresh_stats
    schema: mydb
    enabled: false

- name: Remove an event
  ansible.mysql.mysql_event:
    name: refresh_stats
    schema: mydb
    state: absent
'''

RETURN = r'''
queries:
  description: List of executed queries which modified state.
  returned: changed
  type: list
  sample: ["CREATE EVENT `mydb`.`refresh_stats` ON SCHEDULE EVERY 1 HOUR ENABLE DO CALL mydb.refresh_statistics()"]
'''

import warnings

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.database import mysql_quote_identifier
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect, mysql_driver, mysql_driver_fail_msg, mysql_common_argument_spec,
)
from ansible.module_utils.common.text.converters import to_native


def get_event(cursor, schema, name):
    """Return event info dict or None."""
    cursor.execute(
        "SELECT EVENT_NAME, EVENT_SCHEMA, EVENT_TYPE, EXECUTE_AT, "
        "INTERVAL_VALUE, INTERVAL_FIELD, EVENT_DEFINITION, STATUS, "
        "EVENT_COMMENT "
        "FROM information_schema.EVENTS "
        "WHERE EVENT_SCHEMA = %s AND EVENT_NAME = %s",
        (schema, name),
    )
    row = cursor.fetchone()
    if row is None:
        return None

    schedule_type = 'at' if row[2] == 'ONE TIME' else 'every'
    if schedule_type == 'at':
        schedule_value = str(row[3]) if row[3] else None
    else:
        schedule_value = '%s %s' % (row[4], row[5]) if row[4] else None

    return {
        'name': row[0],
        'schema': row[1],
        'schedule_type': schedule_type,
        'schedule_value': schedule_value,
        'body': row[6],
        'enabled': row[7] == 'ENABLED',
        'comment': row[8] or '',
    }


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        schema=dict(type='str', required=True),
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        schedule_type=dict(type='str', choices=['at', 'every']),
        schedule_value=dict(type='str'),
        body=dict(type='str'),
        enabled=dict(type='bool', default=True),
        comment=dict(type='str', default=''),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params['name']
    schema = module.params['schema']
    state = module.params['state']
    schedule_type = module.params['schedule_type']
    schedule_value = module.params['schedule_value']
    body = module.params['body']
    enabled = module.params['enabled']
    comment = module.params['comment']

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
            schema,
            connect_timeout=module.params['connect_timeout'],
            check_hostname=module.params['check_hostname'],
        )
    except Exception as e:
        module.fail_json(msg="unable to connect to database: %s" % to_native(e))

    current = get_event(cursor, schema, name)
    changed = False
    queries = []

    qualified_name = "%s.%s" % (
        mysql_quote_identifier(schema, 'database'),
        mysql_quote_identifier(name, 'column'),
    )

    if state == 'absent':
        if current is not None:
            changed = True
            query = "DROP EVENT IF EXISTS %s" % qualified_name
            queries.append(query)
            if not module.check_mode:
                cursor.execute(query)
    else:
        # state == 'present'
        status_clause = "ENABLE" if enabled else "DISABLE"

        if current is None:
            # CREATE
            if schedule_type is None or schedule_value is None or body is None:
                module.fail_json(msg="schedule_type, schedule_value, and body are required to create a new event")

            changed = True
            if schedule_type == 'at':
                schedule_clause = "AT '%s'" % schedule_value
            else:
                schedule_clause = "EVERY %s" % schedule_value

            comment_clause = "COMMENT '%s'" % comment.replace("'", "''") if comment else ""
            query = "CREATE EVENT %s ON SCHEDULE %s %s %s DO %s" % (
                qualified_name,
                schedule_clause,
                status_clause,
                comment_clause,
                body,
            )
            queries.append(query)
            if not module.check_mode:
                cursor.execute(query)
        else:
            # ALTER if needed
            alter_parts = []

            if schedule_type is not None and schedule_value is not None:
                if schedule_type == 'at':
                    new_schedule = "AT '%s'" % schedule_value
                else:
                    new_schedule = "EVERY %s" % schedule_value
                # Compare normalized
                if (current['schedule_type'] != schedule_type
                        or current.get('schedule_value', '').upper() != schedule_value.upper()):
                    alter_parts.append("ON SCHEDULE %s" % new_schedule)

            if body is not None and current['body'] != body:
                alter_parts.append("DO %s" % body)

            if current['enabled'] != enabled:
                alter_parts.append(status_clause)

            if comment is not None and current['comment'] != comment:
                alter_parts.append("COMMENT '%s'" % comment.replace("'", "''"))

            if alter_parts:
                changed = True
                query = "ALTER EVENT %s %s" % (qualified_name, ' '.join(alter_parts))
                queries.append(query)
                if not module.check_mode:
                    cursor.execute(query)

    module.exit_json(changed=changed, queries=queries)


if __name__ == '__main__':
    main()
