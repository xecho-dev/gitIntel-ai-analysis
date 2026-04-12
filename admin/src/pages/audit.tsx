import { useState } from 'react';
import { Table, Tag, Input, Card, Row, Col, Typography, Select, DatePicker, Space, Button, Statistic, Avatar } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  SearchOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

interface AuditLog {
  id: string;
  key: string;
  user: string;
  userAvatar: string;
  action: string;
  actionType: 'create' | 'read' | 'update' | 'delete';
  target: string;
  ip: string;
  timestamp: string;
  status: 'success' | 'failed' | 'pending';
  duration: string;
}

export default function Audit() {
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [logs] = useState<AuditLog[]>([
    { 
      key: '1', 
      id: '1',
      user: 'admin', 
      userAvatar: 'A',
      action: '创建分析', 
      actionType: 'create',
      target: 'facebook/react', 
      ip: '192.168.1.100',
      timestamp: '2026-04-12 10:30:25', 
      status: 'success',
      duration: '2.3s',
    },
    { 
      key: '2', 
      id: '2',
      user: 'user1', 
      userAvatar: 'U',
      action: '查看结果', 
      actionType: 'read',
      target: 'microsoft/vscode', 
      ip: '192.168.1.101',
      timestamp: '2026-04-12 10:25:10', 
      status: 'success',
      duration: '0.5s',
    },
    { 
      key: '3', 
      id: '3',
      user: 'admin', 
      userAvatar: 'A',
      action: '删除用户', 
      actionType: 'delete',
      target: 'user3', 
      ip: '192.168.1.100',
      timestamp: '2026-04-12 09:15:33', 
      status: 'failed',
      duration: '0.2s',
    },
    { 
      key: '4', 
      id: '4',
      user: 'user2', 
      userAvatar: 'U',
      action: '更新配置', 
      actionType: 'update',
      target: '系统设置', 
      ip: '192.168.1.102',
      timestamp: '2026-04-12 08:45:00', 
      status: 'pending',
      duration: '-',
    },
    { 
      key: '5', 
      id: '5',
      user: 'admin', 
      userAvatar: 'A',
      action: '导出报告', 
      actionType: 'read',
      target: '月报-2026-03', 
      ip: '192.168.1.100',
      timestamp: '2026-04-11 16:20:15', 
      status: 'success',
      duration: '5.8s',
    },
  ]);

  const statusMap = {
    success: { color: 'success', text: '成功', icon: <CheckCircleOutlined /> },
    failed: { color: 'error', text: '失败', icon: <CloseCircleOutlined /> },
    pending: { color: 'processing', text: '进行中', icon: <ClockCircleOutlined /> },
  };

  const actionTypeMap = {
    create: { color: 'cyan', text: '创建' },
    read: { color: 'blue', text: '查看' },
    update: { color: 'orange', text: '更新' },
    delete: { color: 'red', text: '删除' },
  };

  const columns: ColumnsType<AuditLog> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
    },
    {
      title: '用户',
      key: 'user',
      render: (_, record) => (
        <Space>
          <Avatar size="small" style={{ background: '#1677ff' }}>{record.userAvatar}</Avatar>
          <Text>{record.user}</Text>
        </Space>
      ),
    },
    {
      title: '操作类型',
      dataIndex: 'actionType',
      key: 'actionType',
      render: (type: keyof typeof actionTypeMap) => (
        <Tag color={actionTypeMap[type].color}>{actionTypeMap[type].text}</Tag>
      ),
    },
    {
      title: '操作描述',
      dataIndex: 'action',
      key: 'action',
    },
    {
      title: '操作对象',
      dataIndex: 'target',
      key: 'target',
      render: (target: string) => <Text code>{target}</Text>,
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      key: 'ip',
    },
    {
      title: '耗时',
      dataIndex: 'duration',
      key: 'duration',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: keyof typeof statusMap) => (
        <Tag color={statusMap[status].color} icon={statusMap[status].icon}>
          {statusMap[status].text}
        </Tag>
      ),
    },
  ];

  return (
    <div>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>分析审计</Title>
        <Text type="secondary">追踪所有用户操作和系统事件</Text>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Statistic title="今日操作" value={12} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Statistic 
              title="成功操作" 
              value={10} 
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Statistic 
              title="失败操作" 
              value={2} 
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Statistic title="进行中" value={0} />
          </Card>
        </Col>
      </Row>

      {/* 筛选器 */}
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col>
            <Input
              placeholder="搜索操作或对象..."
              prefix={<SearchOutlined />}
              style={{ width: 250 }}
            />
          </Col>
          <Col>
            <Select
              placeholder="操作类型"
              style={{ width: 120 }}
              allowClear
              options={[
                { value: 'create', label: '创建' },
                { value: 'read', label: '查看' },
                { value: 'update', label: '更新' },
                { value: 'delete', label: '删除' },
              ]}
            />
          </Col>
          <Col>
            <Select
              placeholder="状态"
              style={{ width: 120 }}
              value={selectedStatus}
              onChange={setSelectedStatus}
              options={[
                { value: 'all', label: '全部' },
                { value: 'success', label: '成功' },
                { value: 'failed', label: '失败' },
                { value: 'pending', label: '进行中' },
              ]}
            />
          </Col>
          <Col>
            <RangePicker />
          </Col>
          <Col flex="auto">
            <Space style={{ float: 'right' }}>
              <Button icon={<ReloadOutlined />}>刷新</Button>
              <Button icon={<DownloadOutlined />}>导出</Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 日志表格 */}
      <Card bordered={false}>
        <Table
          dataSource={logs}
          columns={columns}
          rowKey="key"
          size="middle"
          pagination={{
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条记录`,
          }}
        />
      </Card>
    </div>
  );
}
