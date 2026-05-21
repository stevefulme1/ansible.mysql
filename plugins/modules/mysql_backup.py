#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mysql_backup
short_description: Manage MySQL or MariaDB database backups using mysqldump or mysqlpump
description:
  - Create database backups using C(mysqldump) or C(mysqlpump).
  - Supports compression (gzip, zstd), optional encryption via openssl,
    parallel dumps (mysqlpump only), and automatic retention cleanup.
  - When I(state=present), creates a backup at the specified I(target) path.
  - When I(state=absent), removes an existing backup file at I(target).
version_added: '5.1.0'
options:
  databases:
    description:
      - List of database names to back up.
      - Use C(all) to back up all databases (equivalent to C(--all-databases)).
    type: list
    elements: str
    required: true
  tables:
    description:
      - List of tables to back up (only valid with a single database).
      - If omitted, all tables in the specified databases are backed up.
    type: list
    elements: str
    default: []
  target:
    description:
      - Destination file path for the backup on the remote host.
      - Required when I(state=present).
    type: path
  compression:
    description:
      - Compression method to apply to the backup output.
      - C(none) writes a plain SQL file.
      - C(gzip) pipes through C(gzip).
      - C(zstd) pipes through C(zstd).
    type: str
    choices: ['none', 'gzip', 'zstd']
    default: none
  encryption_key:
    description:
      - When set, the backup is encrypted using C(openssl enc -aes-256-cbc -pbkdf2).
      - The value is the passphrase used for encryption.
      - Decryption command will be included in the module return value.
    type: str
  parallel:
    description:
      - Number of parallel threads for C(mysqlpump).
      - When set to a value greater than 1, C(mysqlpump) is used instead of C(mysqldump).
      - Requires MySQL 5.7.8+ (mysqlpump availability).
    type: int
    default: 1
  routines:
    description:
      - Include stored routines (procedures and functions) in the backup.
    type: bool
    default: true
  triggers:
    description:
      - Include triggers in the backup.
    type: bool
    default: true
  single_transaction:
    description:
      - Execute the dump in a single transaction for InnoDB tables.
      - Ensures a consistent backup without locking tables.
    type: bool
    default: true
  retention_days:
    description:
      - Number of days to retain backup files in the same directory as I(target).
      - Files matching the backup filename pattern older than this value are removed.
      - Set to C(0) to disable retention cleanup.
    type: int
    default: 0
  state:
    description:
      - C(present) creates a backup.
      - C(absent) removes the backup file at I(target).
    type: str
    choices: ['present', 'absent']
    default: present
  dump_extra_args:
    description:
      - Additional arguments to pass directly to the dump command.
    type: str
  unsafe_login_password:
    description:
      - If C(true), the module will not shell-escape the I(login_password) value.
      - Use only when special characters cause C(Access denied) errors.
    type: bool
    default: false
  restrict_config_file:
    description:
      - Read only the passed I(config_file) instead of the usual option files.
    type: bool
    default: false
  pipefail:
    description:
      - Use C(bash -o pipefail) to catch errors when piping through compression.
    type: bool
    default: true
author:
  - Ansible community (@ansible-collections)
requirements:
  - mysqldump or mysqlpump (command line binary)
  - gzip (when compression=gzip)
  - zstd (when compression=zstd)
  - openssl (when encryption_key is set)
notes:
  - Compatible with MariaDB or MySQL.
  - The C(parallel) option requires C(mysqlpump), available in MySQL 5.7.8+.
  - MariaDB does not ship C(mysqlpump); use C(parallel=1) with MariaDB.
attributes:
  check_mode:
    support: full
  idempotent:
    support: partial
    details:
      - Backup creation is not idempotent; a new file is always written.
      - Backup removal is idempotent.
extends_documentation_fragment:
  - ansible.mysql.mysql
seealso:
  - module: ansible.mysql.mysql_db
  - name: mysqldump reference
    description: Complete reference of the mysqldump utility.
    link: https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html
  - name: mysqlpump reference
    description: Complete reference of the mysqlpump utility.
    link: https://dev.mysql.com/doc/refman/8.0/en/mysqlpump.html
'''

EXAMPLES = r'''
- name: Back up a single database with gzip compression
  ansible.mysql.mysql_backup:
    databases:
      - myapp
    target: /backups/myapp.sql.gz
    compression: gzip
    login_unix_socket: /run/mysqld/mysqld.sock

- name: Back up all databases with zstd compression and encryption
  ansible.mysql.mysql_backup:
    databases:
      - all
    target: /backups/full_backup.sql.zst.enc
    compression: zstd
    encryption_key: "{{ vault_backup_passphrase }}"

