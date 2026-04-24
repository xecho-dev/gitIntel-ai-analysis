import { defineConfig } from 'umi';
import { resolve } from 'path';

export default defineConfig({
  npmClient: 'pnpm',

  routes: [
    { path: '/login', component: '@/pages/login' },
    {
      path: '/',
      component: '@/layouts/AdminLayout',
      routes: [
        { path: '/', redirect: '/dashboard' },
        { path: '/dashboard', component: '@/pages/dashboard' },
        { path: '/analysis-history', component: '@/pages/analysis-history' },
        { path: '/users', component: '@/pages/users' },
        { path: '/audit', component: '@/pages/audit' },
        { path: '/settings', component: '@/pages/settings' },
      ],
    },
  ],

  alias: {
    '@': resolve(__dirname, 'src'),
  },

  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
});
