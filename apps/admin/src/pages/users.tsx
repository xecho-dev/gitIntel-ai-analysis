import { useState, useEffect, useCallback } from 'react';
import {
  Table,
  Tag,
  Button,
  Space,
  Avatar,
  Input,
  Card,
  Row,
  Col,
  Typography,
  Modal,
  message,
  Spin,
  Drawer,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  UserAddOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  MailOutlined,
  CheckCircleOutlined,
  StopOutlined,
  StarOutlined,
  ForkOutlined,
  HistoryOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { getUserList, updateUser } from '@/services/admin';
import type { AdminUserItem, AdminUserListResponse, AdminHistoryListResponse } from '@/types';
import AnalysisDetailDrawer from '@/components/AnalysisDetailDrawer';

const { Title, Text } = Typography;
const { confirm } = Modal;

export default function Users() {
  const [loading, setLoading] = useState(false);
  const [users, setUsers] = useState<AdminUserListResponse | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // 用户分析历史抽屉
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyData, setHistoryData] = useState<{
    user: AdminUserItem;
    history: AdminHistoryListResponse;
  } | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(10);

  // 详情抽屉
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailData, setDetailData] = useState<import('@/types').AdminHistoryDetailResponse | null>(null);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getUserList({ page, pageSize, search: search || undefined });
      setUsers(res);
    } catch {
      message.error('加载用户列表失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleSearch = () => {
    setPage(1);
    fetchUsers();
  };

  const handlePageChange = (newPage: number, newPageSize: number) => {
    if (newPageSize !== pageSize) {
      setPageSize(newPageSize);
      setPage(1);
    } else {
      setPage(newPage);
    }
  };

  const handleViewUserHistory = async (user: AdminUserItem) => {
    setHistoryOpen(true);
    setHistoryPage(1);
    setHistoryPageSize(10);
    setHistoryLoading(true);
    try {
      const { getUserHistory } = await import('@/services/admin');
      const res = await getUserHistory(user.id, { page: 1, pageSize: 10 });
      setHistoryData(res);
    } catch {
      message.error('加载用户分析历史失败');
      setHistoryOpen(false);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleHistoryPageChange = async (newPage: number, newPageSize: number) => {
    if (!historyData) return;
    setHistoryPage(newPage);
    setHistoryPageSize(newPageSize);
    setHistoryLoading(true);
    try {
      const { getUserHistory } = await import('@/services/admin');
      const res = await getUserHistory(historyData.user.id, {
        page: newPage,
        pageSize: newPageSize,
      });
      setHistoryData(res);
    } catch {
      message.error('加载失败');
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleViewDetail = async (recordId: string) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailData(null);
    try {
      const { getHistoryDetail } = await import('@/services/admin');
      const res = await getHistoryDetail(recordId);
      setDetailData(res);
    } catch {
      message.error('加载详情失败');
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const userColumns: ColumnsType<AdminUserItem> = [
    {
      title: '用户',
      key: 'user',
      render: (_, record) => (
        <Space>
          <Avatar
            src={record.avatar_url || undefined}
            style={{ background: '#1677ff' }}
          >
            {record.login?.slice(0, 1).toUpperCase() || 'U'}
          </Avatar>
          <div>
            <Text strong>{record.login}</Text>
            {record.name && (
              <Text type="secondary" style={{ display: 'block', fontSize: 11 }}>
                {record.name}
              </Text>
            )}
            {record.email && (
              <Text type="secondary" style={{ display: 'block', fontSize: 11 }}>
                <MailOutlined style={{ marginRight: 3 }} />
                {record.email}
              </Text>
            )}
          </div>
        </Space>
      ),
    },
    {
      title: 'GitHub 统计',
      key: 'github_stats',
      width: 180,
      render: (_, record) => (
        <Space size="middle">
          <Tooltip title="公开仓库">
            <span>
              <ForkOutlined style={{ color: '#8b909f', marginRight: 3 }} />
              <Text style={{ fontSize: 12 }}>{record.public_repos}</Text>
            </span>
          </Tooltip>
          <Tooltip title="Followers">
            <span>
              <StarOutlined style={{ color: '#8b909f', marginRight: 3 }} />
              <Text style={{ fontSize: 12 }}>{record.followers}</Text>
            </span>
          </Tooltip>
          <Tooltip title="Following">
            <span>
              <Text style={{ fontSize: 12 }}>{record.following}</Text>
              <Text type="secondary" style={{ fontSize: 11 }}> following</Text>
            </span>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: '位置',
      dataIndex: 'location',
      key: 'location',
      width: 120,
      render: (loc: string | null) => loc || <Text type="secondary">-</Text>,
    },
    {
      title: '注册时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (ts: string) => (
        <Text style={{ fontSize: 12 }} type="secondary">
          {dayjs(ts).format('YYYY-MM-DD HH:mm')}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_, record) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => handleViewUserHistory(record)}
          >
            分析记录
          </Button>
          <Button type="text" size="small" icon={<EditOutlined />}>
            编辑
          </Button>
        </Space>
      ),
    },
  ];

  const historyColumns: ColumnsType<import('@/types').AdminAnalysisItem> = [
    {
      title: '仓库',
      key: 'repo',
      render: (_, record) => (
        <div>
          <a
            href={record.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontWeight: 500 }}
          >
            {record.repo_name}
          </a>
          <div>
            <Tag style={{ fontSize: 10 }}>{record.branch || 'main'}</Tag>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {dayjs(record.created_at).format('YYYY-MM-DD HH:mm')}
            </Text>
          </div>
        </div>
      ),
    },
    {
      title: '健康分',
      dataIndex: 'health_score',
      key: 'health_score',
      width: 80,
      render: (s: number | null) => {
        if (s === null) return <Text type="secondary">-</Text>;
        const color = s >= 85 ? '#52c41a' : s >= 60 ? '#faad14' : '#ff4d4f';
        return <Tag color={s >= 85 ? 'success' : s >= 60 ? 'warning' : 'error'}>{s}%</Tag>;
      },
    },
    {
      title: '质量',
      dataIndex: 'quality_score',
      key: 'quality_score',
      width: 60,
      render: (score: string | null) => {
        const sc: Record<string, string> = {
          'A+': '#52c41a', 'A': '#73d13d', 'B+': '#1677ff', 'B': '#4096ff',
          'C': '#faad14', 'C-': '#ff7a45', 'D': '#ff4d4f',
        };
        return (
          <Tag style={{ color: sc[score || ''] || '#8b909f', fontWeight: 700 }}>
            {score || '-'}
          </Tag>
        );
      },
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 70,
      render: (level: string | null) => {
        const cfg: Record<string, { color: string; text: string }> = {
          高危: { color: '#ff4d4f', text: '高危' },
          中等: { color: '#722ed1', text: '中等' },
          极低: { color: '#52c41a', text: '极低' },
        };
        const c = cfg[level || ''] || { color: '#8b909f', text: level || '-' };
        return <Tag style={{ color: c.color, borderColor: c.color }}>{c.text}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, record) => (
        <Button
          type="text"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => handleViewDetail(record.id)}
        >
          详情
        </Button>
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
            <Text type="secondary">管理系统用户和权限</Text>
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
            <div style={{ fontSize: 24, fontWeight: 600, color: '#1677ff' }}>
              {users?.total || 0}
            </div>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Text type="secondary">活跃用户</Text>
            <div style={{ fontSize: 24, fontWeight: 600, color: '#52c41a' }}>
              {users?.items.filter((u) => u.email).length || 0}
            </div>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Text type="secondary">总仓库数</Text>
            <div style={{ fontSize: 24, fontWeight: 600, color: '#fa8c16' }}>
              {users?.items.reduce((acc, u) => acc + u.public_repos, 0) || 0}
            </div>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Text type="secondary">总关注者数</Text>
            <div style={{ fontSize: 24, fontWeight: 600, color: '#722ed1' }}>
              {users?.items.reduce((acc, u) => acc + u.followers, 0) || 0}
            </div>
          </Card>
        </Col>
      </Row>

      {/* 用户表格 */}
      <Card bordered={false}>
        <div style={{ marginBottom: 16 }}>
          <Space>
            <Input
              placeholder="搜索用户名或邮箱..."
              prefix={<SearchOutlined />}
              style={{ width: 300 }}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onPressEnter={handleSearch}
              allowClear
            />
            <Button type="primary" onClick={handleSearch}>搜索</Button>
          </Space>
        </div>
        <Spin spinning={loading}>
          <Table
            dataSource={users?.items || []}
            columns={userColumns}
            rowKey="id"
            size="middle"
            pagination={{
              current: page,
              pageSize: pageSize,
              total: users?.total || 0,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 条记录`,
              onChange: handlePageChange,
            }}
          />
        </Spin>
      </Card>

      {/* 用户分析历史抽屉 */}
      <Drawer
        title={
          historyData ? (
            <Space>
              <Avatar
                src={historyData.user.avatar_url || undefined}
                style={{ background: '#1677ff' }}
              >
                {historyData.user.login?.slice(0, 1).toUpperCase()}
              </Avatar>
              <span>{historyData.user.login} 的分析记录</span>
            </Space>
          ) : '用户分析记录'
        }
        placement="right"
        width={900}
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        styles={{ body: { padding: 0 } }}
      >
        <Spin spinning={historyLoading} tip="加载中...">
          {historyData && (
            <>
              {/* 用户基本信息 */}
              <div style={{ padding: '12px 24px', borderBottom: '1px solid #f3f4f6', background: '#fafafa' }}>
                <Space wrap>
                  {historyData.user.name && <Text>{historyData.user.name}</Text>}
                  {historyData.user.email && (
                    <Text type="secondary">
                      <MailOutlined style={{ marginRight: 4 }} />
                      {historyData.user.email}
                    </Text>
                  )}
                  {historyData.user.location && (
                    <Text type="secondary">{historyData.user.location}</Text>
                  )}
                  <Text type="secondary">
                    <ForkOutlined style={{ marginRight: 3 }} />
                    {historyData.user.public_repos} 仓库
                  </Text>
                  <Text type="secondary">
                    <StarOutlined style={{ marginRight: 3 }} />
                    {historyData.user.followers} followers
                  </Text>
                  {historyData.user.blog && (
                    <a href={historyData.user.blog} target="_blank" rel="noopener noreferrer">
                      <Text type="secondary">{historyData.user.blog}</Text>
                    </a>
                  )}
                </Space>
                {/* 历史统计 */}
                <Row gutter={[16, 8]} style={{ marginTop: 8 }}>
                  <Col>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      总分析: <strong style={{ color: '#1677ff' }}>{historyData.history.stats.total_scans}</strong>
                    </Text>
                  </Col>
                  <Col>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      平均健康分:{' '}
                      <strong style={{ color: historyData.history.stats.avg_health_score >= 85 ? '#52c41a' : '#faad14' }}>
                        {historyData.history.stats.avg_health_score}%
                      </strong>
                    </Text>
                  </Col>
                  <Col>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      高危: <strong style={{ color: '#ff4d4f' }}>{historyData.history.stats.high_risk_count}</strong>
                    </Text>
                  </Col>
                  <Col>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      中等: <strong style={{ color: '#722ed1' }}>{historyData.history.stats.medium_risk_count}</strong>
                    </Text>
                  </Col>
                </Row>
              </div>

              {/* 历史表格 */}
              <div style={{ padding: '16px 24px' }}>
                <Table
                  dataSource={historyData.history.items}
                  columns={historyColumns}
                  rowKey="id"
                  size="small"
                  pagination={{
                    current: historyPage,
                    pageSize: historyPageSize,
                    total: historyData.history.total,
                    showSizeChanger: true,
                    showTotal: (total) => `共 ${total} 条记录`,
                    onChange: handleHistoryPageChange,
                  }}
                />
              </div>
            </>
          )}
        </Spin>
      </Drawer>

      {/* 详情抽屉 */}
      <AnalysisDetailDrawer
        open={detailOpen}
        loading={detailLoading}
        data={detailData}
        onClose={() => {
          setDetailOpen(false);
          setDetailData(null);
        }}
      />
    </div>
  );
}
