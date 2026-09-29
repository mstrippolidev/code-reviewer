import { Route, Routes } from 'react-router-dom'
import { AppHeader } from './components/AppHeader'
import { RequireAuth } from './components/RequireAuth'
import { AnnotatedFilePage } from './pages/AnnotatedFilePage'
import { CallbackPage } from './pages/CallbackPage'
import { GitHubAccessLevelPage } from './pages/GitHubAccessLevelPage'
import { GuestReviewPage } from './pages/GuestReviewPage'
import { LoginPage } from './pages/LoginPage'
import { RepoBrowserPage } from './pages/RepoBrowserPage'
import { ReviewPage } from './pages/ReviewPage'
import { ReviewPreviewPage } from './pages/ReviewPreviewPage'
import './App.css'
import './review.css'

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
            path="/guest"
            element={
              <RequireAuth allowGuest>
                <GuestReviewPage />
              </RequireAuth>
            }
          />
          <Route
            path="/repos"
            element={
              <RequireAuth>
                <RepoBrowserPage />
              </RequireAuth>
            }
          />
          {import.meta.env.DEV ? <Route path="/reviews/preview" element={<ReviewPreviewPage />} /> : null}
          <Route
            path="/reviews/:reviewId"
            element={
              <RequireAuth allowGuest>
                <ReviewPage />
              </RequireAuth>
            }
          />
          <Route
            path="/reviews/:reviewId/file"
            element={
              <RequireAuth allowGuest>
                <AnnotatedFilePage />
              </RequireAuth>
            }
          />
        </Routes>
      </main>
    </>
  )
}

export default App
