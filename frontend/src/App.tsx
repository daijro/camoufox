import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { useApiHydrate } from '@/components/ApiStatusBanner'
import { routes } from './routes'

const router = createBrowserRouter(routes)

function Boot() {
  useApiHydrate()
  return <RouterProvider router={router} />
}

export default function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <Boot />
    </QueryClientProvider>
  )
}