- name: Parallel backup using mysqlpump
  ansible.mysql.mysql_backup:
    databases:
      - db1
      - db2
    target: /backups/multi.sql
    parallel: 4

- name: Back up specific tables only
  ansible.mysql.mysql_backup:
    databases:
      - myapp
    tables:
      - users
      - orders
    target: /backups/myapp_tables.sql.gz
    compression: gzip

- name: Back up with 7-day retention cleanup
  ansible.mysql.mysql_backup:
    databases:
      - myapp
    target: /backups/myapp_daily.sql.gz
    compression: gzip
    retention_days: 7

- name: Remove a backup file
  ansible.mysql.mysql_backup:
    databases:
      - myapp
    target: /backups/old_backup.sql.gz
    state: absent
'''

RETURN = r'''
target:
  description: Path to the backup file on the remote host.
  returned: when state=present
  type: str
  sample: "/backups/myapp.sql.gz"
size:
  description: Size of the backup file in bytes.
  returned: when state=present and backup was created
  type: int
  sample: 1048576
databases:
  description: List of databases included in the backup.
  returned: always
  type: list
  sample: ["myapp"]
executed_commands:
  description: List of commands executed during the backup.
  returned: when state=present
  type: list
  sample: ["mysqldump --defaults-extra-file=... --single-transaction --routines --triggers myapp | gzip > /backups/myapp.sql.gz"]
decryption_command:
  description: Command to decrypt the backup (when encryption_key was used).
  returned: when encryption_key is set
  type: str
  sample: "openssl enc -d -aes-256-cbc -pbkdf2 -in backup.sql.gz.enc -out backup.sql.gz -pass pass:***"
retention_removed:
  description: List of old backup files removed by retention policy.
  returned: when retention_days > 0
  type: list
  sample: ["/backups/myapp_daily.sql.gz.20230101"]
