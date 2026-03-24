import React, { useState, useEffect, useRef } from 'react';

interface LabelEditorProps {
    initialValue: string;
    onSave: (value: string) => void;
    onCancel: () => void;
}

export const LabelEditor: React.FC<LabelEditorProps> = ({ initialValue, onSave, onCancel }) => {
    const [value, setValue] = useState(initialValue);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        // Focus the input when the component mounts
        inputRef.current?.focus();
        // Select all text
        inputRef.current?.select();
    }, []);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            onSave(value);
        } else if (e.key === 'Escape') {
            onCancel();
        }
    };

    return (
        <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            zIndex: 1000,
            background: 'var(--vscode-editor-background)',
            border: '1px solid var(--vscode-input-border)',
            borderRadius: '4px',
            padding: '4px',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)'
        }}>
            <input
                ref={inputRef}
                type="text"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={handleKeyDown}
                onBlur={onCancel}
                style={{
                    background: 'var(--vscode-input-background)',
                    color: 'var(--vscode-input-foreground)',
                    border: '1px solid var(--vscode-input-border)',
                    borderRadius: '2px',
                    padding: '4px 8px',
                    fontSize: '11px',
                    fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
                    width: '150px',
                    outline: 'none'
                }}
            />
        </div>
    );
}; 