# -*- coding: utf-8 -*-
from testcasebase import TestCaseBase
import time
import os
from libs.test_loader import load
import libs.utils as utils
from libs.logger import infoLogger
from libs.deco import multi_dimension
import libs.ddt as ddt


@ddt.ddt
class TestRecoverEndpoint(TestCaseBase):

    def confset_createtable_put(self, data_count):
        self.confset(self.ns_leader, 'auto_failover', 'true')
        self.confset(self.ns_leader, 'auto_recover_table', 'true')
        self.tname = 'tname{}'.format(time.time())
        metadata_path = '{}/metadata.txt'.format(self.testpath)
        m = utils.gen_table_metadata(
            '"{}"'.format(self.tname), '"kAbsoluteTime"', 144000, 8,
            ('table_partition', '"{}"'.format(self.leader), '"0-3"', 'true'),
            ('table_partition', '"{}"'.format(self.slave1), '"0-3"', 'false'),
            ('table_partition', '"{}"'.format(self.slave2), '"2-3"', 'false'),
            ('column_desc', '"k1"', '"string"', 'true'),
            ('column_desc', '"k2"', '"string"', 'false'),
            ('column_desc', '"k3"', '"string"', 'false'))
        utils.gen_table_metadata_file(m, metadata_path)
        rs = self.ns_create(self.ns_leader, metadata_path)
        self.assertIn('Create table ok', rs)
        table_info = self.showtable(self.ns_leader)
        self.tid = int(table_info.keys()[0][1])
        self.pid = 3
        self.put_large_datas(data_count, 7)


    def put_data(self, endpoint):
        rs = self.put(endpoint, self.tid, self.pid, "testkey0", self.now() + 1000, "testvalue0")
        self.assertIn("ok", rs)


    @staticmethod
    def get_steps_dict():
        return {
            0: 'time.sleep(10)',
            1: 'self.confset_createtable_put(1)',
            2: 'self.stop_client(self.leader)',
            3: 'self.disconnectzk(self.leader)',
            4: 'self.stop_client(self.slave1)',
            5: 'self.disconnectzk(self.slave1)',
            6: 'self.find_new_tb_leader(self.tname, self.tid, self.pid)',
            7: 'self.put_data(self.leader)',
            8: 'self.put_data(self.new_tb_leader)',
            9: 'self.confset(self.ns_leader, "auto_recover_table", "false")',
            10: 'self.makesnapshot(self.leader, self.tid, self.pid)',
            11: 'self.makesnapshot(self.slave1, self.tid, self.pid), self.makesnapshot(self.slave2, self.tid, self.pid)',
            12: 'self.makesnapshot(self.ns_leader, self.tname, self.pid, \'ns_client\')',
            13: 'self.start_client(self.leader)',
            14: 'self.start_client(self.slave1)',
            15: 'self.connectzk(self.leader)',
            16: 'self.connectzk(self.slave1)',
            17: 'self.assertEqual(self.get_op_by_opid(self.latest_opid), "kReAddReplicaOP")',
            18: 'self.assertEqual(self.get_op_by_opid(self.latest_opid), "kReAddReplicaNoSendOP")',
            19: 'self.assertEqual(self.get_op_by_opid(self.latest_opid), "kReAddReplicaWithDropOP")',
            20: 'self.assertEqual(self.get_op_by_opid(self.latest_opid), "kReAddReplicaSimplifyOP")',
            21: 'self.check_re_add_replica_op(self.latest_opid)',
            22: 'self.check_re_add_replica_no_send_op(self.latest_opid)',
            23: 'self.check_re_add_replica_with_drop_op(self.latest_opid)',
            24: 'self.check_re_add_replica_simplify_op(self.latest_opid)',
            25: 'self.recoverendpoint(self.ns_leader, self.leader)',
            26: 'self.confset(self.ns_leader, "auto_recover_table", "false")',
            27: 'self.confset(self.ns_leader, "auto_recover_table", "true")',
            28: 'self.stop_client(self.ns_leader)',
            29: 'self.start_client(self.ns_leader, "nameserver")',
            30: 'self.get_new_ns_leader()',
            31: 'self.get_table_status(self.leader)',
            32: 'self.makesnapshot(self.ns_leader, self.tname, self.pid, "ns_client")',
            33: 'self.get_latest_opid_by_tname_pid(self.tname, self.pid)',
            34: 'self.recoverendpoint(self.ns_leader, self.slave1)',
        }


    @ddt.data(
        (1, 26, 3, 0, 6, 15, 25, 0, 33, 20, 24, 27),  # 主节点断网后恢复，手动恢复后加为从节点
        (1, 26, 3, 0, 6, 8, 12, 15, 25, 0, 33, 19, 23, 27),
        (1, 26, 12, 2, 0, 6, 12, 13, 25, 0, 33, 18, 22, 27),
        (1, 26, 2, 0, 6, 13, 25, 0, 33, 17, 21, 27),
        (1, 26, 4, 0, 14, 34, 0, 33, 17, 27),  # 从节点挂掉后恢复，手动恢复后重新加为从节点
    )
    @ddt.unpack
    def test_recover_endpoint(self, *steps):
        """
        tablet故障恢复流程测试
        :param steps:
        :return:
        """
        self.get_new_ns_leader()
        steps_dict = self.get_steps_dict()
        for i in steps:
            infoLogger.info('*' * 10 + ' Executing step {}: {}'.format(i, steps_dict[i]))
            eval(steps_dict[i])
        rs = self.showtable(self.ns_leader)
        role_x = [v[0] for k, v in rs.items()]
        is_alive_x = [v[-1] for k, v in rs.items()]
        print self.showopstatus(self.ns_leader)
        self.assertEqual(role_x.count('leader'), 4)
        self.assertEqual(role_x.count('follower'), 6)
        self.assertEqual(is_alive_x.count('yes'), 10)
        self.assertEqual(self.get_table_status(self.leader, self.tid, self.pid)[0],
                         self.get_table_status(self.slave1, self.tid, self.pid)[0])
        self.assertEqual(self.get_table_status(self.leader, self.tid, self.pid)[0],
                         self.get_table_status(self.slave2, self.tid, self.pid)[0])


    def test_recoversnapshot_offline_master_failed(self):
        """
        主节点挂掉未启动，不可以手工recoversnapshot成功
        :return:
        """
        self.start_client(self.leader)
        metadata_path = '{}/metadata.txt'.format(self.testpath)
        name = 'tname{}'.format(time.time())
        m = utils.gen_table_metadata(
            '"{}"'.format(name), None, 144000, 2,
            ('table_partition', '"{}"'.format(self.leader), '"0-2"', 'true'),
            ('table_partition', '"{}"'.format(self.slave1), '"0-1"', 'false'),
            ('table_partition', '"{}"'.format(self.slave2), '"0-1"', 'false'),
            ('column_desc', '"k1"', '"string"', 'true'),
            ('column_desc', '"k2"', '"string"', 'false'),
            ('column_desc', '"k3"', '"string"', 'false')
        )
        utils.gen_table_metadata_file(m, metadata_path)
        rs0 = self.ns_create(self.ns_leader, metadata_path)
        self.assertIn('Create table ok', rs0)
        self.multidimension_vk = {'k1': ('string:index', 'testvalue0'),
                                  'k2': ('string', 'testvalue0'),
                                  'k3': ('string', 'testvalue0')}
        self.multidimension_scan_vk = {'k1': 'testvalue0'}

        self.confset(self.ns_leader, 'auto_failover', 'false')
        self.confset(self.ns_leader, 'auto_recover_table', 'false')

        self.stop_client(self.leader)
        time.sleep(10)
        rs = self.recoverendpoint(self.ns_leader, self.leader)
        self.assertIn('failed', rs)


    def test_recoversnapshot_offline_master_after_changeleader(self):
        """
        主节点挂掉，手动故障切换成功后启动，
        做了故障切换的分片，可以手工recovertable为follower
        无副本的分片，手工recovertablet为leader
        :return:
        """
        self.start_client(self.leader)
        metadata_path = '{}/metadata.txt'.format(self.testpath)
        name = 'tname{}'.format(time.time())
        m = utils.gen_table_metadata(
            '"{}"'.format(name), None, 144000, 2,
            ('table_partition', '"{}"'.format(self.leader), '"0-2"', 'true'),
            ('table_partition', '"{}"'.format(self.slave1), '"0-1"', 'false'),
            ('table_partition', '"{}"'.format(self.slave2), '"0-1"', 'false'),
            ('column_desc', '"k1"', '"string"', 'true'),
            ('column_desc', '"k2"', '"string"', 'false'),
            ('column_desc', '"k3"', '"string"', 'false')
        )
        utils.gen_table_metadata_file(m, metadata_path)
        rs0 = self.ns_create(self.ns_leader, metadata_path)
        self.assertIn('Create table ok', rs0)
        self.multidimension_vk = {'k1': ('string:index', 'testvalue0'),
                                  'k2': ('string', 'testvalue0'),
                                  'k3': ('string', 'testvalue0')}
        self.multidimension_scan_vk = {'k1': 'testvalue0'}

        rs1 = self.showtable(self.ns_leader)
        tid = rs1.keys()[0][1]

        self.confset(self.ns_leader, 'auto_failover', 'false')
        self.confset(self.ns_leader, 'auto_recover_table', 'false')

        self.stop_client(self.leader)
        time.sleep(10)
        self.changeleader(self.ns_leader, name, 0)
        self.changeleader(self.ns_leader, name, 1)
        self.start_client(self.leader)
        time.sleep(3)
        self.recoverendpoint(self.ns_leader, self.leader)
        time.sleep(10)

        rs5 = self.showtable(self.ns_leader)
        self.assertEqual(rs5[(name, tid, '0', self.leader)], ['follower', '2', '144000', 'yes'])
        self.assertEqual(rs5[(name, tid, '1', self.leader)], ['follower', '2', '144000', 'yes'])
        self.assertEqual(rs5[(name, tid, '2', self.leader)], ['leader', '2', '144000', 'yes'])


if __name__ == "__main__":
    load(TestRecoverEndpoint)