import { expect, test } from '@playwright/test'
import { registerApiMocks } from './support/mockApi'

const pageCases = [
  { name: '总览', path: '/', title: '统一运维总览' },
  { name: '流量分析', path: '/traffic?time_range=1h', title: '流量分析' },
  { name: '资源分析', path: '/resources?time_range=1h', title: '资源分析' },
  { name: '异常中心', path: '/incidents', title: '异常中心' },
  { name: '建议中心', path: '/recommendations', title: '建议中心' },
  { name: '任务中心', path: '/tasks', title: '任务中心' },
  { name: '质量看板', path: '/quality', title: '质量看板' },
  { name: '执行插件', path: '/executors', title: '执行插件' },
]

test.beforeEach(async ({ page }) => {
  await registerApiMocks(page)
})

test.describe('主控台主链路 Smoke', () => {
  for (const pageCase of pageCases) {
    test(`${pageCase.name} 页面可正常渲染`, async ({ page }) => {
      await page.goto(pageCase.path)
      await expect(page.getByText('统一运维分析工作台')).toBeVisible()
      await expect(page.getByRole('heading', { name: pageCase.title, exact: true })).toBeVisible()
    })
  }

  test('侧边导航可以在主页面间切换', async ({ page }) => {
    // 通过真实点击菜单验证路由切换，防止导航回归导致入口不可达。
    await page.goto('/')
    const menu = page.locator('.ant-menu')

    await menu.getByText('流量分析', { exact: true }).click()
    await expect(page).toHaveURL(/\/traffic/)
    await expect(page.getByRole('heading', { name: '流量分析', exact: true })).toBeVisible()

    await menu.getByText('任务中心', { exact: true }).click()
    await expect(page).toHaveURL(/\/tasks/)
    await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible()

    await menu.getByText('执行插件', { exact: true }).click()
    await expect(page).toHaveURL(/\/executors/)
    await expect(page.getByRole('heading', { name: '执行插件', exact: true })).toBeVisible()
  })
})

