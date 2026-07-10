import asyncio, re, json
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page(viewport={'width': 1920, 'height': 1080})
        env_text = open('d:/agentclaw/AgentClaw/.env').read()
        token = re.search(r'ADMIN_TOKEN=(.+)', env_text).group(1).strip()

        await page.goto('http://127.0.0.1:8000/dashboard', wait_until='networkidle', timeout=20000)
        await asyncio.sleep(2)
        await page.locator('input').first.fill(token)
        await page.locator('button').last.click()
        await asyncio.sleep(5)

        await page.locator('textarea').first.fill('帮我创建一个小红书文案生成的agent')
        await page.keyboard.press('Enter')
        print('Sent agent creation request, monitoring for errors...')

        for i in range(180):
            await asyncio.sleep(1)
            raw = await page.evaluate('() => document.body.innerText')

            if 'tool_choice' in raw and 'Thinking mode' in raw:
                print(f'FAIL at t={i+1}s — tool_choice error')
                return
            if '401' in raw and 'Authentication' in raw:
                print(f'FAIL at t={i+1}s — auth error')
                return
            if 'xhs_' in raw.lower() or 'xiaohongshu' in raw.lower():
                print(f'SUCCESS at t={i+1}s — agent files being created!')
                return
            if i % 30 == 29:
                has_err = '错误' in raw
                print(f'... t={i+1}s (error_visible={has_err})')

        raw = await page.evaluate('() => document.body.innerText')
        if '错误' in raw:
            idx = raw.find('错误')
            print(f'Error: {raw[idx:idx+200]}')
        else:
            print('No visible error')
        await b.close()

asyncio.run(test())
