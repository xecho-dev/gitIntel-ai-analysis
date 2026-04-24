/**
 * Umi route-level auth wrapper.
 * Applied via `wrappers: ['@/wrappers/auth']` in .umirc.ts.
 * Wraps every authenticated page — if not logged in, redirects to /login.
 */
import React, { useEffect, useState } from 'react';
import { history } from 'umi';
import { Spin, Result, Button } from 'antd';
import { adminMe } from '@/services/admin';

export default function AuthWrapper(props: { children?: React.ReactNode } & Record<string, unknown>) {
  const { children } = props;
  const [authState, setAuthState] = useState<'loading' | 'authenticated' | 'unauthenticated'>('loading');

  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    if (!token) {
      setAuthState('unauthenticated');
      return;
    }

    adminMe()
      .then((user) => {
        localStorage.setItem('admin_user', JSON.stringify(user));
        setAuthState('authenticated');
      })
      .catch(() => {
        localStorage.removeItem('admin_token');
        localStorage.removeItem('admin_user');
        localStorage.removeItem('admin_token_expires_at');
        setAuthState('unauthenticated');
      });
  }, []);

  useEffect(() => {
    if (authState === 'unauthenticated') {
      history.replace('/login');
    }
  }, [authState]);

  if (authState === 'loading') {
    return (
      <div
        style={{
          height: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#f5f5f5',
        }}
      >
        <Spin size="large" tip="验证登录状态..." />
      </div>
    );
  }

  if (authState === 'unauthenticated') {
    return (
      <Result
        status="403"
        title="未登录"
        subTitle="请先登录以访问管理后台"
        extra={
          <Button type="primary" onClick={() => history.push('/login')}>
            前往登录
          </Button>
        }
      />
    );
  }

  return <>{children}</>;
}
