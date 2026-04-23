import {
  Drawer,
  Tabs,
  Descriptions,
  Tag,
  Card,
  Row,
  Col,
  Typography,
  Space,
  Avatar,
  Progress,
  Statistic,
  Badge,
  Tooltip,
  Spin,
  Alert,
  Button,
  List,
} from 'antd';
import {
  SafetyCertificateOutlined,
  AlertOutlined,
  ApartmentOutlined,
  ExperimentOutlined,
  AppstoreOutlined,
  BulbOutlined,
  LinkOutlined,
  UserOutlined,
  TrophyOutlined,
  ExclamationCircleOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  GlobalOutlined,
  ForkOutlined,
  StarOutlined,
  RadarChartOutlined,
} from '@ant-design/icons';
import type { AdminHistoryDetailResponse, AdminUserItem, LangSmithTraceInfo } from '@/types';

const { Title, Text, Paragraph } = Typography;

interface AnalysisDetailDrawerProps {
  open: boolean;
  loading: boolean;
  data: AdminHistoryDetailResponse | null;
  onClose: () => void;
}

// ─── 共享配色常量 ─────────────────────────────────────────────────────────────

const RISK_COLOR = { high: '#ef4444', medium: '#f59e0b', low: '#10b981', none: '#6b7280' };
const SCORE_COLOR = { excellent: '#10b981', good: '#3b82f6', warning: '#f59e0b', danger: '#ef4444' };

function riskColor(level?: string | null): string {
  if (!level) return RISK_COLOR.none;
  if (level.includes('高')) return RISK_COLOR.high;
  if (level.includes('中')) return RISK_COLOR.medium;
  return RISK_COLOR.low;
}

function scoreColor(score?: string | null): string {
  if (!score) return RISK_COLOR.none;
  if (score.startsWith('A')) return SCORE_COLOR.excellent;
  if (score.startsWith('B')) return SCORE_COLOR.good;
  if (score.startsWith('C')) return SCORE_COLOR.warning;
  return SCORE_COLOR.danger;
}

function RiskBadge({ risk_level }: { risk_level?: string | null }) {
  return (
    <Badge
      status={risk_level?.includes('高') ? 'error' : risk_level?.includes('中') ? 'warning' : 'success'}
      text={<span style={{ color: riskColor(risk_level), fontWeight: 500 }}>{risk_level || '-'}</span>}
    />
  );
}

function QualityScoreBadge({ score }: { score?: string | null }) {
  return (
    <Tag
      style={{
        fontWeight: 600,
        fontSize: 13,
        minWidth: 40,
        textAlign: 'center',
        border: 'none',
        color: scoreColor(score),
        background: `${scoreColor(score)}18`,
      }}
    >
      {score || '-'}
    </Tag>
  );
}

// ─── Agent 结果卡片 ───────────────────────────────────────────────────────────

function AgentResultCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card
      size="small"
      title={
        <Space size={6}>
          {icon}
          <span style={{ fontWeight: 500 }}>{title}</span>
        </Space>
      }
      style={{ marginBottom: 16 }}
      styles={{ body: { padding: '12px 16px' } }}
    >
      {children}
    </Card>
  );
}

// ─── 技术栈结果 ──────────────────────────────────────────────────────────────

function TechStackPanel({ result }: { result?: Record<string, unknown> }) {
  if (!result) return <Text type="secondary">暂无数据</Text>;
  const { languages = [], frameworks = [], infrastructure = [], dev_tools = [], package_manager, dependency_count } = result as Record<string, unknown>;

  return (
    <div>
      <Row gutter={[16, 12]}>
        <Col xs={24} sm={8}>
          <Text type="secondary" style={{ fontSize: 12 }}>包管理器</Text>
          <div><Text strong>{package_manager || '-'}</Text></div>
        </Col>
        <Col xs={24} sm={8}>
          <Text type="secondary" style={{ fontSize: 12 }}>总依赖数</Text>
          <div><Text strong>{dependency_count ?? '-'}</Text></div>
        </Col>
      </Row>

      {languages.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            <GlobalOutlined /> 语言
          </Text>
          <Space size={6} wrap>
            {(languages as string[]).map((l) => <Tag key={l}>{l}</Tag>)}
          </Space>
        </div>
      )}
      {frameworks.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            <ForkOutlined /> 框架
          </Text>
          <Space size={6} wrap>
            {(frameworks as string[]).map((f) => <Tag key={f}>{f}</Tag>)}
          </Space>
        </div>
      )}
      {infrastructure.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            <RadarChartOutlined /> 基础设施
          </Text>
          <Space size={6} wrap>
            {(infrastructure as string[]).map((i) => <Tag key={i}>{i}</Tag>)}
          </Space>
        </div>
      )}
      {dev_tools.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            <StarOutlined /> 开发工具
          </Text>
          <Space size={6} wrap>
            {(dev_tools as string[]).map((t) => <Tag key={t}>{t}</Tag>)}
          </Space>
        </div>
      )}
    </div>
  );
}