'''

import glob
import os
import shlex
import time

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
    mysql_common_argument_spec,
    get_server_implementation,
    get_server_version,
)
from ansible_collections.ansible.mysql.plugins.module_utils.version import LooseVersion
from ansible.module_utils.common.text.converters import to_native


def build_dump_command(module, params, server_implementation, server_version):
    """Build the mysqldump/mysqlpump command line."""
    executed_commands = []
    use_pump = params['parallel'] > 1

    if use_pump:
        cmd_str = 'mysqlpump'
    elif server_implementation == 'mariadb' and LooseVersion(server_version) >= LooseVersion("10.4.6"):
        cmd_str = 'mariadb-dump'
    else:
        cmd_str = 'mysqldump'

    try:
        cmd = [module.get_bin_path(cmd_str, True)]
    except Exception as e:
        module.fail_json(msg="Cannot find %s binary: %s" % (cmd_str, to_native(e)))

    # Config file must be first
    config_file = params.get('config_file')
    if config_file and os.path.exists(config_file):
        if params['restrict_config_file']:
            cmd.append("--defaults-file=%s" % shlex.quote(config_file))
        else:
            cmd.append("--defaults-extra-file=%s" % shlex.quote(config_file))

    if params['login_user'] is not None:
        cmd.append("--user=%s" % shlex.quote(params['login_user']))
    if params['login_password'] is not None:
        if params['unsafe_login_password']:
            cmd.append("--password=%s" % params['login_password'])
        else:
            cmd.append("--password=%s" % shlex.quote(params['login_password']))

    # SSL
    if params['client_cert'] is not None:
        cmd.append("--ssl-cert=%s" % shlex.quote(params['client_cert']))
    if params['client_key'] is not None:
        cmd.append("--ssl-key=%s" % shlex.quote(params['client_key']))
    if params['ca_cert'] is not None:
        cmd.append("--ssl-ca=%s" % shlex.quote(params['ca_cert']))

    # Connection
    if params['login_unix_socket'] is not None:
        cmd.append("--socket=%s" % shlex.quote(params['login_unix_socket']))
    else:
        cmd.append("--host=%s" % shlex.quote(params['login_host']))
        cmd.append("--port=%i" % params['login_port'])

    # Dump options
    if params['single_transaction']:
        cmd.append("--single-transaction")
    if params['routines']:
        cmd.append("--routines")
    if params['triggers']:
        cmd.append("--triggers")
    if use_pump:
        cmd.append("--default-parallelism=%d" % params['parallel'])

    # Databases
    all_databases = params['databases'] == ['all']
    if all_databases:
        cmd.append("--all-databases")
    elif len(params['databases']) > 1:
        cmd.append("--databases %s" % ' '.join(shlex.quote(d) for d in params['databases']))
    else:
        cmd.append(shlex.quote(params['databases'][0]))
        if params['tables']:
            for table in params['tables']:
                cmd.append(shlex.quote(table))

    if params['dump_extra_args']:
        cmd.append(params['dump_extra_args'])

    # Build pipeline
    cmd_line = ' '.join(cmd)
    pipeline = [cmd_line]

    # Compression
    if params['compression'] == 'gzip':
        gzip_path = module.get_bin_path('gzip', True)
        pipeline.append(gzip_path)
    elif params['compression'] == 'zstd':
        zstd_path = module.get_bin_path('zstd', True)
        pipeline.append(zstd_path)

    # Encryption
    if params['encryption_key']:
        openssl_path = module.get_bin_path('openssl', True)
        pipeline.append("%s enc -aes-256-cbc -pbkdf2 -pass pass:%s" % (
            openssl_path, shlex.quote(params['encryption_key'])))

    full_cmd = ' | '.join(pipeline) + ' > %s' % shlex.quote(params['target'])
    if params['pipefail'] and (len(pipeline) > 1):
        full_cmd = 'set -o pipefail && ' + full_cmd

    executed_commands.append(full_cmd)
    return full_cmd, executed_commands, params['pipefail'] and len(pipeline) > 1


def cleanup_old_backups(target, retention_days):
    """Remove backup files older than retention_days in the same directory."""
    if retention_days <= 0:
        return []

    target_dir = os.path.dirname(target) or '.'
    target_base = os.path.basename(target)
    cutoff = time.time() - (retention_days * 86400)
    removed = []

    # Match files with same base name pattern
    pattern = os.path.join(target_dir, target_base + '*')
    for filepath in glob.glob(pattern):
        if filepath == target:
            continue
        try:
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
                removed.append(filepath)
        except OSError:
            pass

    return removed


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        databases=dict(type='list', elements='str', required=True),
        tables=dict(type='list', elements='str', default=[]),
        target=dict(type='path'),
        compression=dict(type='str', choices=['none', 'gzip', 'zstd'], default='none'),
        encryption_key=dict(type='str', no_log=True),
        parallel=dict(type='int', default=1),
        routines=dict(type='bool', default=True),
        triggers=dict(type='bool', default=True),
        single_transaction=dict(type='bool', default=True),
        retention_days=dict(type='int', default=0),
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        dump_extra_args=dict(type='str'),
        unsafe_login_password=dict(type='bool', default=False, no_log=True),
        restrict_config_file=dict(type='bool', default=False),
        pipefail=dict(type='bool', default=True),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ('state', 'present', ['target']),
            ('state', 'absent', ['target']),
        ],
    )

    state = module.params['state']
    target = module.params['target']
    databases = [d.strip() for d in module.params['databases']]
    module.params['databases'] = databases

    if module.params['tables'] and len(databases) != 1:
        module.fail_json(msg="tables can only be specified with a single database")
    if module.params['tables'] and databases == ['all']:
        module.fail_json(msg="tables cannot be used with databases=['all']")

    result = dict(
        changed=False,
        databases=databases,
    )

    if state == 'absent':
        if os.path.exists(target):
            if module.check_mode:
                result['changed'] = True
                module.exit_json(**result)
            os.remove(target)
            result['changed'] = True
        module.exit_json(**result)

    # state == 'present'
    if module.check_mode:
        result['changed'] = True
        result['target'] = target
        module.exit_json(**result)

    # Connect to get server info
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

    server_implementation = get_server_implementation(cursor)
    server_version = get_server_version(cursor)

    if module.params['parallel'] > 1 and server_implementation == 'mariadb':
        module.fail_json(msg="mysqlpump (parallel > 1) is not available on MariaDB")

    # Build and run the dump command
    full_cmd, executed_commands, use_bash = build_dump_command(
        module, module.params, server_implementation, server_version)

    if use_bash:
        rc, stdout, stderr = module.run_command(full_cmd, use_unsafe_shell=True, executable='bash')
    else:
        rc, stdout, stderr = module.run_command(full_cmd, use_unsafe_shell=True)

    if rc != 0:
        module.fail_json(msg="Backup failed: %s" % stderr, executed_commands=executed_commands)

    result['changed'] = True
    result['target'] = target
    result['executed_commands'] = executed_commands

    if os.path.exists(target):
        result['size'] = os.path.getsize(target)

    if module.params['encryption_key']:
        result['decryption_command'] = (
            "openssl enc -d -aes-256-cbc -pbkdf2 -in %s -out <output_file> -pass pass:***" % target
        )

    # Retention cleanup
    if module.params['retention_days'] > 0:
        result['retention_removed'] = cleanup_old_backups(target, module.params['retention_days'])

    module.exit_json(**result)


if __name__ == '__main__':
    main()
