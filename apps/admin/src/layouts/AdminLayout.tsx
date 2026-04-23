import React, { useState } from 'react';
import { Link, useLocation, Outlet } from 'umi';
import { Layout, Menu, Button, Dropdown, Avatar, Space, Typography, ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { MenuProps } from 'antd';
import {
  DashboardOutlined,
  UserOutlined,
  AuditOutlined,
  SettingOutlined,
  BellOutlined,
  QuestionCircleOutlined,
  BranchesOutlined,
  HistoryOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';

dayjs.locale('zh-cn');

const lightTheme: React.ComponentProps<typeof ConfigProvider>['theme'] = {
  token: {
    colorPrimary: '#3b82f6',
    colorBgLayout: '#f5f5f5',
    colorBgContainer: '#ffffff',
    colorTextBase: '#1a1a1a',
    colorTextSecondary: '#6b7280',
    colorBorder: '#e5e7eb',
    colorBorderSecondary: '#f3f4f6',
    borderRadius: 8,
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  components: {
    Layout: {
      siderBg: '#ffffff',
      headerBg: '#ffffff',
      bodyBg: '#f5f5f5',
    },
    Menu: {
      itemBg: 'transparent',
      itemSelectedBg: '#eff6ff',
      itemSelectedColor: '#3b82f6',
      itemHoverBg: '#f9fafb',
    },
    Card: {
      colorBgContainer: '#ffffff',
    },
  },
};

const { Sider, Content, Header } = Layout;
const { Text } = Typography;

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: <Link to="/dashboard">全局概览</Link> },
  { key: '/analysis-history', icon: <HistoryOutlined />, label: <Link to="/analysis-history">分析记录</Link> },
  { key: '/users', icon: <UserOutlined />, label: <Link to="/users">用户管理</Link> },
  { key: '/audit', icon: <AuditOutlined />, label: <Link to="/audit">分析审计</Link> },
  { key: '/settings', icon: <SettingOutlined />, label: <Link to="/settings">系统设置</Link> },
];

const userMenuItems: MenuProps['items'] = [
  { key: 'profile', label: '个人中心' },
  { key: 'settings', label: '账户设置' },
  { type: 'divider' },
  { key: 'logout', label: '退出登录', danger: true },
];

function AdminLayout() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <ConfigProvider theme={lightTheme} locale={zhCN}>
      <AntApp>
        <Layout style={{ minHeight: '100vh' }}>
          <Sider
            width={220}
            collapsible
            collapsed={collapsed}
            onCollapse={setCollapsed}
            style={{
              background: '#ffffff',
              boxShadow: '1px 0 0 #e5e7eb',
              position: 'fixed',
              left: 0,
              top: 0,
              bottom: 0,
              zIndex: 100,
              borderRight: '1px solid #e5e7eb',
            }}
          >
            {/* Logo 区域 */}
            <div
              style={{
                height: 64,
                display: 'flex',
                alignItems: 'center',
                justifyContent: collapsed ? 'center' : 'flex-start',
                padding: collapsed ? 0 : '0 20px',
                borderBottom: '1px solid #f3f4f6',
                cursor: 'pointer',
              }}
            >
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 8,
                  background: '#3b82f6',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <BranchesOutlined style={{ color: '#fff', fontSize: 16 }} />
              </div>
              {!collapsed && (
                <span
                  style={{
                    marginLeft: 10,
                    color: '#1a1a1a',
                    fontSize: 16,
                    fontWeight: 700,
                    letterSpacing: '-0.01em',
                  }}
                >
                  GitIntel
                </span>
              )}
            </div>

            {/* 菜单 */}
            <Menu
              mode="inline"
              selectedKeys={[location.pathname]}
              defaultSelectedKeys={['/dashboard']}
              items={menuItems}
              style={{
                background: 'transparent',
                border: 'none',
                marginTop: 8,
              }}
              theme="light"
            />

            {/* 底部信息 */}
            {!collapsed && (
              <div
                style={{
                  position: 'absolute',
                  bottom: 0,
                  left: 0,
                  right: 0,
                  padding: '16px 20px',
                  borderTop: '1px solid #f3f4f6',
                }}
              >
                <Space direction="vertical" size={2}>
                  <Text style={{ color: '#9ca3af', fontSize: 11 }}>
                    GitIntel Admin v1.0.0
                  </Text>
                  <Text style={{ color: '#d1d5db', fontSize: 10 }}>
                    Powered by AI
                  </Text>
                </Space>
              </div>
            )}
          </Sider>

          <Layout style={{ marginLeft: collapsed ? 64 : 220, transition: 'margin-left 0.2s' }}>
            {/* 顶部导航栏 */}
            <Header
              style={{
                background: '#ffffff',
                padding: '0 24px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                position: 'sticky',
                top: 0,
                zIndex: 99,
                height: 60,
                borderBottom: '1px solid #f3f4f6',
              }}
            >
              <Space size={12}>
                <Button type="text" icon={<QuestionCircleOutlined />} />
                <Button type="text" icon={<BellOutlined />} badge={{ count: 3 }} />
                <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
                  <Space style={{ cursor: 'pointer' }}>
                    <Avatar size={32} style={{ background: '#3b82f6' }}>
                      A
                    </Avatar>
                    <Text strong style={{ fontSize: 14 }}>Admin</Text>
                  </Space>
                </Dropdown>
              </Space>
            </Header>

            {/* 内容区域 */}
            <Content
              style={{
                padding: 24,
                background: '#f5f5f5',
                minHeight: 'calc(100vh - 60px)',
              }}
            >
              <Outlet />
            </Content>
          </Layout>
        </Layout>
      </AntApp>
    </ConfigProvider>
  );
}

export default AdminLayout;
export { AdminLayout };
