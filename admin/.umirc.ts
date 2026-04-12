import { defineConfig } from 'umi';
import { resolve } from 'path';

export default defineConfig({
  npmClient: 'pnpm',

  routes: [
    {
      path: '/',
      component: '@/layouts/AdminLayout',
      routes: [
        { path: '/', redirect: '/dashboard' },
        { path: '/dashboard', component: '@/pages/dashboard' },
        { path: '/users', component: '@/pages/users' },
        { path: '/audit', component: '@/pages/audit' },
        { path: '/settings', component: '@/pages/settings' },
      ],
    },
  ],

  alias: {
    '@': resolve(__dirname, 'src'),
  },

  styles: ['@/src/tailwind.css'],

  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
});
