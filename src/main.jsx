import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import Report from './Report.jsx'

const RootView = window.location.pathname === '/report' ? Report : App

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <RootView />
  </StrictMode>,
)
