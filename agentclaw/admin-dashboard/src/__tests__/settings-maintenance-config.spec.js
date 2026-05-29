import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('maintenance settings UX', () => {
  it('exposes independent retention controls for logs and checkpointers', () => {
    const settingsSource = readFileSync(resolve(process.cwd(), 'src/views/Settings.vue'), 'utf8')
    const apiSource = readFileSync(resolve(process.cwd(), 'src/api/index.js'), 'utf8')

    expect(settingsSource).toContain('maintenanceForm.log_retention_days')
    expect(settingsSource).toContain('maintenanceForm.checkpointer_retention_days')
    expect(settingsSource).toContain('fetchMaintenanceConfig')
    expect(settingsSource).toContain('saveMaintenanceConfig')
    expect(apiSource).toContain("getMaintenance: () => api.get('/settings/maintenance')")
    expect(apiSource).toContain("updateMaintenance: (data) => api.put('/settings/maintenance', data)")
  })
})
