import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { AdminRoute } from './auth/AdminRoute'
import { AuthProvider } from './auth/AuthProvider'
import { Callback } from './auth/callback'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { SilentCallback } from './auth/silentCallback'
import { Admin } from './pages/Admin'
import { Files } from './pages/Files'
import { Login } from './pages/Login'
import { Search } from './pages/Search'
import { Upload } from './pages/Upload'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/auth/callback" element={<Callback />} />
          <Route path="/auth/silent-callback" element={<SilentCallback />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Search />
              </ProtectedRoute>
            }
          />
          <Route
            path="/files"
            element={
              <ProtectedRoute>
                <Files />
              </ProtectedRoute>
            }
          />
          <Route
            path="/upload"
            element={
              <ProtectedRoute>
                <Upload />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <Admin />
              </AdminRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