// ─── 代码质量结果 ─────────────────────────────────────────────────────────────

function QualityPanel({ result }: { result?: Record<string, unknown> }) {
  if (!result) return <Text type="secondary">暂无数据</Text>;

  const {
    health_score, test_coverage, complexity,
    python_metrics, typescript_metrics, duplication,
    test_info,
    maint_score, comp_score, dup_score, test_score, coup_score,
  } = result as Record<string, unknown>;

  const scoreItems = [
    { label: '可维护性', score: maint_score },
    { label: '圈复杂度', score: comp_score },
    { label: '重复率', score: dup_score },
    { label: '测试覆盖', score: test_score },
    { label: '耦合度', score: coup_score },
  ];

  const getBarColor = (score?: number) => {
    if (!score) return '#e5e7eb';
    if (score >= 80) return SCORE_COLOR.excellent;
    if (score >= 60) return SCORE_COLOR.warning;
    return SCORE_COLOR.danger;
  };

  const healthColor = (health_score as number) >= 85 ? SCORE_COLOR.excellent : (health_score as number) >= 60 ? SCORE_COLOR.warning : SCORE_COLOR.danger;
  const coverageColor = (test_coverage as number) >= 60 ? SCORE_COLOR.excellent : SCORE_COLOR.warning;

  return (
    <div>
      <Row gutter={[12, 12]} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 12 }}>健康分</Text>}
              value={health_score ?? 0}
              suffix="%"
              valueStyle={{ color: healthColor, fontSize: 28, fontWeight: 600 }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 12 }}>测试覆盖率</Text>}
              value={test_coverage ?? 0}
              suffix="%"
              valueStyle={{ color: coverageColor, fontSize: 28, fontWeight: 600 }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 12 }}>复杂度</Text>}
              value={complexity || '-'}
              valueStyle={{ fontSize: 22, fontWeight: 600 }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[8, 8]} style={{ marginBottom: 20 }}>
        {scoreItems.map((item) => (
          <Col xs={24} sm={12} key={item.label}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Text style={{ width: 56, fontSize: 12, color: '#6b7280' }}>{item.label}</Text>
              <Progress
                percent={item.score || 0}
                size="small"
                strokeColor={getBarColor(item.score as number)}
                style={{ flex: 1 }}
                format={(p) => <Text style={{ fontSize: 11, color: '#6b7280' }}>{p}</Text>}
              />
            </div>
          </Col>
        ))}
      </Row>

      {duplication && (
        <AgentResultCard title="重复代码" icon={<AppstoreOutlined style={{ color: '#3b82f6' }} />}>
          <Space>
            <Tag color={((duplication as Record<string, unknown>).score as number) < 5 ? 'green' : 'orange'}>
              {(duplication as Record<string, unknown>).score}%
            </Tag>
            <Text type="secondary">{(duplication as Record<string, unknown>).duplication_level}</Text>
          </Space>
        </AgentResultCard>
      )}

      {python_metrics && (
        <AgentResultCard title="Python 指标" icon={<span style={{ color: '#3b82f6', fontFamily: 'monospace', fontSize: 12 }}>Py</span>}>
          <Row gutter={[8, 8]}>
            <Col span={12}><Text type="secondary" style={{ fontSize: 12 }}>函数总数</Text><div>{(python_metrics as Record<string, unknown>).total_functions ?? '-'}</div></Col>
            <Col span={12}><Text type="secondary" style={{ fontSize: 12 }}>平均复杂度</Text><div>{(python_metrics as Record<string, unknown>).avg_complexity ?? '-'}</div></Col>
            <Col span={12}><Text type="secondary" style={{ fontSize: 12 }}>超复杂函数</Text><div>{(python_metrics as Record<string, unknown>).over_complexity_count ?? '-'}</div></Col>
            <Col span={12}><Text type="secondary" style={{ fontSize: 12 }}>圈复杂度</Text><div>{(python_metrics as Record<string, unknown>).cyclomatic_complexity ?? '-'}</div></Col>
          </Row>
        </AgentResultCard>
      )}

      {typescript_metrics && (
        <AgentResultCard title="TypeScript 指标" icon={<span style={{ color: '#3b82f6', fontFamily: 'monospace', fontSize: 12 }}>TS</span>}>
          <Row gutter={[8, 8]}>
            <Col span={12}><Text type="secondary" style={{ fontSize: 12 }}>函数总数</Text><div>{(typescript_metrics as Record<string, unknown>).total_functions ?? '-'}</div></Col>
            <Col span={12}><Text type="secondary" style={{ fontSize: 12 }}>平均复杂度</Text><div>{(typescript_metrics as Record<string, unknown>).avg_complexity ?? '-'}</div></Col>
            <Col span={12}><Text type="secondary" style={{ fontSize: 12 }}>超复杂函数</Text><div>{(typescript_metrics as Record<string, unknown>).over_complexity_count ?? '-'}</div></Col>
            <Col span={12}><Text type="secondary" style={{ fontSize: 12 }}>总行数</Text><div>{(typescript_metrics as Record<string, unknown>).total_lines ?? '-'}</div></Col>
          </Row>
        </AgentResultCard>
      )}

      {test_info && (
        <AgentResultCard title="测试信息" icon={<ExperimentOutlined style={{ color: '#3b82f6' }} />}>
          <Space>
            <Text type="secondary">{(test_info as Record<string, unknown>).test_files ?? '-'} 文件</Text>
            <Text type="secondary">覆盖率 {(test_info as Record<string, unknown>).estimated_coverage ?? '-'}%</Text>
          </Space>
        </AgentResultCard>
      )}
    </div>
  );
}

