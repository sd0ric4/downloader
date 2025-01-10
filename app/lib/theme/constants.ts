import type { Theme, ThemeStyle } from '~/types/theme';

export const getSystemTheme = (): 'light' | 'dark' => {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
};

export const themeStyles: Record<Theme, ThemeStyle> = {
  light: {
    background: 'bg-gradient-to-b from-gray-100 to-white',
    text: 'text-gray-900',
    subtext: 'text-gray-600',
    card: 'bg-white/80',
    border: 'border-gray-200',
    hover: 'hover:bg-gray-100',
    button: 'bg-gray-100 hover:bg-gray-200',
    buttonSecondary: 'bg-gray-100 hover:bg-gray-200',
    activeButton: 'bg-blue-500 text-white hover:bg-blue-600 transition-colors',
    input: 'bg-white border-gray-200 focus:border-blue-500',
    alert: {
      success: 'bg-green-50 text-green-700 border-green-200',
      error: 'bg-red-50 text-red-700 border-red-200',
    },
  },
  dark: {
    background: 'bg-gradient-to-b from-gray-900 to-black',
    text: 'text-white',
    subtext: 'text-gray-400',
    card: 'bg-gray-800/30',
    input: 'bg-gray-800 border-gray-700 focus:border-blue-500',
    border: 'border-gray-700/50',
    hover: 'hover:bg-gray-700/50',
    button: 'bg-gray-800/80 hover:bg-gray-700/80',
    buttonSecondary: 'bg-gray-800/80 hover:bg-gray-700/80',
    activeButton: 'bg-blue-600/90 hover:bg-blue-500/90',
    alert: {
      success: 'bg-green-900/20 text-green-300 border-green-800/50',
      error: 'bg-red-900/20 text-red-300 border-red-800/50',
    },
  },
  eyecare: {
    background: 'bg-gradient-to-b from-amber-50 to-amber-100',
    text: 'text-gray-800',
    subtext: 'text-gray-600',
    card: 'bg-yellow-50/80',
    border: 'border-yellow-200/50',
    hover: 'hover:bg-yellow-100/50',
    button: 'bg-yellow-100 hover:bg-yellow-200',
    input: 'bg-yellow-50 border-yellow-200 focus:border-yellow-500',
    buttonSecondary: 'bg-yellow-100 hover:bg-yellow-200',
    activeButton: 'bg-yellow-600 text-white hover:bg-yellow-500',
    alert: {
      success: 'bg-emerald-50/90 text-emerald-600 border-emerald-200/50',
      error: 'bg-rose-50/90 text-rose-600 border-rose-200/50',
    },
  },
  system: {
    get background() {
      return themeStyles[getSystemTheme()].background;
    },
    get text() {
      return themeStyles[getSystemTheme()].text;
    },
    get subtext() {
      return themeStyles[getSystemTheme()].subtext;
    },
    get card() {
      return themeStyles[getSystemTheme()].card;
    },
    get border() {
      return themeStyles[getSystemTheme()].border;
    },
    get hover() {
      return themeStyles[getSystemTheme()].hover;
    },
    get button() {
      return themeStyles[getSystemTheme()].button;
    },
    get buttonSecondary() {
      return themeStyles[getSystemTheme()].buttonSecondary;
    },
    get activeButton() {
      return themeStyles[getSystemTheme()].activeButton;
    },
    get alert() {
      return themeStyles[getSystemTheme()].alert;
    },
    get input() {
      return themeStyles[getSystemTheme()].input;
    },
  },
  newyear: {
    background: 'bg-red-50',
    text: 'text-red-900',
    subtext: 'text-red-700',
    border: 'border-red-200',
    card: 'bg-white/50',
    button: 'bg-red-100 hover:bg-red-200',
    buttonSecondary: 'bg-red-100 hover:bg-red-200',
    activeButton: 'bg-red-500 hover:bg-red-600 text-white',
    input: 'bg-white border-red-200 focus:border-red-500',
    hover: 'hover:bg-red-100',
    alert: {
      success: 'bg-emerald-50/90 text-emerald-600 border-emerald-200/50',
      error: 'bg-rose-50/90 text-rose-600 border-rose-200/50',
    },
  },
};
