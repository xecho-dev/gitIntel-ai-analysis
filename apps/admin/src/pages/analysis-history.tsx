import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Input,
  Select,
  DatePicker,
  Row,
  Col,
  Typography,
  Statistic,
  Avatar,
  Progress,
  Modal,
  message,
  Badge,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  SearchOutlined,
  ReloadOutlined,
  DeleteOutlined,
  EyeOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  AlertOutlined,
  UserOutlined,
  StarOutlined,
  ForkOutlined,
  ClockCircleOutlined,
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

export default function AnalysisHistoryPage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<AdminHistoryListResponse | null>(null);
  const [filters, setFilters] = useState<HistoryFilterParams>({
    page: 1,
    pageSize: 10,
  });
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailData, setDetailData] = useState<import('@/types').AdminHistoryDetailResponse | null>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getFilteredHistory(filters);
      setData(res);
    } catch (err) {
      message.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handlePageChange = (page: number, pageSize: number) => {
    setFilters((prev) => ({ ...prev, page, pageSize }));
  };

  const handleFilterChange = (key: keyof HistoryFilterParams, value: unknown) => {
    setFilters((prev) => ({ ...prev, [key]: value, page: 1 }));
  };

  const handleReset = () => {
    setFilters({ page: 1, pageSize: 10 });
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

  const handleViewDetail = async (record: AdminAnalysisItem) => {
    setSelectedRecordId(record.id);
    setDetailOpen(true);
    setDetailData(null);
    setDetailLoading(true);
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

  const columns: ColumnsType<AdminAnalysisItem> = [
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
            <Tag icon={<ForkOutlined />} style={{ fontSize: 11, marginTop: 2 }}>
              {record.branch || 'main'}
            </Tag>
            <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
              <ClockCircleOutlined style={{ marginRight: 3 }} />
              {dayjs(record.created_at).format('YYYY-MM-DD HH:mm')}
            </Text>
          </div>
        </div>
      ),
    },
    {
      title: '用户',
      key: 'user',
      width: 160,
      render: (_, record) => (
        <Space>
          <Avatar size="small" style={{ background: '#1677ff', fontSize: 11 }}>
            {record.user_id?.slice(0, 2).toUpperCase() || 'U'}
          </Avatar>
          <Text style={{ fontSize: 12 }} type="secondary">{record.user_id?.slice(0, 8)}...</Text>
        </Space>
      ),
    },
    {
      title: '健康分',
      dataIndex: 'health_score',
      key: 'health_score',
      width: 120,
      sorter: (a, b) => (a.health_score ?? 0) - (b.health_score ?? 0),
      render: (score: number | null) => (
        score !== null && score !== undefined ? (
          <Progress
            percent={score}
            size="small"
            strokeColor={
              score >= 85 ? '#52c41a' : score >= 60 ? '#faad14' : '#ff4d4f'
            }
            format={(p) => <span style={{ fontSize: 11 }}>{p}</span>}
          />
        ) : <Text type="secondary">-</Text>
      ),
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
            color={scoreColors[score || ''] || 'default'}
            style={{ fontWeight: 700, minWidth: 36, textAlign: 'center' }}
          >
            {score || '-'}
          </Tag>
        );
      },
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 80,
      render: (level: string | null) => {
        const cfg = riskLevelMap[level || ''] || { color: '#8b909f', text: '-' };
        return <Tag style={{ color: cfg.color, borderColor: cfg.color }}>{cfg.text}</Tag>;
      },
    },
    {
      title: '分析内容',
      key: 'result_preview',
      width: 200,
      render: (_, record) => {
        const result = record.result_data as Record<string, unknown> | undefined;
        const agents = result ? Object.keys(result) : [];
        return (
          <Space wrap size={[4, 4]}>
            {agents.map((a) => (
              <Tag key={a} style={{ fontSize: 11 }}>{a}</Tag>
            ))}
            {!agents.length && <Text type="secondary">-</Text>}
          </Space>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      fixed: 'right',
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
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
          />
        </Space>
      ),
    },
  ];

  const stats = data?.stats;

  return (
    <div>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>分析记录</Title>
        <Text type="secondary">查看所有用户的完整分析记录和结果</Text>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
          <Col xs={12} lg={6}>
            <Card bordered={false} size="small">
              <Statistic
                title={<Text type="secondary">总分析次数</Text>}
                value={stats.total_scans}
                prefix={<BarChartOutlined style={{ color: '#1677ff' }} />}
              />
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card bordered={false} size="small">
              <Statistic
                title={<Text type="secondary">平均健康分</Text>}
                value={stats.avg_health_score}
                suffix="%"
                prefix={<SafetyCertificateOutlined style={{ color: '#52c41a' }} />}
                valueStyle={{ color: stats.avg_health_score >= 85 ? '#52c41a' : '#faad14' }}
              />
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card bordered={false} size="small">
              <Statistic
                title={<Text type="secondary">高危项目</Text>}
                value={stats.high_risk_count}
                prefix={<AlertOutlined style={{ color: '#ff4d4f' }} />}
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card bordered={false} size="small">
              <Statistic
                title={<Text type="secondary">中等风险</Text>}
                value={stats.medium_risk_count}
                prefix={<AlertOutlined style={{ color: '#722ed1' }} />}
                valueStyle={{ color: '#722ed1' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 高级筛选器 */}
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={12} lg={6}>
            <Input
              placeholder="搜索仓库名..."
              prefix={<SearchOutlined />}
              allowClear
              value={filters.repo_name || ''}
              onChange={(e) => handleFilterChange('repo_name', e.target.value || undefined)}
            />
          </Col>
          <Col xs={12} sm={8} lg={3}>
            <Select
              placeholder="风险等级"
              allowClear
              style={{ width: '100%' }}
              value={filters.risk_level}
              onChange={(v) => handleFilterChange('risk_level', v)}
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
              value={filters.quality_score_max !== undefined ? String(filters.quality_score_max) : undefined}
              onChange={(v) => {
                if (v) {
                  const maxMap: Record<string, number> = { 'A+': 100, 'A': 85, 'B+': 75, 'B': 65, 'C': 55, 'C-': 45, 'D': 0 };
                  handleFilterChange('quality_score_max', maxMap[v]);
                } else {
                  handleFilterChange('quality_score_max', undefined);
                }
              }}
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
              value={[
                filters.date_from ? dayjs(filters.date_from) : null,
                filters.date_to ? dayjs(filters.date_to) : null,
              ]}
              onChange={(dates) => {
                handleFilterChange('date_from', dates?.[0]?.format('YYYY-MM-DD') || undefined);
                handleFilterChange('date_to', dates?.[1]?.format('YYYY-MM-DD') || undefined);
              }}
              placeholder={['开始日期', '结束日期']}
            />
          </Col>
          <Col xs={24} lg={24}>
            <Space style={{ float: 'right' }}>
              <Button icon={<ReloadOutlined />} onClick={handleReset}>重置</Button>
              <Button type="primary" icon={<SearchOutlined />} onClick={fetchData}>搜索</Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 表格 */}
      <Card bordered={false}>
        <Table
          dataSource={data?.items || []}
          columns={columns}
          rowKey="id"
          size="middle"
          loading={loading}
          scroll={{ x: 900 }}
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
      </Card>

      {/* 详情抽屉 */}
      <AnalysisDetailDrawer
        open={detailOpen}
        loading={detailLoading}
        data={detailData}
        onClose={() => {
          setDetailOpen(false);
          setDetailData(null);
          setSelectedRecordId(null);
        }}
      />
    </div>
  );
}