// ─── 依赖风险结果 ─────────────────────────────────────────────────────────────

function DependencyPanel({ result }: { result?: Record<string, unknown> }) {
  if (!result) return <Text type="secondary">暂无数据</Text>;

  const { total, high = 0, medium = 0, low = 0, risk_level: riskLevel, summary, deps } = result as Record<string, unknown>;

  return (
    <div>
      <Row gutter={[8, 8]} style={{ marginBottom: 20 }}>
        <Col xs={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>总依赖</Text>} value={total ?? 0} valueStyle={{ fontSize: 20, fontWeight: 600 }} />
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>高危</Text>} value={high as number} valueStyle={{ fontSize: 20, fontWeight: 600, color: high > 0 ? RISK_COLOR.high : undefined }} />
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>中危</Text>} value={medium as number} valueStyle={{ fontSize: 20, fontWeight: 600, color: medium > 0 ? RISK_COLOR.medium : undefined }} />
          </Card>
        </Col>
      </Row>

      {riskLevel && (
        <Alert
          message={<Text strong>风险等级: {riskLevel as string}</Text>}
          description={
            <div>
              {(summary as string[])?.map((s, i) => <div key={i} style={{ fontSize: 13 }}>{s}</div>)}
            </div>
          }
          type={high > 0 ? 'error' : medium > 0 ? 'warning' : 'success'}
          style={{ marginBottom: 16 }}
          showIcon
        />
      )}

      {(deps as Array<Record<string, unknown>>)?.length > 0 && (
        <AgentResultCard
          title={`风险依赖详情 (${(deps as Array<Record<string, unknown>>).length})`}
          icon={<AlertOutlined style={{ color: RISK_COLOR.high }} />}
        >
          <List
            size="small"
            dataSource={deps as Array<Record<string, unknown>>}
            renderItem={(dep) => (
              <List.Item style={{ padding: '8px 0' }}>
                <Space style={{ width: '100%' }} size="middle">
                  <Text code style={{ minWidth: 120, fontSize: 12 }}>{dep.name as string}</Text>
                  <Tag style={{ border: 'none', color: '#6b7280', background: '#f3f4f6' }}>{dep.version as string}</Tag>
                  <Tag color={
                    dep.risk_level === 'high' ? 'red' :
                    dep.risk_level === 'medium' ? 'orange' : 'green'
                  }>
                    {dep.risk_level as string}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 12, flex: 1 }}>{dep.risk_reason as string}</Text>
                </Space>
              </List.Item>
            )}
          />
        </AgentResultCard>
      )}
    </div>
  );
}

// ─── 架构分析结果 ─────────────────────────────────────────────────────────────

