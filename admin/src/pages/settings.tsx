import { Card, Form, Input, Switch, Button, Space, Divider, Row, Col, Typography, Tabs, message, Alert } from 'antd';
import {
  SaveOutlined,
  GlobalOutlined,
  LockOutlined,
  BellOutlined,
  RobotOutlined,
  DatabaseOutlined,
  ApiOutlined,
} from '@ant-design/icons';

const { Title, Text } = Typography;

export default function Settings() {
  const [form] = Form.useForm();

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      console.log('保存设置:', values);
      message.success('设置已保存');
    } catch (error) {
      console.error('验证失败:', error);
    }
  };

  const items = [
    {
      key: 'basic',
      label: (
        <span>
          <GlobalOutlined />
          基础配置
        </span>
      ),
      children: (
        <Card bordered={false}>
          <Form form={form} layout="vertical" initialValues={{
            systemName: 'GitIntel Admin',
            apiBaseUrl: 'http://localhost:8000',
            timeout: 30,
          }}>
            <Row gutter={24}>
              <Col span={12}>
                <Form.Item
                  name="systemName"
                  label="系统名称"
                  rules={[{ required: true, message: '请输入系统名称' }]}
                >
                  <Input placeholder="GitIntel Admin" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="apiBaseUrl"
                  label="API 基础地址"
                  rules={[{ required: true, message: '请输入 API 地址' }]}
                >
                  <Input placeholder="http://localhost:8000" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="timeout" label="请求超时时间（秒）">
                  <Input type="number" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="maxRetries" label="最大重试次数">
                  <Input type="number" />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Card>
      ),
    },
    {
      key: 'features',
      label: (
        <span>
          <RobotOutlined />
          功能开关
        </span>
      ),
      children: (
        <Card bordered={false}>
          <Form layout="vertical">
            <Form.Item
              label={
                <Space>
                  <Text>启用分析功能</Text>
                  <Text type="secondary">(允许用户创建新的代码分析任务)</Text>
                </Space>
              }
            >
              <Switch defaultChecked />
            </Form.Item>
            <Divider />
            <Form.Item
              label={
                <Space>
                  <Text>启用通知</Text>
                  <Text type="secondary">(分析完成时发送邮件通知)</Text>
                </Space>
              }
            >
              <Switch defaultChecked />
            </Form.Item>
            <Divider />
            <Form.Item
              label={
                <Space>
                  <Text>启用审计日志</Text>
                  <Text type="secondary">(记录所有用户操作)</Text>
                </Space>
              }
            >
              <Switch defaultChecked />
            </Form.Item>
            <Divider />
            <Form.Item
              label={
                <Space>
                  <Text>调试模式</Text>
                  <Text type="secondary">(显示详细的调试信息)</Text>
                </Space>
              }
            >
              <Switch />
            </Form.Item>
          </Form>
        </Card>
      ),
    },
    {
      key: 'security',
      label: (
        <span>
          <LockOutlined />
          安全设置
        </span>
      ),
      children: (
        <Card bordered={false}>
          <Form layout="vertical">
            <Alert
              message="安全建议"
              description="建议定期更换密码，启用双因素认证，并限制 API 访问频率。"
              type="info"
              showIcon
              style={{ marginBottom: 24 }}
            />
            <Row gutter={24}>
              <Col span={12}>
                <Form.Item label="会话超时（分钟）">
                  <Input type="number" placeholder="60" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="密码最小长度">
                  <Input type="number" placeholder="8" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label="启用双因素认证">
              <Space direction="vertical">
                <Switch />
                <Text type="secondary">启用后，用户登录时需要输入手机验证码</Text>
              </Space>
            </Form.Item>
          </Form>
        </Card>
      ),
    },
    {
      key: 'notifications',
      label: (
        <span>
          <BellOutlined />
          通知设置
        </span>
      ),
      children: (
        <Card bordered={false}>
          <Form layout="vertical">
            <Form.Item label="邮件通知">
              <Switch defaultChecked />
            </Form.Item>
            <Form.Item label="SMTP 服务器">
              <Input placeholder="smtp.example.com" />
            </Form.Item>
            <Row gutter={24}>
              <Col span={12}>
                <Form.Item label="邮箱地址">
                  <Input placeholder="noreply@example.com" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="邮箱密码">
                  <Input.Password placeholder="••••••••" />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Card>
      ),
    },
    {
      key: 'database',
      label: (
        <span>
          <DatabaseOutlined />
          数据库
        </span>
      ),
      children: (
        <Card bordered={false}>
          <Alert
            message="数据库配置"
            description="修改数据库配置前请确保服务已停止，避免数据丢失。"
            type="warning"
            showIcon
            style={{ marginBottom: 24 }}
          />
          <Form layout="vertical">
            <Row gutter={24}>
              <Col span={12}>
                <Form.Item label="数据库类型">
                  <Input value="PostgreSQL" disabled />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="连接地址">
                  <Input placeholder="localhost:5432" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="数据库名称">
                  <Input placeholder="gitintel" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="连接池大小">
                  <Input type="number" placeholder="10" />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Card>
      ),
    },
    {
      key: 'api',
      label: (
        <span>
          <ApiOutlined />
          API 配置
        </span>
      ),
      children: (
        <Card bordered={false}>
          <Form layout="vertical">
            <Row gutter={24}>
              <Col span={12}>
                <Form.Item label="AI 模型">
                  <Input placeholder="gpt-4" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="API Key">
                  <Input.Password placeholder="sk-..." />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="最大 Token 数">
                  <Input type="number" placeholder="4000" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="Temperature">
                  <Input type="number" placeholder="0.7" step="0.1" />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Card>
      ),
    },
  ];

  return (
    <div>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>系统设置</Title>
        <Text type="secondary">配置系统参数和功能选项</Text>
      </div>

      <Tabs
        tabPosition="left"
        style={{ minHeight: 600 }}
        items={items}
        tabBarStyle={{ width: 180 }}
      />

      <div style={{ marginTop: 24, textAlign: 'right' }}>
        <Space>
          <Button>重置</Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={handleSave}>
            保存设置
          </Button>
        </Space>
      </div>
    </div>
  );
}
