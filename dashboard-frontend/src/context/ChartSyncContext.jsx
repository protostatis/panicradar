import { createContext, useContext, useState, useCallback } from 'react';

const ChartSyncContext = createContext(null);

export const ChartSyncProvider = ({ children }) => {
  const [activeDate, setActiveDate] = useState(null);

  const handleMouseMove = useCallback((e) => {
    if (e?.activeLabel) {
      setActiveDate(e.activeLabel);
    }
  }, []);

  const handleMouseLeave = useCallback(() => {
    setActiveDate(null);
  }, []);

  return (
    <ChartSyncContext.Provider value={{ activeDate, handleMouseMove, handleMouseLeave }}>
      {children}
    </ChartSyncContext.Provider>
  );
};

// Default no-op functions for when used outside provider
const defaultValue = {
  activeDate: null,
  handleMouseMove: () => {},
  handleMouseLeave: () => {},
};

export const useChartSync = () => {
  const context = useContext(ChartSyncContext);
  return context || defaultValue;
};

export default ChartSyncContext;
