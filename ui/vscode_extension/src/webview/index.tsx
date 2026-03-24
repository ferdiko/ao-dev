import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { GraphTabApp } from './GraphTabApp';
import { RunDetailsModalApp } from './RunDetailsModalApp';
import { NodeEditModalApp } from './NodeEditModalApp';
import { LessonsTabApp } from './LessonsTabApp';
import { NodeEditorTabApp } from './NodeEditorTabApp';
import { LessonEditorTabApp } from './LessonEditorTabApp';
import './styles.css';

if (document.getElementById('root')) {
  const root = ReactDOM.createRoot(document.getElementById('root') as HTMLElement);
  root.render(<App />);
} else if (document.getElementById('graph-tab-root')) {
  // Render GraphTabApp for graph tabs
  const root = ReactDOM.createRoot(document.getElementById('graph-tab-root') as HTMLElement);
  root.render(<GraphTabApp />);
} else if (document.getElementById('lessons-root')) {
  // Render LessonsTabApp for lessons tab
  const root = ReactDOM.createRoot(document.getElementById('lessons-root') as HTMLElement);
  root.render(<LessonsTabApp />);
} else if (document.getElementById('node-editor-root')) {
  // Render NodeEditorTabApp for node editor tab
  const root = ReactDOM.createRoot(document.getElementById('node-editor-root') as HTMLElement);
  root.render(<NodeEditorTabApp />);
} else if (document.getElementById('lesson-editor-root')) {
  // Render LessonEditorTabApp for lesson editor tab
  const root = ReactDOM.createRoot(document.getElementById('lesson-editor-root') as HTMLElement);
  root.render(<LessonEditorTabApp />);
} else if (document.getElementById('run-details-root')) {
  // Render RunDetailsModalApp for run details dialog
  const root = ReactDOM.createRoot(document.getElementById('run-details-root') as HTMLElement);
  root.render(<RunDetailsModalApp />);
} else if (document.getElementById('node-edit-root')) {
  // Render NodeEditModalApp for node edit dialog
  const root = ReactDOM.createRoot(document.getElementById('node-edit-root') as HTMLElement);
  root.render(<NodeEditModalApp />);
}
