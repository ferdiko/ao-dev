import React from 'react';
import ReactDOM from 'react-dom';

interface NodePopoverProps {
    onAction: (action: string) => void;
    onMouseEnter: () => void;
    onMouseLeave: () => void;
    position?: 'above' | 'below' | 'left';
    top?: number;
    left?: number;
    isDarkTheme?: boolean;
}

export const NodePopover: React.FC<NodePopoverProps> = ({ 
    onAction, 
    onMouseEnter, 
    onMouseLeave,
    position = 'below', // Default to below
    top,
    left,
    isDarkTheme = false,
}) => {
    const popoverBg = isDarkTheme ? '#4d4d4d' : '#ffffff';
    const popoverBorder = isDarkTheme ? '#6b6b6b' : '#cccccc';
    const arrowColor = popoverBg;
    const textColor = isDarkTheme ? '#fff' : '#000';
    const hoverBg = isDarkTheme ? '#555' : '#f2f2f2';

    const actions = [
        // { id: 'editInput', label: 'Edit input' },
        // { id: 'editOutput', label: 'Edit output' },
        { id: 'editInput', label: 'Edit input / output' },
        { id: 'changeLabel', label: 'Change label' },
    ];

    const isLeft = position === 'left';

    const popoverStyle: React.CSSProperties = {
        position: 'fixed',
        top: top !== undefined ? (isLeft ? top : top + 4) : undefined,
        left: left !== undefined ? left : undefined,
        transform: isLeft ? 'translateX(-100%) translateY(-50%)' : 'translateX(-50%)',
        background: popoverBg,
        border: `1px solid ${popoverBorder}`,
        borderRadius: '6px',
        padding: '6px',
        minWidth: '120px',
        zIndex: 9999,
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
        // Animation properties
        opacity: 0,
        scale: '0.95',
        transformOrigin: isLeft ? 'right center' : 'top center',
        animation: isLeft ? 'popoverFadeInLeft 0.2s ease-out forwards' : 'popoverFadeIn 0.2s ease-out forwards',
    };

    const arrowStyle: React.CSSProperties = isLeft ? {
        position: 'absolute',
        top: '47.5%',
        right: '-5px',
        transform: 'translateY(-50%)',
        width: 0,
        height: 0,
        borderTop: '5px solid transparent',
        borderBottom: '5px solid transparent',
        borderLeft: `5px solid ${arrowColor}`,
        filter: `drop-shadow(1px 0 0 ${popoverBorder})`,
    } : {
        position: 'absolute',
        top: '-5px',
        left: '50%',
        transform: 'translateX(-50%)',
        width: 0,
        height: 0,
        borderLeft: '5px solid transparent',
        borderRight: '5px solid transparent',
        borderBottom: `5px solid ${arrowColor}`,
        filter: `drop-shadow(0 -1px 0 ${popoverBorder})`,
    };

    return ReactDOM.createPortal(
        <>
            {/* Add CSS animation keyframes */}
            <style>{`
                @keyframes popoverFadeIn {
                    0% {
                        opacity: 0;
                        transform: translateX(-50%) scale(0.95);
                    }
                    100% {
                        opacity: 1;
                        transform: translateX(-50%) scale(1);
                    }
                }
                @keyframes popoverFadeInLeft {
                    0% {
                        opacity: 0;
                        transform: translateX(-100%) translateY(-50%) scale(0.95);
                    }
                    100% {
                        opacity: 1;
                        transform: translateX(-100%) translateY(-50%) scale(1);
                    }
                }
            `}</style>
            <div
                onMouseEnter={onMouseEnter}
                onMouseLeave={onMouseLeave}
                style={popoverStyle}
            >
                {/* Speech bubble tail */}
                <div style={arrowStyle} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {actions.map(action => (
                        <button
                            key={action.id}
                            onClick={() => onAction(action.id)}
                            style={{
                                background: 'transparent',
                                border: 'none',
                                color: textColor,
                                padding: '6px 10px',
                                cursor: 'pointer',
                                textAlign: 'left',
                                borderRadius: '4px',
                                fontSize: '11px',
                                fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
                                whiteSpace: 'nowrap',
                                transition: 'background 0.15s ease',
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = hoverBg;
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'transparent';
                            }}
                        >
                            {action.label}
                        </button>
                    ))}
                </div>
            </div>
        </>,
        document.body
    );
};
