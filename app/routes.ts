import { type RouteConfig, index, route } from '@react-router/dev/routes';

export default [
  index('routes/home.tsx'),
  route('structure', './view/protocalStructure.tsx'),
  route('progress', './view/progress.tsx'),
] satisfies RouteConfig;
