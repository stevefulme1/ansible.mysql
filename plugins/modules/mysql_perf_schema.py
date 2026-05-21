#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible MySQL collection contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_perf_schema

short_description: Configure MySQL Performance Schema instruments and consumers

description:
  - Enable or disable Performance Schema instruments and consumers at runtime.
  - Uses C(UPDATE performance_schema.setup_instruments) and
    C(UPDATE performance_schema.setup_consumers).
  - Requires the C(UPDATE) privilege on C(performance_schema).

version_added: "5.1.0"

author:
  - Ansible MySQL collection contributors (@ansible-collections)

options:
  instruments:
    description:
      - List of instrument configuration dicts.
      - Each dict must contain O(instruments[].name_pattern) (a SQL C(LIKE) pattern)
        and O(instruments[].enabled) (C(true) or C(false)).
    type: list
    elements: dict
    suboptions:
      name_pattern:
        description: SQL C(LIKE) pattern matching instrument names.
        type: str
        required: true
      enabled:
        description: Whether matching instruments should be enabled.
        type: bool
        required: true
  consumers:
    description:
      - List of consumer configuration dicts.
      - Each dict must contain O(consumers[].name) (exact consumer name)
        and O(consumers[].enabled) (C(true) or C(false)).
    type: list
    elements: dict
    suboptions:
      name:
        description: Exact consumer name.
        type: str
        required: true
      enabled:
        description: Whether the consumer should be enabled.
        type: bool
        required: true

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
  - ansible.mysql.mysql

notes:
  - Performance Schema changes take effect immediately but do not persist across server restarts.
  - Compatible with MySQL 5.7+ and MySQL 8.0+.
'''

EXAMPLES = r'''
- name: Enable all wait instruments
  ansible.mysql.mysql_perf_schema:
    instruments:
      - name_pattern: "wait/%"
        enabled: true

- name: Disable statement history consumers
  ansible.mysql.mysql_perf_schema:
    consumers:
      - name: events_statements_history
        enabled: false
      - name: events_statements_history_long
        enabled: false

- name: Enable specific instruments and consumers together
  ansible.mysql.mysql_perf_schema:
    instruments:
      - name_pattern: "stage/%"
        enabled: true
    consumers:
      - name: events_stages_current
        enabled: true
      - name: events_stages_history
        enabled: true
'''

RETURN = r'''
queries:
  description: List of executed queries which modified state.
  returned: changed
  type: list
  sample: ["UPDATE performance_schema.setup_instruments SET ENABLED = 'YES' WHERE NAME LIKE 'wait/%'"]
instruments_changed:
  description: Number of instrument rows updated.
  returned: always
  type: int
  sample: 42
consumers_changed:
  description: Number of consumer rows updated.
  returned: always
  type: int
  sample: 2
'''

import warnings

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect, mysql_driver, mysql_driver_fail_msg, mysql_common_argument_spec,
)
from ansible.module_utils.common.text.converters import to_native


def get_instrument_state(cursor, name_pattern):
    """Return dict of {name: enabled} for instruments matching pattern."""
    cursor.execute(
        "SELECT NAME, ENABLED FROM performance_schema.setup_instruments WHERE NAME LIKE %s",
        (name_pattern,),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def get_consumer_state(cursor, name):
    """Return current ENABLED value for a consumer, or None."""
    cursor.execute(
        "SELECT ENABLED FROM performance_schema.setup_consumers WHERE NAME = %s",
        (name,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        instruments=dict(
            type='list', elements='dict', default=None,
            options=dict(
                name_pattern=dict(type='str', required=True),
                enabled=dict(type='bool', required=True),
            ),
        ),
        consumers=dict(
            type='list', elements='dict', default=None,
            options=dict(
                name=dict(type='str', required=True),
                enabled=dict(type='bool', required=True),
            ),
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[['instruments', 'consumers']],
    )

    instruments = module.params['instruments'] or []
    consumers = module.params['consumers'] or []

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
            'performance_schema',
            connect_timeout=module.params['connect_timeout'],
            check_hostname=module.params['check_hostname'],
        )
    except Exception as e:
        module.fail_json(msg="unable to connect to database: %s" % to_native(e))

    changed = False
    queries = []
    instruments_changed = 0
    consumers_changed = 0

    # Process instruments
    for item in instruments:
        pattern = item['name_pattern']
        desired = 'YES' if item['enabled'] else 'NO'
        current_state = get_instrument_state(cursor, pattern)

        if not current_state:
            module.warn("No instruments matched pattern '%s'" % pattern)
            continue

        needs_change = any(v != desired for v in current_state.values())
        if needs_change:
            changed = True
            query = ("UPDATE performance_schema.setup_instruments "
                     "SET ENABLED = %s WHERE NAME LIKE %s AND ENABLED != %s")
            if not module.check_mode:
                cursor.execute(query, (desired, pattern, desired))
                instruments_changed += cursor.rowcount
            else:
                instruments_changed += sum(1 for v in current_state.values() if v != desired)
            queries.append("UPDATE performance_schema.setup_instruments "
                           "SET ENABLED = '%s' WHERE NAME LIKE '%s'" % (desired, pattern))

    # Process consumers
    for item in consumers:
        name = item['name']
        desired = 'YES' if item['enabled'] else 'NO'
        current = get_consumer_state(cursor, name)

        if current is None:
            module.fail_json(msg="Consumer '%s' not found in performance_schema.setup_consumers" % name)

        if current != desired:
            changed = True
            query = ("UPDATE performance_schema.setup_consumers "
                     "SET ENABLED = %s WHERE NAME = %s")
            if not module.check_mode:
                cursor.execute(query, (desired, name))
                consumers_changed += cursor.rowcount
            else:
                consumers_changed += 1
            queries.append("UPDATE performance_schema.setup_consumers "
                           "SET ENABLED = '%s' WHERE NAME = '%s'" % (desired, name))

    module.exit_json(
        changed=changed,
        queries=queries,
        instruments_changed=instruments_changed,
        consumers_changed=consumers_changed,
    )


if __name__ == '__main__':
    main()
