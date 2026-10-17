import React from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import thTH from 'antd/locale/th_TH';
import { BrowserRouter } from 'react-router-dom';
import App from './App.jsx';
import { mahidolTheme } from './theme.js';

document.body.style.fontFamily = "Prompt, 'Noto Sans Thai', Tahoma, sans-serif";

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider theme={mahidolTheme} locale={thTH}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
);
