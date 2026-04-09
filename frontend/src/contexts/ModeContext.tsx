import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';

export type AppMode = 'institutional' | 'retail';

interface ModeContextType {
  mode: AppMode;
  setMode: (m: AppMode) => void;
  isRetail: boolean;
  isInstitutional: boolean;
}

const ModeContext = createContext<ModeContextType>({
  mode: 'institutional',
  setMode: () => {},
  isRetail: false,
  isInstitutional: true,
});

export const ModeProvider = ({ children }: { children: ReactNode }) => {
  const [mode, setModeState] = useState<AppMode>(() => {
    return (localStorage.getItem('cs_mode') as AppMode) || 'institutional';
  });

  const setMode = (m: AppMode) => {
    localStorage.setItem('cs_mode', m);
    setModeState(m);
  };

  return (
    <ModeContext.Provider value={{
      mode,
      setMode,
      isRetail: mode === 'retail',
      isInstitutional: mode === 'institutional',
    }}>
      {children}
    </ModeContext.Provider>
  );
};

export const useMode = () => useContext(ModeContext);
