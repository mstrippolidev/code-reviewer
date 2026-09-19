import { Route, Routes } from 'react-router-dom'
import { RequireAuth } from './components/RequireAuth'
import { CallbackPage } from './pages/CallbackPage'
import { GitHubAccessLevelPage } from './pages/GitHubAccessLevelPage'
import { LoginPage } from './pages/LoginPage'
import { RepoBrowserPage } from './pages/RepoBrowserPage'
import './App.css'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/login" element={<GitHubAccessLevelPage />} />
      <Route path="/callback" element={<CallbackPage />} />
      <Route
        path="/repos"
        element={
          <RequireAuth>
            <RepoBrowserPage />
          </RequireAuth>
        }
      />
    </Routes>
  )
}

export default App
