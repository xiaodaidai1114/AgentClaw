import fs from 'fs'
import path from 'path'

const args = process.argv.slice(2)
const rootArg = args.find(arg => arg.startsWith('--root='))
const root = path.resolve(rootArg ? rootArg.slice('--root='.length) : 'agentclaw/admin-dashboard/src')
const uiOnly = args.includes('--ui-only')
const byFile = args.includes('--by-file')
const skipDirs = new Set(['locales', '__tests__'])
const filePattern = /\.(vue|js)$/
const chinesePattern = /[\u4e00-\u9fff][\u4e00-\u9fff0-9A-Za-z_（）()、，。：；！?+\- ]*/g

const textCounts = new Map()
const fileCounts = new Map()

function collect(file, value) {
  const text = value.trim()
  if (!text || text.length < 2) return
  textCounts.set(text, (textCounts.get(text) || 0) + 1)
  const rel = path.relative(process.cwd(), file)
  fileCounts.set(rel, (fileCounts.get(rel) || 0) + 1)
}

function extractGenericMatches(text) {
  return text.match(chinesePattern) || []
}

function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|\s)\/\/.*$/gm, ' ')
}

function extractUiMatches(text) {
  const cleaned = stripComments(text)
  const matches = []
  const patterns = [
    />\s*([^<]*[\u4e00-\u9fff][^<]*)\s*</g,
    /(?:title|placeholder|label|description|tab)="([^"]*[\u4e00-\u9fff][^"]*)"/g,
    /(?:title|placeholder|label|description|tab)='([^']*[\u4e00-\u9fff][^']*)'/g,
    /(?:alert|confirm|message\.(?:success|error|warning|info))\(\s*(['"`])([^'"`]*[\u4e00-\u9fff][^'"`]*)\1/g,
    /(?:text|label|title|description|content|detail|action|hint|placeholder)\s*:\s*(['"`])([^'"`]*[\u4e00-\u9fff][^'"`]*)\1/g,
    /return\s+(['"`])([^'"`]*[\u4e00-\u9fff][^'"`]*)\1/g,
  ]

  for (const pattern of patterns) {
    for (const match of cleaned.matchAll(pattern)) {
      const candidate = match[2] ?? match[1]
      if (!candidate) continue
      matches.push(candidate)
    }
  }

  return matches
}

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (skipDirs.has(entry.name)) continue
      walk(path.join(dir, entry.name))
      continue
    }
    const file = path.join(dir, entry.name)
    if (!filePattern.test(file)) continue
    const text = fs.readFileSync(file, 'utf8')
    const matches = uiOnly ? extractUiMatches(text) : extractGenericMatches(text)
    for (const raw of matches) {
      collect(file, raw)
    }
  }
}

walk(root)

if (byFile) {
  for (const [file, count] of [...fileCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) {
    console.log(`${String(count).padStart(4, ' ')}  ${file}`)
  }
} else {
  for (const [text, count] of [...textCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-Hans-CN'))) {
    console.log(`${String(count).padStart(4, ' ')}  ${text}`)
  }
}
