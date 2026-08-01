/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from 'react';

const MotionPreferenceContext = createContext(true);

export interface MotionPreferenceProviderProps {
  children: ReactNode;
  motionEnabled: boolean;
}

export function MotionPreferenceProvider({ children, motionEnabled }: MotionPreferenceProviderProps) {
  return (
    <MotionPreferenceContext.Provider value={motionEnabled}>
      {children}
    </MotionPreferenceContext.Provider>
  );
}

export function useReducedMotion(): boolean {
  return !useContext(MotionPreferenceContext);
}
