import { create } from 'zustand'

type UiState = {
  sidebarCollapsed: boolean
  searchQuery: string
  toggleSidebar: () => void
  setSearchQuery: (q: string) => void
}

export const useUiStore = create<UiState>((set) => ({
  sidebarCollapsed: false,
  searchQuery: '',
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setSearchQuery: (searchQuery) => set({ searchQuery }),
}))
