import { Route, Routes } from 'react-router-dom'
import { AppHeader } from './components/AppHeader'
import { RequireAuth } from './components/RequireAuth'
import { CallbackPage } from './pages/CallbackPage'
import { GitHubAccessLevelPage } from './pages/GitHubAccessLevelPage'
import { LoginPage } from './pages/LoginPage'
import { RepoBrowserPage } from './pages/RepoBrowserPage'
import './App.css'

function App() {
  return (
    <>
      <AppHeader />
      <main className="app-main">
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
      </main>
    </>
  )
}

export default App
