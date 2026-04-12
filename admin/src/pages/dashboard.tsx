import { useEffect, useState } from 'react';
import { Card, Statistic, Row, Col, Table, Tag, Progress, Timeline, Typography, Space } from 'antd';
import {
  BarChartOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  RiseOutlined,
  ArrowUpOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

const { Title, Text } = Typography;

interface Analysis {
  id: string;
  repo: string;
  owner: string;
  status: 'completed' | 'pending' | 'failed' | 'running';
  date: string;
  score: number;
}

export default function Dashboard() {
  const [analyses] = useState<Analysis[]>([
    { id: '1', repo: 'react', owner: 'facebook', status: 'completed', date: '2026-04-10', score: 92 },
    { id: '2', repo: 'vscode', owner: 'microsoft', status: 'completed', date: '2026-04-11', score: 88 },
    { id: '3', repo: 'next.js', owner: 'vercel', status: 'running', date: '2026-04-12', score: 0 },
    { id: '4', repo: 'tensorflow', owner: 'tensorflow', status: 'pending', date: '2026-04-12', score: 0 },
    { id: '5', repo: 'rust', owner: 'rust-lang', status: 'completed', date: '2026-04-09', score: 95 },
    { id: '6', repo: 'golang', owner: 'golang', status: 'failed', date: '2026-04-08', score: 0 },
  ]);

  const statusMap = {
    completed: { color: 'success', text: '已完成', icon: <CheckCircleOutlined /> },
    pending: { color: 'processing', text: '排队中', icon: <ClockCircleOutlined /> },
    running: { color: 'warning', text: '进行中', icon: <BarChartOutlined /> },
    failed: { color: 'error', text: '失败', icon: <CloseCircleOutlined /> },
  };

  const columns: ColumnsType<Analysis> = [
    {
      title: '仓库',
      key: 'repo',
      render: (_, record) => (
        <Space>
          <Text strong>{record.owner}/{record.repo}</Text>
        </Space>
      ),
    },
    {
      title: '日期',
      dataIndex: 'date',
      key: 'date',
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
    {
      title: '质量评分',
      dataIndex: 'score',
      key: 'score',
      render: (score: number) =>
        score > 0 ? (
          <Progress
            percent={score}
            size="small"
            strokeColor={score >= 90 ? '#52c41a' : score >= 70 ? '#1677ff' : '#faad14'}
          />
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
  ];

  return (
    <div>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>仪表盘</Title>
        <Text type="secondary">查看系统运行状态和数据分析概览</Text>
      </div>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false}>
            <Statistic
              title={<Text type="secondary">总分析数</Text>}
              value={156}
              prefix={<BarChartOutlined style={{ color: '#1677ff' }} />}
              suffix={
                <Text type="success" style={{ fontSize: 14 }}>
                  <ArrowUpOutlined /> 12%
                </Text>
              }
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false}>
            <Statistic
              title={<Text type="secondary">已完成</Text>}
              value={144}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false}>
            <Statistic
              title={<Text type="secondary">进行中</Text>}
              value={8}
              prefix={<ClockCircleOutlined style={{ color: '#faad14' }} />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false}>
            <Statistic
              title={<Text type="secondary">失败</Text>}
              value={4}
              prefix={<CloseCircleOutlined style={{ color: '#ff4d4f' }} />}
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 图表和分析列表 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card
            title="最近分析"
            extra={<Text type="secondary">共 {analyses.length} 条记录</Text>}
            bordered={false}
          >
            <Table
              dataSource={analyses}
              columns={columns}
              rowKey="id"
              pagination={false}
              size="middle"
            />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="系统状态" bordered={false} style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={16}>
              <div>
                <Row justify="space-between">
                  <Text>API 服务</Text>
                  <Tag color="success">在线</Tag>
                </Row>
              </div>
              <div>
                <Row justify="space-between">
                  <Text>数据库</Text>
                  <Tag color="success">正常</Tag>
                </Row>
              </div>
              <div>
                <Row justify="space-between">
                  <Text>AI 模型</Text>
                  <Tag color="success">就绪</Tag>
                </Row>
              </div>
              <div>
                <Row justify="space-between">
                  <Text>队列任务</Text>
                  <Tag color="processing">3 个运行中</Tag>
                </Row>
              </div>
            </Space>
          </Card>

          <Card title="最近活动" bordered={false}>
            <Timeline
              items={[
                { color: 'green', children: '分析 facebook/react 完成' },
                { color: 'green', children: '分析 microsoft/vscode 完成' },
                { color: 'blue', children: '开始分析 vercel/next.js' },
                { color: 'gray', children: '系统维护完成' },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
