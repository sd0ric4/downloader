import { createContext, useEffect, useMemo, useState } from 'react';
import { themeStyles } from '~/lib/theme/constants';
import type { Theme } from '~/types/theme';

type ThemeContextType = {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  currentTheme: typeof themeStyles.light;
  mounted: boolean;
};

export const ThemeContext = createContext<ThemeContextType | undefined>(
  undefined
);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    // 服务端返回系统主题
    if (typeof window === 'undefined') {
      return 'system';
    }
    return (localStorage.getItem('theme') as Theme) || 'system';
  });
  const [mounted, setMounted] = useState(false);

  // 使用 useMemo 缓存系统主题
  const systemTheme = useMemo(() => {
    if (typeof window === 'undefined') return 'light';
    return window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }, []);

  useEffect(() => {
    setMounted(true);
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (e: MediaQueryListEvent) => {
      if (theme === 'system') {
        document.documentElement.className = e.matches ? 'dark' : 'light';
      }
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, [theme]);

  useEffect(() => {
    if (mounted && theme) {
      localStorage.setItem('theme', theme);
      document.documentElement.className =
        theme === 'system' ? systemTheme : theme;
    }
  }, [theme, systemTheme, mounted]);

  const currentTheme =
    theme === 'system' ? themeStyles[systemTheme] : themeStyles[theme];

  return (
    <ThemeContext.Provider value={{ theme, setTheme, currentTheme, mounted }}>
      {children}
    </ThemeContext.Provider>
  );
}