function ArchitecturePanel({ result }: { result?: Record<string, unknown> }) {
  if (!result) return <Text type="secondary">暂无数据</Text>;

  const { complexity, components, techStack, maintainability, architectureStyle, keyPatterns, hotSpots, summary } = result as Record<string, unknown>;

  return (
    <div>
      <Row gutter={[8, 8]} style={{ marginBottom: 20 }}>
        <Col xs={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>复杂度</Text>} value={complexity || '-'} valueStyle={{ fontSize: 20, fontWeight: 600 }} />
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>组件数</Text>} value={components ?? '-'} valueStyle={{ fontSize: 20, fontWeight: 600 }} />
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>可维护性</Text>} value={maintainability || '-'} valueStyle={{ fontSize: 20, fontWeight: 600 }} />
          </Card>
        </Col>
      </Row>

      {architectureStyle && (
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>架构风格</Text>
          <Tag>{architectureStyle as string}</Tag>
        </div>
      )}

      {techStack && (techStack as string[]).length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>技术栈</Text>
          <Space size={6} wrap>
            {(techStack as string[]).map((t) => <Tag key={t}>{t}</Tag>)}
          </Space>
        </div>
      )}

      {keyPatterns && (keyPatterns as string[]).length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>关键设计模式</Text>
          <Space size={6} wrap>
            {(keyPatterns as string[]).map((p) => <Tag key={p}>{p}</Tag>)}
          </Space>
        </div>
      )}

      {hotSpots && (hotSpots as string[]).length > 0 && (
        <Alert
          message={<Text strong>架构热点问题</Text>}
          description={
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {(hotSpots as string[]).map((h, i) => <li key={i} style={{ fontSize: 13 }}>{h}</li>)}
            </ul>
          }
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}

      {summary && (
        <Alert
          message={<Text strong>LLM 架构评估</Text>}
          description={<Paragraph style={{ margin: 0, fontSize: 13, color: '#6b7280' }}>{(summary as string).slice(0, 600)}{(summary as string).length > 600 ? '...' : ''}</Paragraph>}
          type="info"
          showIcon
        />
      )}
    </div>
  );
}

// ─── 优化建议结果 ─────────────────────────────────────────────────────────────

function SuggestionPanel({ result }: { result?: Record<string, unknown> }) {
  if (!result) return <Text type="secondary">暂无数据</Text>;

  const { suggestions = [], total = 0, high_priority = 0, medium_priority = 0, low_priority = 0, llm_powered } = result as Record<string, unknown>;

  const priorityColor: Record<string, string> = {
    high: RISK_COLOR.high,
    medium: RISK_COLOR.medium,
    low: RISK_COLOR.low,
  };

  const typeColor: Record<string, string> = {
    security: RISK_COLOR.high,
    performance: RISK_COLOR.medium,
    dependency: '#8b5cf6',
    architecture: '#3b82f6',
    quality: '#10b981',
  };

  return (
    <div>
      <Row gutter={[8, 8]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>建议总数</Text>} value={total} valueStyle={{ fontSize: 22, fontWeight: 600 }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>高优</Text>} value={high_priority as number} valueStyle={{ fontSize: 22, fontWeight: 600, color: RISK_COLOR.high }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>中优</Text>} value={medium_priority as number} valueStyle={{ fontSize: 22, fontWeight: 600, color: RISK_COLOR.medium }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title={<Text type="secondary" style={{ fontSize: 11 }}>低优</Text>} value={low_priority as number} valueStyle={{ fontSize: 22, fontWeight: 600, color: RISK_COLOR.low }} />
          </Card>
        </Col>
      </Row>

      {llm_powered && (
        <Tag color="processing" style={{ marginBottom: 16 }}>由 AI 驱动</Tag>
      )}

      <List
        size="small"
        dataSource={suggestions as Array<Record<string, unknown>>}
        renderItem={(item, idx) => (
          <List.Item style={{ padding: '10px 0', borderBottom: '1px solid #f3f4f6' }}>
            <div style={{ width: '100%' }}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }} size="middle">
                <Space size={8}>
                  <span style={{
                    display: 'inline-block',
                    width: 24,
                    height: 24,
                    borderRadius: '50%',
                    background: `${typeColor[item.category as string] || '#6b7280'}20`,
                    color: typeColor[item.category as string] || '#6b7280',
                    textAlign: 'center',
                    lineHeight: '24px',
                    fontSize: 12,
                    fontWeight: 600,
                  }}>
                    {idx + 1}
                  </span>
                  <Text strong style={{ fontSize: 13 }}>{item.title as string}</Text>
                </Space>
                <Space size={6}>
                  <Tag style={{ border: 'none', color: priorityColor[item.priority as string] || '#6b7280', background: `${priorityColor[item.priority as string] || '#6b7280'}18` }}>
                    {item.priority as string}
                  </Tag>
                  <Tag style={{ border: 'none', color: '#6b7280', background: '#f3f4f6' }}>{item.category as string}</Tag>
                </Space>
              </Space>
              {item.description && (
                <Paragraph type="secondary" style={{ margin: '6px 0 0 32px', fontSize: 12 }}>
                  {item.description as string}
                </Paragraph>
              )}
            </div>
          </List.Item>
        )}
      />
    </div>
  );
}

