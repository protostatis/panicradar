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

export const useChartSync = () => {
  const context = useContext(ChartSyncContext);
  if (!context) {
    throw new Error('useChartSync must be used within a ChartSyncProvider');
  }
  return context;
};

export default ChartSyncContext;
