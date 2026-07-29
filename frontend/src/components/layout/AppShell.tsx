import { Outlet } from 'react-router-dom'
import { ApiStatusBanner } from '@/components/ApiStatusBanner'
import { Sidebar } from './Sidebar'

export function AppShell() {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-50 text-slate-800">
      <ApiStatusBanner />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
