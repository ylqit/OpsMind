import { create } from 'zustand'

export const OPS_TIME_RANGE_OPTIONS = ['1h', '6h', '24h'] as const
export const QUALITY_WINDOW_OPTIONS = ['7d', '14d', '30d'] as const

export type OpsTimeRange = (typeof OPS_TIME_RANGE_OPTIONS)[number]
export type QualityWindow = (typeof QUALITY_WINDOW_OPTIONS)[number]

const DEFAULT_TIME_RANGE: OpsTimeRange = '1h'
const DEFAULT_QUALITY_WINDOW: QualityWindow = '7d'

const opsTimeRangeSet = new Set<string>(OPS_TIME_RANGE_OPTIONS)
const qualityWindowSet = new Set<string>(QUALITY_WINDOW_OPTIONS)

export const normalizeOpsTimeRange = (value?: string | null): OpsTimeRange => {
  if (!value || !opsTimeRangeSet.has(value)) {
    return DEFAULT_TIME_RANGE
  }
  return value as OpsTimeRange
}

export const normalizeQualityWindow = (value?: string | null): QualityWindow => {
  if (!value || !qualityWindowSet.has(value)) {
    return DEFAULT_QUALITY_WINDOW
  }
  return value as QualityWindow
}

interface WorkspaceFilterState {
  timeRange: OpsTimeRange
  serviceKey: string
  qualityWindow: QualityWindow
  model: string
  setTimeRange: (value: OpsTimeRange) => void
  setServiceKey: (value: string) => void
  setQualityWindow: (value: QualityWindow) => void
  setModel: (value: string) => void
  syncOpsFilters: (payload: { timeRange?: string | null; serviceKey?: string | null }) => void
  syncQualityFilters: (payload: { window?: string | null; serviceKey?: string | null; model?: string | null }) => void
  resetOpsFilters: () => void
  resetQualityFilters: () => void
}

// 主控台跨页共享的筛选条件统一放在这里，避免每个页面各自维护一套状态。
export const useWorkspaceFilterStore = create<WorkspaceFilterState>((set) => ({
  timeRange: DEFAULT_TIME_RANGE,
  serviceKey: '',
  qualityWindow: DEFAULT_QUALITY_WINDOW,
  model: '',
  setTimeRange: (value) => set({ timeRange: normalizeOpsTimeRange(value) }),
  setServiceKey: (value) => set({ serviceKey: value.trim() }),
  setQualityWindow: (value) => set({ qualityWindow: normalizeQualityWindow(value) }),
  setModel: (value) => set({ model: value.trim() }),
  syncOpsFilters: ({ timeRange, serviceKey }) => set((state) => {
    const nextTimeRange = timeRange == null ? state.timeRange : normalizeOpsTimeRange(timeRange)
    const nextServiceKey = serviceKey == null ? state.serviceKey : serviceKey.trim()
    if (state.timeRange === nextTimeRange && state.serviceKey === nextServiceKey) {
      return state
    }
    return {
      timeRange: nextTimeRange,
      serviceKey: nextServiceKey,
    }
  }),
  syncQualityFilters: ({ window, serviceKey, model }) => set((state) => {
    const nextWindow = window == null ? state.qualityWindow : normalizeQualityWindow(window)
    const nextServiceKey = serviceKey == null ? state.serviceKey : serviceKey.trim()
    const nextModel = model == null ? state.model : model.trim()
    if (
      state.qualityWindow === nextWindow
      && state.serviceKey === nextServiceKey
      && state.model === nextModel
    ) {
      return state
    }
    return {
      qualityWindow: nextWindow,
      serviceKey: nextServiceKey,
      model: nextModel,
    }
  }),
  resetOpsFilters: () => set({ timeRange: DEFAULT_TIME_RANGE, serviceKey: '' }),
  resetQualityFilters: () => set({ qualityWindow: DEFAULT_QUALITY_WINDOW, serviceKey: '', model: '' }),
}))
