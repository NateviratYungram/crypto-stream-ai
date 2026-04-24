import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';

export type AppMode = 'institutional' | 'retail';
export type ThemeMode = 'dark' | 'light';

interface ModeContextType {
  mode: AppMode;
  setMode: (m: AppMode) => void;
  theme: ThemeMode;
  toggleTheme: () => void;
  isRetail: boolean;
  isInstitutional: boolean;
}

export const ModeContext = createContext<ModeContextType>({
  mode: 'institutional',
  setMode: () => {},
  theme: 'dark',
  toggleTheme: () => {},
  isRetail: false,
  isInstitutional: true,
});

export const ModeProvider = ({ children }: { children: ReactNode }) => {
  const [mode] = useState<AppMode>('retail');

  const [theme, setThemeState] = useState<ThemeMode>(() => {
    return (localStorage.getItem('cs_theme') as ThemeMode) || 'dark';
  });

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove('light', 'dark');
    root.classList.add(theme);
    localStorage.setItem('cs_theme', theme);
  }, [theme]);

  const setMode = (_m: AppMode) => {};

  const toggleTheme = () => {
    setThemeState(prev => prev === 'dark' ? 'light' : 'dark');
  };

  return (
    <ModeContext.Provider value={{
      mode,
      setMode,
      theme,
      toggleTheme,
      isRetail: mode === 'retail',
      isInstitutional: mode === 'institutional',
    }}>
      {children}
    </ModeContext.Provider>
  );
};

export const useMode = () => useContext(ModeContext);
