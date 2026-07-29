import { Navigate, type RouteObject } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import {
  AddonsPage,
  ApiPage,
  BrowserPage,
  FingerprintsPage,
  ProfileDetailPage,
  ProfileGroupsPage,
  ProfileImportPage,
  ProfileNewPage,
  ProfilesPage,
  ProfileTrashPage,
  ProxiesPage,
  RuntimePage,
  SettingsPage,
  TasksPage,
} from '@/pages'

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/profiles" replace /> },
      { path: 'profiles', element: <ProfilesPage /> },
      { path: 'profiles/new', element: <ProfileNewPage /> },
      { path: 'profiles/import', element: <ProfileImportPage /> },
      { path: 'profiles/groups', element: <ProfileGroupsPage /> },
      { path: 'profiles/trash', element: <ProfileTrashPage /> },
      { path: 'profiles/:id', element: <ProfileDetailPage /> },
      { path: 'runtime', element: <RuntimePage /> },
      { path: 'proxies', element: <ProxiesPage /> },
      { path: 'fingerprints', element: <FingerprintsPage /> },
      { path: 'browser', element: <BrowserPage /> },
      { path: 'api', element: <ApiPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'addons', element: <AddonsPage /> },
      { path: 'tasks', element: <TasksPage /> },
      { path: '*', element: <Navigate to="/profiles" replace /> },
    ],
  },
]
