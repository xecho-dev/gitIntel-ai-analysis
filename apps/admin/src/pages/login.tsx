import React from 'react';
import { useNavigate } from 'umi';
import { LoginForm, ProFormText, ProConfigProvider } from '@ant-design/pro-components';
import { ConfigProvider, App as AntApp, message } from 'antd';
import { adminLogin } from '@/services/admin';
import zhCN from 'antd/locale/zh_CN';

const lightTheme: React.ComponentProps<typeof ConfigProvider>['theme'] = {
  token: {
    colorPrimary: '#3b82f6',
    borderRadius: 8,
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
};

interface LoginValues {
  username: string;
  password: string;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const [messageApi, contextHolder] = message.useMessage();

  const handleSubmit = async (values: LoginValues) => {
    try {
      const { username, password } = values;
      const res = await adminLogin(username, password);

      localStorage.setItem('admin_token', res.token);
      localStorage.setItem('admin_user', JSON.stringify(res.user));
      localStorage.setItem('admin_token_expires_at', res.expires_at);

      messageApi.success('登录成功，正在跳转...');
      setTimeout(() => navigate('/dashboard'), 500);
      return true;
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }; message?: string };
      const detail = error.response?.data?.detail || error.message || '登录失败，请检查用户名和密码';
      messageApi.error(detail);
      return false;
    }
  };

  return (
    <ProConfigProvider hashed={false}>
      <ConfigProvider theme={lightTheme} locale={zhCN}>
        <AntApp>
          {contextHolder}
          <div
            style={{
              background: '#f0f2f5',
              minHeight: '100vh',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <LoginForm
              title="GitIntel"
              subTitle="管理后台"
              onFinish={handleSubmit}
              logo={
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    background: '#3b82f6',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 20,
                    color: '#fff',
                    fontWeight: 700,
                  }}
                >
                  G
                </div>
              }
              actions={
                <span style={{ color: '#9ca3af', fontSize: 12 }}>
                  请使用管理员账号登录
                </span>
              }
            >
              <ProFormText
                name="username"
                fieldProps={{
                  size: 'large',
                  prefix: (
                    <span style={{ color: '#9ca3af' }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                        <circle cx="12" cy="7" r="4" />
                      </svg>
                    </span>
                  ),
                }}
                placeholder="请输入管理员账号"
                rules={[{ required: true, message: '请输入管理员账号' }]}
              />
              <ProFormText.Password
                name="password"
                fieldProps={{
                  size: 'large',
                  prefix: (
                    <span style={{ color: '#9ca3af' }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                      </svg>
                    </span>
                  ),
                }}
                placeholder="请输入密码"
                rules={[{ required: true, message: '请输入密码' }]}
              />
            </LoginForm>
          </div>
        </AntApp>
      </ConfigProvider>
    </ProConfigProvider>
  );
}
