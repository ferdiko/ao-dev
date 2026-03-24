import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';

interface DocumentContextValue {
  // Map from document key (hash of first N chars) to opened file path
  openedPaths: Map<string, string>;
  // Mark a document as opened with its path
  setDocumentOpened: (key: string, path: string) => void;
}

const DocumentContext = createContext<DocumentContextValue | null>(null);

/**
 * Generate a short key from base64 data for tracking opened documents.
 * Uses first 32 chars which should be unique enough to identify documents.
 */
export function getDocumentKey(base64Data: string): string {
  return base64Data.substring(0, 32);
}

export const DocumentContextProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [openedPaths, setOpenedPaths] = useState<Map<string, string>>(new Map());

  const setDocumentOpened = useCallback((key: string, path: string) => {
    setOpenedPaths(prev => {
      const next = new Map(prev);
      next.set(key, path);
      return next;
    });
  }, []);

  return (
    <DocumentContext.Provider value={{ openedPaths, setDocumentOpened }}>
      {children}
    </DocumentContext.Provider>
  );
};

export const useDocumentContext = () => {
  const context = useContext(DocumentContext);
  // Return a default value if used outside provider (e.g., in web app)
  if (!context) {
    return { openedPaths: new Map<string, string>(), setDocumentOpened: () => {} };
  }
  return context;
};
