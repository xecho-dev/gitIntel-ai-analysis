import React, { useState } from 'react';
import { Link, useLocation, Outlet } from 'umi';
import { Layout, Menu, Button, Dropdown, Avatar, Space, Typography } from 'antd';
import type { MenuProps } from 'antd';
import {
  DashboardOutlined,
  UserOutlined,
  AuditOutlined,
  SettingOutlined,
  BellOutlined,
  QuestionCircleOutlined,
  GithubOutlined,
  BranchesOutlined,
} from '@ant-design/icons';

const { Sider, Content, Header } = Layout;
const { Text } = Typography;

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: <Link to="/dashboard">全局概览</Link> },
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
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={240}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        style={{
          background: '#001529',
          boxShadow: '2px 0 8px rgba(0,0,0,0.15)',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 100,
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
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            cursor: 'pointer',
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 6,
              background: 'linear-gradient(135deg, #1677ff 0%, #4096ff 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 2px 8px rgba(22,119,255,0.4)',
            }}
          >
            <BranchesOutlined style={{ color: '#fff', fontSize: 16 }} />
          </div>
          {!collapsed && (
            <span
              style={{
                marginLeft: 12,
                color: '#fff',
                fontSize: 16,
                fontWeight: 600,
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
            marginTop: 12,
          }}
          theme="dark"
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
              borderTop: '1px solid rgba(255,255,255,0.06)',
            }}
          >
            <Space direction="vertical" size={4}>
              <Text style={{ color: 'rgba(255,255,255,0.45)', fontSize: 11 }}>
                GitIntel Admin v1.0.0
              </Text>
              <Text style={{ color: 'rgba(255,255,255,0.25)', fontSize: 10 }}>
                Powered by AI
              </Text>
            </Space>
          </div>
        )}
      </Sider>

      <Layout style={{ marginLeft: collapsed ? 80 : 240, transition: 'margin-left 0.2s' }}>
        {/* 顶部导航栏 */}
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            boxShadow: '0 1px 4px rgba(0,21,41,0.08)',
            position: 'sticky',
            top: 0,
            zIndex: 99,
            height: 56,
          }}
        >
          <Space size={16}>
            <Button type="text" icon={<QuestionCircleOutlined />} />
            <Button type="text" icon={<BellOutlined />} badge={{ count: 3 }} />
            <Button type="text" icon={<GithubOutlined />} href="https://github.com" target="_blank" />
            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
              <Space style={{ cursor: 'pointer' }}>
                <Avatar size={32} style={{ background: '#1677ff' }}>
                  A
                </Avatar>
                <Text strong>Admin</Text>
              </Space>
            </Dropdown>
          </Space>
        </Header>

        {/* 内容区域 */}
        <Content
          style={{
            padding: 24,
            background: '#f5f5f5',
            minHeight: 'calc(100vh - 56px)',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

export default AdminLayout;
export { AdminLayout };