// ─── LangSmith 追踪信息 ───────────────────────────────────────────────────────

function LangSmithPanel({ info }: { info?: LangSmithTraceInfo | null }) {
  if (!info) {
    return (
      <Alert
        message="LangSmith 追踪未启用"
        description="如需查看 AI 调用追踪详情，请在环境变量中配置 LANGSMITH_API_KEY 并重启后端服务。"
        type="info"
        showIcon
      />
    );
  }

  const agentColors: Record<string, string> = {
    architecture: '#3b82f6',
    quality: '#10b981',
    dependency: '#8b5cf6',
    suggestion: '#f59e0b',
    tech_stack: '#06b6d4',
  };

  return (
    <div>
      <Row gutter={[8, 8]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11 }}>LLM 运行次数</Text>}
              value={info.total_runs}
              valueStyle={{ fontSize: 24, fontWeight: 600 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11 }}>总 Tokens</Text>}
              value={info.total_tokens.toLocaleString()}
              valueStyle={{ fontSize: 24, fontWeight: 600, color: '#3b82f6' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11 }}>费用 (USD)</Text>}
              value={`$${info.total_cost_usd.toFixed(4)}`}
              valueStyle={{ fontSize: 24, fontWeight: 600, color: '#f59e0b' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11 }}>总耗时</Text>}
              value={info.total_duration_ms ? `${(info.total_duration_ms / 1000).toFixed(1)}s` : '-'}
              valueStyle={{ fontSize: 24, fontWeight: 600, color: '#8b5cf6' }}
            />
          </Card>
        </Col>
      </Row>

      <Card size="small" title={<Text style={{ fontSize: 13, fontWeight: 500 }}>Token 消耗明细</Text>} style={{ marginBottom: 16 }} styles={{ body: { padding: '12px 16px' } }}>
        <Row gutter={[8, 8]}>
          <Col span={8} style={{ textAlign: 'center' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>Prompt</Text>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{(info.total_prompt_tokens || 0).toLocaleString()}</div>
          </Col>
          <Col span={8} style={{ textAlign: 'center' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>Completion</Text>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{(info.total_completion_tokens || 0).toLocaleString()}</div>
          </Col>
          <Col span={8} style={{ textAlign: 'center' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>总费用</Text>
            <div style={{ fontSize: 15, fontWeight: 600, color: '#f59e0b' }}>${(info.total_cost_usd || 0).toFixed(6)}</div>
          </Col>
        </Row>
      </Card>

      {info.agents && info.agents.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>本次分析 Agent</Text>
          <Space size={8} wrap>
            {info.agents.map((agent) => (
              <Tag
                key={agent}
                style={{
                  border: 'none',
                  color: agentColors[agent] || '#6b7280',
                  background: `${agentColors[agent] || '#6b7280'}18`,
                }}
              >
                {agent}
              </Tag>
            ))}
          </Space>
        </div>
      )}

      {info.run_url && (
        <Button type="primary" icon={<LinkOutlined />} href={info.run_url} target="_blank">
          在 LangSmith 中查看完整追踪
        </Button>
      )}
      {info.trace_id && (
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Trace ID: <Text code copyable style={{ fontSize: 11 }}>{info.trace_id}</Text>
          </Text>
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function AnalysisDetailDrawer({ open, loading, data, onClose }: AnalysisDetailDrawerProps) {
  const history = data?.history;
  const user = data?.user;
  const resultData = history?.result_data as Record<string, unknown> | undefined;

  const tabItems = [
    {
      key: 'quality',
      label: (
        <Space size={4}>
          <TrophyOutlined />
          代码质量
        </Space>
      ),
      children: <QualityPanel result={resultData?.quality as Record<string, unknown>} />,
    },
    {
      key: 'dependency',
      label: (
        <Space size={4}>
          <AppstoreOutlined />
          依赖风险
        </Space>
      ),
      children: <DependencyPanel result={resultData?.dependency as Record<string, unknown>} />,
    },
    {
      key: 'architecture',
      label: (
        <Space size={4}>
          <ApartmentOutlined />
          架构分析
        </Space>
      ),
      children: <ArchitecturePanel result={resultData?.architecture as Record<string, unknown>} />,
    },
    {
      key: 'tech_stack',
      label: (
        <Space size={4}>
          <ForkOutlined />
          技术栈
        </Space>
      ),
      children: <TechStackPanel result={resultData?.tech_stack as Record<string, unknown>} />,
    },
    {
      key: 'suggestion',
      label: (
        <Space size={4}>
          <BulbOutlined />
          优化建议
        </Space>
      ),
      children: <SuggestionPanel result={resultData?.suggestion as Record<string, unknown>} />,
    },
    {
      key: 'langsmith',
      label: (
        <Space size={4}>
          <RadarChartOutlined />
          LangSmith
        </Space>
      ),
      children: <LangSmithPanel info={data?.langsmith ?? null} />,
    },
  ];

  const healthColor = (history?.health_score ?? 0) >= 85 ? SCORE_COLOR.excellent : (history?.health_score ?? 0) >= 60 ? SCORE_COLOR.warning : SCORE_COLOR.danger;

  return (
    <Drawer
      title={
        <Space size={6}>
          <EyeOutlined />
          <span>分析详情</span>
        </Space>
      }
      placement="right"
      width={680}
      open={open}
      onClose={onClose}
      styles={{ body: { padding: 0 } }}
    >
      <Spin spinning={loading} tip="加载中...">
        {data && history && (
          <div>
            {/* 基本信息区 */}
            <div style={{ padding: '20px 24px', borderBottom: '1px solid #f0f0f0' }}>
              <Row gutter={[16, 12]}>
                <Col flex="auto">
                  <div>
                    <Title level={5} style={{ margin: 0, fontWeight: 600 }}>
                      <LinkOutlined style={{ marginRight: 6, color: '#6b7280' }} />
                      <a href={history.repo_url} target="_blank" rel="noopener noreferrer">
                        {history.repo_url}
                      </a>
                    </Title>
                    <Space style={{ marginTop: 6 }} size="middle">
                      <Tag icon={<ForkOutlined />} style={{ border: 'none', color: '#6b7280', background: '#f5f5f5' }}>
                        {history.branch || 'main'}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        <ClockCircleOutlined style={{ marginRight: 4 }} />
                        {new Date(history.created_at).toLocaleString('zh-CN')}
                      </Text>
                    </Space>
                  </div>
                </Col>
                <Col>
                  <Space size={24}>
                    <div style={{ textAlign: 'center' }}>
                      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>健康分</Text>
                      <Progress
                        type="circle"
                        percent={history.health_score ?? 0}
                        size={56}
                        strokeColor={healthColor}
                        format={(p) => <span style={{ fontSize: 13, fontWeight: 600, color: healthColor }}>{p}</span>}
                      />
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>质量评分</Text>
                      <div style={{ marginTop: 8 }}><QualityScoreBadge score={history.quality_score} /></div>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>风险等级</Text>
                      <div style={{ marginTop: 8 }}><RiskBadge risk_level={history.risk_level} /></div>
                    </div>
                  </Space>
                </Col>
              </Row>
            </div>

            {/* 用户信息 */}
            {user && (
              <div style={{ padding: '12px 24px', background: '#fafafa', borderBottom: '1px solid #f0f0f0' }}>
                <Space>
                  <Avatar src={user.avatar_url} icon={<UserOutlined />} style={{ background: '#3b82f6' }} />
                  <div>
                    <Text strong style={{ fontSize: 14 }}>{user.login}</Text>
                    {user.name && <Text type="secondary" style={{ marginLeft: 6 }}>({user.name})</Text>}
                    <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
                      <StarOutlined style={{ marginRight: 3 }} />{user.followers}
                      <ForkOutlined style={{ marginLeft: 10, marginRight: 3 }} />{user.public_repos}
                    </Text>
                  </div>
                </Space>
              </div>
            )}

            {/* Agent 结果 Tab 区 */}
            <div style={{ padding: '16px 24px' }}>
              <Tabs
                defaultActiveKey="quality"
                items={tabItems}
                size="small"
                style={{ minHeight: 400 }}
              />
            </div>
          </div>
        )}
      </Spin>
    </Drawer>
  );
}
