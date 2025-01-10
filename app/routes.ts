import { type RouteConfig, index, route } from '@react-router/dev/routes';

export default [
  index('./view/ServerWebui.tsx'),
  route('client', './view/ClientWebui.tsx'),
] satisfies RouteConfig;
