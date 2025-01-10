import { useState, useRef, useEffect } from 'react';
import { Sun, Moon, Eye, Computer, Settings, Sparkles } from 'lucide-react';
import type { Theme } from '../types/theme';

interface ThemeMenuProps {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  currentThemeStyle: {
    text: string;
    button: string;
    activeButton: string;
    card: string;
    border: string;
    hover: string;
  };
}

const themeItems = [
  { value: 'light', label: '浅色模式', icon: Sun },
  { value: 'dark', label: '深色模式', icon: Moon },
  { value: 'eyecare', label: '护眼模式', icon: Eye },
  { value: 'system', label: '跟随系统', icon: Computer },
  { value: 'newyear', label: '新年', icon: Sparkles }, // 添加新年主题
] as const;

export function ThemeMenu({
  theme,
  setTheme,
  currentThemeStyle,
}: ThemeMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const getCurrentIcon = () => {
    const currentItem = themeItems.find((item) => item.value === theme);
    const Icon = currentItem?.icon || Settings;
    return <Icon className='w-5 h-5' />;
  };

  return (
    <div className='relative' ref={menuRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`p-2 rounded-lg ${
          theme === 'system'
            ? currentThemeStyle.activeButton
            : currentThemeStyle.button
        } ${currentThemeStyle.text} transition-colors duration-200`}
        aria-label='切换主题'
      >
        {getCurrentIcon()}
      </button>

      {isOpen && (
        <div
          className={`absolute right-0 top-full mt-2 w-36 rounded-lg ${currentThemeStyle.card} 
          ${currentThemeStyle.border} border backdrop-blur-sm shadow-lg z-50`}
        >
          {themeItems.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              onClick={() => {
                setTheme(value as Theme);
                setIsOpen(false);
              }}
              className={`w-full px-3 py-2 flex items-center gap-2 ${
                currentThemeStyle.text
              } 
                ${currentThemeStyle.hover} ${
                theme === value ? 'font-medium' : ''
              } 
                first:rounded-t-lg last:rounded-b-lg transition-colors duration-200`}
            >
              <Icon className='w-4 h-4' />
              <span>{label}</span>
              {theme === value && (
                <span className='ml-auto w-1 h-1 rounded-full bg-current' />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default ThemeMenu;
