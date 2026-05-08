import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import '@xyflow/react/dist/style.css'
import App from './App.tsx'
import { LocaleProvider } from './i18n'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LocaleProvider>
      <App />
    </LocaleProvider>
  </StrictMode>,
)
