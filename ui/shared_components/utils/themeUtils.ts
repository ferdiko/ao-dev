import { useState, useEffect } from 'react';

export function useIsVsCodeDarkTheme(initialValue = true) {
    const [isDarkTheme, setIsDarkTheme] = useState(initialValue);

    useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            const message = event.data;

            if (message.type === 'vscode-theme-change') {
                const isDark = message.payload.theme === 'vscode-dark';
                setIsDarkTheme(isDark);
            }
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    return isDarkTheme;
}
