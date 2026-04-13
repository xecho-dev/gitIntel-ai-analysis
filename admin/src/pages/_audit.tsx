import { useState, useEffect, useCallback } from 'react';
import {
  Table,
  Tag,
  Input,
  Card,
  Row,
  Col,
  Typography,
  Select,
  DatePicker,
  Space,
  Button,
  Statistic,
  Avatar,
  Modal,
  message,
  Spin,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  SearchOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  DownloadOutlined,
  UserOutlined,
  StarOutlined,
  ForkOutlined,
  EyeOutlined,
  SafetyCertificateOutlined,
  AlertOutlined,
  BarChartOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { getFilteredHistory, deleteAnalysisRecord, getHistoryDetail } from '@/services/admin';
import type { AdminAnalysisItem, AdminHistoryListResponse, HistoryFilterParams } from '@/types';
import AnalysisDetailDrawer from '@/components/AnalysisDetailDrawer';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;
const { confirm } = Modal;

const riskLevelMap: Record<string, { color: string; text: string }> = {
  高危: { color: '#ff4d4f', text: '高危' },
  中等: { color: '#722ed1', text: '中等' },
  极低: { color: '#52c41a', text: '极低' },
};

export default function Audit() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<AdminHistoryListResponse | null>(null);
  const [filters, setFilters] = useState<HistoryFilterParams>({
    page: 1,
    pageSize: 10,
  });

  // 筛选器状态
  const [searchText, setSearchText] = useState('');
  const [riskLevel, setRiskLevel] = useState<string | undefined>();
  const [qualityFilter, setQualityFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<string>('all');

  // 详情抽屉
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailData, setDetailData] = useState<import('@/types').AdminHistoryDetailResponse | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getFilteredHistory(filters);
      setData(res);
    } catch {
      message.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleSearch = () => {
    const newFilters: HistoryFilterParams = {
      page: 1,
      pageSize: filters.pageSize || 10,
      search: searchText || undefined,
      risk_level: riskLevel,
      repo_name: searchText || undefined,
      date_from: dateRange?.[0]?.format('YYYY-MM-DD'),
      date_to: dateRange?.[1]?.format('YYYY-MM-DD'),
    };

    if (qualityFilter) {
      const maxMap: Record<string, number> = {
        'A+': 100, 'A': 85, 'B+': 75, 'B': 65, 'C': 55, 'C-': 45, 'D': 0,
      };
      newFilters.quality_score_max = maxMap[qualityFilter];
    }

    setFilters(newFilters);
  };

  const handleReset = () => {
    setSearchText('');
    setRiskLevel(undefined);
    setQualityFilter(undefined);
    setDateRange(null);
    setSelectedStatus('all');
    setFilters({ page: 1, pageSize: 10 });
  };

  const handlePageChange = (page: number, pageSize: number) => {
    setFilters((prev) => ({ ...prev, page, pageSize }));
  };

  const handleViewDetail = async (record: AdminAnalysisItem) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailData(null);
    try {
      const res = await getHistoryDetail(record.id);
      setDetailData(res);
    } catch {
      message.error('加载详情失败');
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = (record: AdminAnalysisItem) => {
    confirm({
      title: '确认删除',
      content: `确定要删除 "${record.repo_name}" 的分析记录吗？此操作不可恢复。`,
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteAnalysisRecord(record.id);
          message.success('删除成功');
          fetchData();
        } catch {
          message.error('删除失败');
        }
      },
    });
  };

  const stats = data?.stats;
  const items = data?.items || [];

  // 计算筛选后的统计数据（基于当前数据）
  const filteredStats = {
    total: items.length,
    successCount: items.filter((i) => i.health_score !== null && i.health_score !== undefined).length,
    failedCount: items.filter((i) => i.health_score === null).length,
  };

  const columns: ColumnsType<AdminAnalysisItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (ts: string) => (
        <Space>
          <ClockCircleOutlined style={{ color: '#8b909f', fontSize: 12 }} />
          <Text style={{ fontSize: 12 }}>{dayjs(ts).format('YYYY-MM-DD HH:mm:ss')}</Text>
        </Space>
      ),
    },
    {
      title: '用户',
      key: 'user',
      width: 150,
      render: (_, record) => (
        <Space>
          <Avatar
            size="small"
            style={{ background: '#1677ff', fontSize: 10, minWidth: 24 }}
          >
            {record.user_id?.slice(0, 2).toUpperCase() || 'U'}
          </Avatar>
          <Tooltip title={record.user_id}>
            <Text style={{ fontSize: 12 }} type="secondary">
              {record.user_id?.slice(0, 8)}...
            </Text>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: '仓库',
      key: 'repo',
      render: (_, record) => (
        <div>
          <a
            href={record.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontWeight: 500, fontSize: 13 }}
          >
            {record.repo_name}
          </a>
          <div style={{ marginTop: 2 }}>
            <Tag icon={<ForkOutlined />} style={{ fontSize: 10 }}>
              {record.branch || 'main'}
            </Tag>
          </div>
        </div>
      ),
    },
    {
      title: '健康分',
      dataIndex: 'health_score',
      key: 'health_score',
      width: 90,
      sorter: (a, b) => (a.health_score ?? 0) - (b.health_score ?? 0),
      render: (score: number | null) => {
        if (score === null || score === undefined) return <Text type="secondary">-</Text>;
        const color = score >= 85 ? '#52c41a' : score >= 60 ? '#faad14' : '#ff4d4f';
        return (
          <Tag color={score >= 85 ? 'success' : score >= 60 ? 'warning' : 'error'}>
            {score}%
          </Tag>
        );
      },
    },
    {
      title: '质量',
      dataIndex: 'quality_score',
      key: 'quality_score',
      width: 70,
      render: (score: string | null) => {
        const scoreColors: Record<string, string> = {
          'A+': '#52c41a', 'A': '#73d13d', 'B+': '#1677ff', 'B': '#4096ff',
          'C': '#faad14', 'C-': '#ff7a45', 'D': '#ff4d4f',
        };
        return (
          <Tag
            style={{
              color: scoreColors[score || ''] || '#8b909f',
              borderColor: scoreColors[score || ''] || '#8b909f',
              fontWeight: 700,
              minWidth: 36,
              textAlign: 'center',
            }}
          >
            {score || '-'}
          </Tag>
        );
      },
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 90,
      render: (level: string | null) => {
        const cfg = riskLevelMap[level || ''] || { color: '#8b909f', text: '-' };
        return (
          <Tag
            style={{
              color: cfg.color,
              borderColor: cfg.color,
              background: `${cfg.color}15`,
            }}
          >
            {cfg.text}
          </Tag>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'health_score',
      key: 'status',
      width: 90,
      render: (score: number | null) => {
        const cfg = score !== null
          ? { color: 'success', text: '成功', icon: <CheckCircleOutlined /> }
          : { color: 'error', text: '失败', icon: <CloseCircleOutlined /> };
        return (
          <Tag color={cfg.color} icon={cfg.icon}>
            {cfg.text}
          </Tag>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, record) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleViewDetail(record)}
          >
            详情
          </Button>
          <Button
            type="text"
            size="small"
            danger
            icon={<CloseCircleOutlined />}
            onClick={() => handleDelete(record)}
          />
        </Space>
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
            <Statistic
              title={<Text type="secondary">总分析次数</Text>}
              value={stats?.total_scans || 0}
              prefix={<BarChartOutlined style={{ color: '#1677ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Statistic
              title={<Text type="secondary">成功操作</Text>}
              value={filteredStats.successCount}
              prefix={<SafetyCertificateOutlined style={{ color: '#52c41a' }} />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Statistic
              title={<Text type="secondary">高危项目</Text>}
              value={stats?.high_risk_count || 0}
              prefix={<AlertOutlined style={{ color: '#ff4d4f' }} />}
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card bordered={false} size="small">
            <Statistic
              title={<Text type="secondary">中等风险</Text>}
              value={stats?.medium_risk_count || 0}
              prefix={<AlertOutlined style={{ color: '#722ed1' }} />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 筛选器 */}
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={12} lg={6}>
            <Input
              placeholder="搜索仓库名..."
              prefix={<SearchOutlined />}
              allowClear
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col xs={12} sm={8} lg={3}>
            <Select
              placeholder="风险等级"
              allowClear
              style={{ width: '100%' }}
              value={riskLevel}
              onChange={setRiskLevel}
              options={[
                { value: '高危', label: '高危' },
                { value: '中等', label: '中等' },
                { value: '极低', label: '极低' },
              ]}
            />
          </Col>
          <Col xs={12} sm={8} lg={4}>
            <Select
              placeholder="质量评分"
              allowClear
              style={{ width: '100%' }}
              value={qualityFilter}
              onChange={setQualityFilter}
              options={[
                { value: 'A+', label: 'A+ (>=85)' },
                { value: 'A', label: 'A (>=75)' },
                { value: 'B+', label: 'B+ (>=65)' },
                { value: 'B', label: 'B (>=55)' },
                { value: 'C', label: 'C (>=45)' },
                { value: 'D', label: 'D (<45)' },
              ]}
            />
          </Col>
          <Col xs={24} lg={8}>
            <RangePicker
              style={{ width: '100%' }}
              value={dateRange}
              onChange={(dates) => setDateRange(dates as [dayjs.Dayjs | null, dayjs.Dayjs | null] | null)}
              placeholder={['开始日期', '结束日期']}
            />
          </Col>
          <Col xs={24} lg={3}>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button icon={<ReloadOutlined />} onClick={handleReset}>重置</Button>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 日志表格 */}
      <Card bordered={false}>
        <Spin spinning={loading}>
          <Table
            dataSource={items}
            columns={columns}
            rowKey="id"
            size="middle"
            scroll={{ x: 1000 }}
            pagination={{
              current: data?.page || 1,
              pageSize: data?.pageSize || 10,
              total: data?.total || 0,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 条记录`,
              onChange: handlePageChange,
            }}
          />
        </Spin>
      </Card>

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
