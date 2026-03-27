import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { GraphTabApp } from './GraphTabApp';
import { RunDetailsModalApp } from './RunDetailsModalApp';
import { NodeEditModalApp } from './NodeEditModalApp';
import { PriorsTabApp } from './PriorsTabApp';
import { NodeEditorTabApp } from './NodeEditorTabApp';
import { PriorEditorTabApp } from './PriorEditorTabApp';
import './styles.css';

if (document.getElementById('root')) {
  const root = ReactDOM.createRoot(document.getElementById('root') as HTMLElement);
  root.render(<App />);
} else if (document.getElementById('graph-tab-root')) {
  // Render GraphTabApp for graph tabs
  const root = ReactDOM.createRoot(document.getElementById('graph-tab-root') as HTMLElement);
  root.render(<GraphTabApp />);
} else if (document.getElementById('priors-root')) {
  // Render PriorsTabApp for priors tab
  const root = ReactDOM.createRoot(document.getElementById('priors-root') as HTMLElement);
  root.render(<PriorsTabApp />);
} else if (document.getElementById('node-editor-root')) {
  // Render NodeEditorTabApp for node editor tab
  const root = ReactDOM.createRoot(document.getElementById('node-editor-root') as HTMLElement);
  root.render(<NodeEditorTabApp />);
} else if (document.getElementById('prior-editor-root')) {
  // Render PriorEditorTabApp for prior editor tab
  const root = ReactDOM.createRoot(document.getElementById('prior-editor-root') as HTMLElement);
  root.render(<PriorEditorTabApp />);
} else if (document.getElementById('run-details-root')) {
  // Render RunDetailsModalApp for run details dialog
  const root = ReactDOM.createRoot(document.getElementById('run-details-root') as HTMLElement);
  root.render(<RunDetailsModalApp />);
} else if (document.getElementById('node-edit-root')) {
  // Render NodeEditModalApp for node edit dialog
  const root = ReactDOM.createRoot(document.getElementById('node-edit-root') as HTMLElement);
  root.render(<NodeEditModalApp />);
}
