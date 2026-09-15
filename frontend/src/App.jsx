import { Route, Routes } from 'react-router-dom'
import { CallbackPage } from './pages/CallbackPage'
import { GitHubAccessLevelPage } from './pages/GitHubAccessLevelPage'
import { LoginPage } from './pages/LoginPage'
import './App.css'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/login" element={<GitHubAccessLevelPage />} />
      <Route path="/callback" element={<CallbackPage />} />
    </Routes>
  )
}

export default App
