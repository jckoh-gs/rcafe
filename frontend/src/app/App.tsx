import { AdminPage } from '../pages/admin'
import { HomePage } from '../pages/home'

/** Two pages, told apart by the address; no router library is needed for that. */
export function App() {
  const isAdmin = /^\/admin(\/|$)/.test(window.location.pathname)
  return isAdmin ? <AdminPage /> : <HomePage />
}
