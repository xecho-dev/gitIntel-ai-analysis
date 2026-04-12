import { useState } from 'react';
import { Table, Tag, Button, Space, Avatar, Input, Card, Row, Col, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  UserAddOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  MailOutlined,
  CheckCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';

const { Title, Text } = Typography;

interface User {
  id: string;
  key: string;
  name: string;
  email: string;
  avatar: string;
  role: 'admin' | 'user';
  status: 'active' | 'inactive';
  lastLogin: string;
  analyses: number;
}

export default function Users() {
  const [users] = useState<User[]>([
    { 
      key: '1', 
      id: '1',
      name: '张三', 
      email: 'zhang@example.com', 
      avatar: 'Z',
      role: 'admin', 
      status: 'active',
      lastLogin: '2026-04-12 10:30',
      analyses: 42,
    },
    { 
      key: '2', 
      id: '2',
      name: '李四', 
      email: 'li@example.com', 
      avatar: 'L',
      role: 'user', 
      status: 'active',
      lastLogin: '2026-04-11 15:20',
      analyses: 28,
    },
    { 
      key: '3', 
      id: '3',
      name: '王五', 
      email: 'wang@example.com', 
      avatar: 'W',
      role: 'user', 
      status: 'inactive',
      lastLogin: '2026-04-01 09:00',
      analyses: 15,
    },
    { 
      key: '4', 
      id: '4',
      name: '赵六', 
      email: 'zhao@example.com', 
      avatar: 'Z',
      role: 'user', 
      status: 'active',
      lastLogin: '2026-04-12 08:45',
      analyses: 63,
    },
  ]);

  const columns: ColumnsType<User> = [
    {
      title: '用户',
      key: 'user',
      render: (_, record) => (
        <Space>
          <Avatar style={{ background: record.role === 'admin' ? '#722ed1' : '#1677ff' }}>
            {record.avatar}
          </Avatar>
          <div>
            <Text strong>{record.name}</Text>
            <br />
            <Text type="secondary" style={{ fontSize: 12 }}>
              <MailOutlined style={{ marginRight: 4 }} />
              {record.email}
            </Text>
          </div>
        </Space>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'purple' : 'blue'} icon={role === 'admin' ? <CheckCircleOutlined /> : undefined}>
          {role === 'admin' ? '管理员' : '普通用户'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => (
        <Tag color={status === 'active' ? 'success' : 'default'} icon={status === 'active' ? <CheckCircleOutlined /> : <StopOutlined />}>
          {status === 'active' ? '正常' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '分析数',
      dataIndex: 'analyses',
      key: 'analyses',
      render: (num: number) => <Text strong>{num}</Text>,
    },
    {
      title: '最后登录',
      dataIndex: 'lastLogin',
      key: 'lastLogin',
    },
    {
      title: '操作',
      key: 'action',
      render: () => (
        <Space size="small">
          <Button type="text" size="small" icon={<EditOutlined />}>
            编辑
          </Button>
          <Button type="text" size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Title level={4} style={{ margin: 0 }}>用户管理</Title>
            <Text type="secondary">管理系��用户和权限</Text>
          </Col>
          <Col>
            <Button type="primary" icon={<UserAddOutlined />}>
              添加用户
            </Button>
          </Col>
        </Row>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Text type="secondary">总用户数</Text>
            <div style={{ fontSize: 24, fontWeight: 600, color: '#1677ff' }}>4</div>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Text type="secondary">管理员</Text>
            <div style={{ fontSize: 24, fontWeight: 600, color: '#722ed1' }}>1</div>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Text type="secondary">活跃用户</Text>
            <div style={{ fontSize: 24, fontWeight: 600, color: '#52c41a' }}>3</div>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Text type="secondary">总分析数</Text>
            <div style={{ fontSize: 24, fontWeight: 600, color: '#fa8c16' }}>148</div>
          </Card>
        </Col>
      </Row>

      {/* 用户表格 */}
      <Card bordered={false}>
        <div style={{ marginBottom: 16 }}>
          <Input
            placeholder="搜索用户..."
            prefix={<SearchOutlined />}
            style={{ width: 300 }}
          />
        </div>
        <Table dataSource={users} columns={columns} rowKey="key" size="middle" />
      </Card>
    </div>
  );
}