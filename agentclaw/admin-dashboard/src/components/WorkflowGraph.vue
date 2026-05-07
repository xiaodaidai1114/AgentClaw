<template>
  <div class="workflow-graph-container">
    <svg :width="svgWidth" :height="svgHeight" class="workflow-svg">
      <defs>
        <marker id="arrow-normal" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#999"/>
        </marker>
        <marker id="arrow-conditional" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#1890ff"/>
        </marker>
        <marker id="arrow-back" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#ff7875"/>
        </marker>
      </defs>
      
      <!-- 边 -->
      <g class="edges">
        <g v-for="edge in renderedEdges" :key="`${edge.source}-${edge.target}`">
          <path :d="edge.path" :class="['edge', edge.edgeClass]" :marker-end="edge.marker"/>
          <text v-if="edge.label" :x="edge.labelX" :y="edge.labelY" :class="['edge-label', edge.edgeClass]">
            {{ edge.label }}
          </text>
        </g>
      </g>
      
      <!-- START 节点 -->
      <g class="start-node" :transform="`translate(${padding}, ${startNodeY})`">
        <rect class="node-rect start" :width="startNodeWidth" :height="nodeHeight" :rx="nodeHeight/2"/>
        <text class="node-name" :x="startNodeWidth/2" :y="nodeHeight/2 + 4">START</text>
      </g>
      
      <!-- 业务节点 -->
      <g class="nodes">
        <g v-for="node in renderedNodes" :key="node.id"
           :transform="`translate(${node.x}, ${node.y})`"
           class="node-group" @click="$emit('node-click', node, $event)">
          
          <!-- ParallelGroup: 蓝色框包含子节点 -->
          <template v-if="isGroupNode(node)">
            <rect class="parallel-group-bg" 
                  :width="getGroupWidth(node)" 
                  :height="getGroupHeight(node)" 
                  rx="8"/>
            <text class="parallel-group-label" x="8" y="18">{{ t('workflowGraph.parallelGroup', { name: node.id }) }}</text>
            <!-- 子节点 -->
            <g v-for="(child, idx) in node.children" :key="child.id"
               :transform="`translate(10, ${30 + idx * (childNodeHeight + 8)})`"
               class="child-node-group">
              <rect class="node-rect" :class="getChildNodeClass(child)" 
                    :width="childNodeWidth" :height="childNodeHeight" rx="4"/>
              <text class="child-node-type" :x="childNodeWidth/2" y="12">{{ getNodeTypeLabel(child) }}</text>
              <text class="child-node-name" :x="childNodeWidth/2" y="26">{{ truncateName(child.id) }}</text>
            </g>
          </template>
          
          <!-- 普通节点 -->
          <template v-else>
            <rect class="node-rect" :class="getNodeClass(node)" :width="nodeWidth" :height="nodeHeight" rx="6"/>
            <text class="node-type" :x="nodeWidth/2" y="16">{{ getNodeTypeLabel(node) }}</text>
            <text class="node-name" :x="nodeWidth/2" y="34">{{ truncateName(node.id) }}</text>
          </template>
        </g>
      </g>
    </svg>
    
    <div class="graph-legend">
      <span class="legend-item"><span class="dot start"></span> {{ t('workflowGraph.legend.start') }}</span>
      <span class="legend-item"><span class="dot llm"></span> LLM</span>
      <span class="legend-item"><span class="dot function"></span> Function</span>
      <span class="legend-item"><span class="dot human"></span> Human</span>
      <span class="legend-item"><span class="dot parallel"></span> Parallel</span>
      <span class="legend-item"><span class="dot current"></span> {{ t('workflowGraph.legend.current') }}</span>
      <span class="legend-item"><span class="dot breakpoint"></span> {{ t('workflowGraph.legend.breakpoint') }}</span>
      <span class="legend-item edge-legend normal">→ {{ t('workflowGraph.legend.normal') }}</span>
      <span class="legend-item edge-legend conditional">⇢ {{ t('workflowGraph.legend.conditional') }}</span>
      <span class="legend-item edge-legend back">↺ {{ t('workflowGraph.legend.loop') }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  nodeOrder: { type: Array, default: () => [] },
  currentNode: { type: String, default: '' },
  executedNodes: { type: Array, default: () => [] },
  breakpoints: { type: Array, default: () => [] }
})

defineEmits(['node-click'])
const { t } = useI18n()

// 布局常量
const nodeWidth = 110
const nodeHeight = 50
const childNodeWidth = 100
const childNodeHeight = 36
const startNodeWidth = 80
const horizontalGap = 40
const verticalGap = 15
const padding = 24
const backEdgeOffset = 30

// 计算 ParallelGroup 的宽度和高度
function getGroupWidth(node) {
  return childNodeWidth + 20
}

function getGroupHeight(node) {
  const childCount = node.children?.length || 0
  return 30 + childCount * (childNodeHeight + 8) + 10
}

function getChildNodeClass(child) {
  const type = child.type?.toLowerCase() || ''
  if (type.includes('llm')) return 'llm'
  if (type.includes('human')) return 'human'
  return 'function'
}

// 判断是否是组节点（ParallelGroup）
function isGroupNode(node) {
  // 检查 is_group 标记或 type 为 parallel 且有 children
  if (node.is_group) return true
  if (node.type === 'parallel' && node.children && node.children.length > 0) return true
  return false
}

// 根据边关系计算节点层级（使用拓扑排序，自动检测回边）
const nodeLayout = computed(() => {
  const levels = {}
  const nodeIds = new Set(props.nodes.map(n => n.id))
  
  // 构建完整邻接关系
  const allOutEdges = {}
  const allInEdges = {}
  props.nodes.forEach(n => {
    allOutEdges[n.id] = []
    allInEdges[n.id] = []
  })
  
  props.edges.forEach(e => {
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) return
    allOutEdges[e.source].push(e.target)
    allInEdges[e.target].push(e.source)
  })
  
  // 找 __start__ 边的目标节点作为入口
  const startEdgeTargets = props.edges
    .filter(e => e.source === '__start__')
    .map(e => e.target)
    .filter(id => nodeIds.has(id))

  // 如果没有 __start__ 边，回退到无入边节点
  let startNodes = startEdgeTargets.length > 0
    ? startEdgeTargets
    : props.nodes.filter(n => allInEdges[n.id].length === 0).map(n => n.id)

  // 全是环的情况，找被引用最少的
  if (startNodes.length === 0 && props.nodes.length > 0) {
    const minInDegree = Math.min(...props.nodes.map(n => allInEdges[n.id].length))
    startNodes = props.nodes.filter(n => allInEdges[n.id].length === minInDegree).map(n => n.id)
  }
  
  // BFS 分层，同时检测回边
  const backEdges = []
  const visited = new Set()
  const inQueue = new Set(startNodes)
  let queue = [...startNodes]
  let level = 0
  
  while (queue.length > 0 && level < 100) {
    const nextQueue = []
    queue.forEach(id => {
      if (visited.has(id)) return
      visited.add(id)
      levels[id] = level
      
      allOutEdges[id]?.forEach(target => {
        if (visited.has(target)) {
          // 目标已访问，这是回边
          backEdges.push({ source: id, target })
        } else if (!inQueue.has(target)) {
          inQueue.add(target)
          nextQueue.push(target)
        }
      })
    })
    queue = nextQueue
    level++
  }
  
  // 未访问节点放到最后一层
  props.nodes.forEach(n => {
    if (levels[n.id] === undefined) levels[n.id] = level
  })
  
  return { levels, backEdges, entryNodes: startNodes }
})

// 每层节点
const levelNodes = computed(() => {
  const result = {}
  props.nodes.forEach(n => {
    const level = nodeLayout.value.levels[n.id] ?? 0
    if (!result[level]) result[level] = []
    result[level].push(n)
  })
  return result
})

const maxLevel = computed(() => Math.max(...Object.keys(levelNodes.value).map(Number), 0))
const maxNodesInLevel = computed(() => Math.max(...Object.values(levelNodes.value).map(arr => arr.length), 1))

// 获取节点实际高度（ParallelGroup 需要更大高度）
function getNodeHeight(node) {
  if (isGroupNode(node)) {
    return getGroupHeight(node)
  }
  return nodeHeight
}

// 计算节点位置
const renderedNodes = computed(() => {
  const positions = []
  
  // 计算每层的总高度（考虑 ParallelGroup）
  const levelHeights = {}
  Object.entries(levelNodes.value).forEach(([level, nodes]) => {
    let height = 0
    nodes.forEach((node, idx) => {
      if (idx > 0) height += verticalGap
      height += getNodeHeight(node)
    })
    levelHeights[level] = height
  })
  
  const maxLevelHeight = Math.max(...Object.values(levelHeights), nodeHeight)
  
  Object.entries(levelNodes.value).forEach(([level, nodes]) => {
    const levelNum = Number(level)
    const x = padding + startNodeWidth + horizontalGap + levelNum * (nodeWidth + horizontalGap)
    const levelHeight = levelHeights[level] || nodeHeight
    let currentY = padding + backEdgeOffset + (maxLevelHeight - levelHeight) / 2
    
    nodes.forEach((node) => {
      const h = getNodeHeight(node)
      positions.push({
        ...node,
        x,
        y: currentY,
        level: levelNum,
        actualHeight: h
      })
      currentY += h + verticalGap
    })
  })
  
  return positions
})

// START 节点 Y 坐标
const startNodeY = computed(() => {
  // 计算最大层高度
  const levelHeights = {}
  Object.entries(levelNodes.value).forEach(([level, nodes]) => {
    let height = 0
    nodes.forEach((node, idx) => {
      if (idx > 0) height += verticalGap
      height += getNodeHeight(node)
    })
    levelHeights[level] = height
  })
  const maxLevelHeight = Math.max(...Object.values(levelHeights), nodeHeight)
  return padding + backEdgeOffset + (maxLevelHeight - nodeHeight) / 2
})

// SVG 尺寸
const svgWidth = computed(() => {
  return padding * 2 + startNodeWidth + (maxLevel.value + 1) * (nodeWidth + horizontalGap) + horizontalGap
})

const svgHeight = computed(() => {
  // 计算最大层高度（考虑 ParallelGroup）
  const levelHeights = {}
  Object.entries(levelNodes.value).forEach(([level, nodes]) => {
    let height = 0
    nodes.forEach((node, idx) => {
      if (idx > 0) height += verticalGap
      height += getNodeHeight(node)
    })
    levelHeights[level] = height
  })
  const contentHeight = Math.max(...Object.values(levelHeights), nodeHeight)
  // 预留下方回边空间
  const bottomBackEdgeSpace = nodeLayout.value.backEdges.length > 0 ? 30 : 0
  return padding * 2 + backEdgeOffset + contentHeight + bottomBackEdgeSpace
})

// 节点位置映射
const nodePositions = computed(() => {
  const map = {}
  renderedNodes.value.forEach(n => {
    map[n.id] = { x: n.x, y: n.y, level: n.level, actualHeight: n.actualHeight || nodeHeight }
  })
  return map
})

// 计算边
const renderedEdges = computed(() => {
  const edges = []
  const positions = nodePositions.value
  const { backEdges, entryNodes } = nodeLayout.value
  const backEdgeSet = new Set(backEdges.map(e => `${e.source}-${e.target}`))
  
  // START → 入口节点（只连接真正的入口）
  entryNodes.forEach((nodeId, idx) => {
    const target = positions[nodeId]
    if (!target) return
    const startX = padding + startNodeWidth
    const startY = startNodeY.value + nodeHeight / 2
    const endX = target.x
    const targetHeight = target.actualHeight || nodeHeight
    const endY = target.y + targetHeight / 2
    
    let path
    if (Math.abs(startY - endY) < 5) {
      path = `M ${startX} ${startY} L ${endX} ${endY}`
    } else {
      const midX = (startX + endX) / 2
      path = `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`
    }
    edges.push({ source: '__start__', target: nodeId, path, edgeClass: 'normal', marker: 'url(#arrow-normal)' })
  })
  
  // 统计上方和下方回边数量，用于错开绘制
  let topBackEdgeIndex = 0
  let bottomBackEdgeIndex = 0

  // 业务边
  props.edges.forEach(edge => {
    const source = positions[edge.source]
    const target = positions[edge.target]
    if (!source || !target) return

    const isBack = backEdgeSet.has(`${edge.source}-${edge.target}`)
    const isConditional = edge.type === 'conditional'
    
    const sourceHeight = source.actualHeight || nodeHeight
    const targetHeight = target.actualHeight || nodeHeight

    let path, labelX, labelY

    if (isBack) {
      // 根据源和目标的 Y 位置决定从上方还是下方绕回
      const sourceY = source.y + sourceHeight / 2
      const targetY = target.y + targetHeight / 2
      const goTop = sourceY <= targetY // 源在上方或同行，从上方绕

      if (goTop) {
        // 从上方绕回
        const offset = topBackEdgeIndex * 18
        topBackEdgeIndex++

        const startX = source.x + nodeWidth / 2
        const startY = source.y
        const endX = target.x + nodeWidth / 2
        const endY = target.y
        const loopY = padding - 5 + offset

        path = `M ${startX} ${startY} L ${startX} ${loopY} L ${endX} ${loopY} L ${endX} ${endY}`
        labelX = (startX + endX) / 2
        labelY = loopY - 6
      } else {
        // 从下方绕回
        const offset = bottomBackEdgeIndex * 18
        bottomBackEdgeIndex++

        const startX = source.x + nodeWidth / 2
        const startY = source.y + sourceHeight
        const endX = target.x + nodeWidth / 2
        const endY = target.y + targetHeight
        const loopY = svgHeight.value - padding / 2 + offset

        path = `M ${startX} ${startY} L ${startX} ${loopY} L ${endX} ${loopY} L ${endX} ${endY}`
        labelX = (startX + endX) / 2
        labelY = loopY + 12
      }
    } else {
      // 前向边
      const startX = source.x + nodeWidth
      const startY = source.y + sourceHeight / 2
      const endX = target.x
      const endY = target.y + targetHeight / 2
      
      if (Math.abs(startY - endY) < 5) {
        path = `M ${startX} ${startY} L ${endX} ${endY}`
      } else {
        const midX = (startX + endX) / 2
        path = `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`
      }
      labelX = (startX + endX) / 2
      labelY = (startY + endY) / 2 - 8
    }
    
    const edgeClass = isBack ? 'back' : (isConditional ? 'conditional' : 'normal')
    const marker = isBack ? 'url(#arrow-back)' : (isConditional ? 'url(#arrow-conditional)' : 'url(#arrow-normal)')
    
    edges.push({
      ...edge,
      path,
      labelX,
      labelY,
      label: edge.condition,
      edgeClass,
      marker
    })
  })
  
  return edges
})

function getNodeClass(node) {
  const classes = []
  const type = node.type?.toLowerCase() || ''
  
  // 基础类型
  if (type.includes('llm')) classes.push('llm')
  else if (type.includes('human')) classes.push('human')
  else if (type.includes('parallel')) classes.push('parallel')
  else classes.push('function')
  
  // 调试状态
  if (props.currentNode === node.id) {
    classes.push('current')
  } else if (props.executedNodes.includes(node.id)) {
    classes.push('executed')
  }
  
  // 断点
  if (props.breakpoints.includes(node.id)) {
    classes.push('has-breakpoint')
  }
  
  return classes.join(' ')
}

function getNodeTypeLabel(node) {
  const type = node.type?.toLowerCase() || ''
  if (type.includes('llm')) return 'LLM'
  if (type.includes('human')) return t('workflowGraph.nodeTypes.human')
  if (type.includes('parallel')) return t('workflowGraph.nodeTypes.parallel')
  return t('workflowGraph.nodeTypes.function')
}

function truncateName(name) {
  if (!name) return ''
  return name.length > 12 ? name.substring(0, 10) + '..' : name
}
</script>

<style scoped>
.workflow-graph-container {
  background: #fafafa;
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.workflow-svg {
  display: block;
}

/* 边样式 */
.edge {
  fill: none;
  stroke-width: 2;
}
.edge.normal { stroke: #999; }
.edge.conditional { stroke: #1890ff; stroke-dasharray: 5,3; }
.edge.back { stroke: #ff7875; stroke-dasharray: 4,2; }

.edge-label {
  font-size: 9px;
  text-anchor: middle;
  font-weight: 500;
}
.edge-label.normal { fill: #666; }
.edge-label.conditional { fill: #1890ff; }
.edge-label.back { fill: #ff7875; }

/* 节点样式 */
.node-group { cursor: pointer; }
.node-group:hover .node-rect { filter: brightness(0.95); stroke-width: 3; }

.node-rect {
  stroke-width: 2;
  transition: all 0.2s;
}
.node-rect.start { fill: #e6fffb; stroke: #13c2c2; }
.node-rect.llm { fill: #f6ffed; stroke: #52c41a; }
.node-rect.function { fill: #fff7e6; stroke: #fa8c16; }
.node-rect.human { fill: #f9f0ff; stroke: #722ed1; }
.node-rect.parallel { fill: #e6f7ff; stroke: #1890ff; }

/* ParallelGroup 样式 */
.parallel-group-bg {
  fill: #e6f7ff;
  stroke: #1890ff;
  stroke-width: 2;
  stroke-dasharray: 4,2;
}
.parallel-group-label {
  font-size: 11px;
  font-weight: 600;
  fill: #1890ff;
}
.child-node-group { cursor: pointer; }
.child-node-type {
  font-size: 9px;
  fill: #888;
  text-anchor: middle;
}
.child-node-name {
  font-size: 10px;
  font-weight: 500;
  fill: #333;
  text-anchor: middle;
}

/* 调试状态样式 */
.node-rect.current {
  stroke: #1976d2 !important;
  stroke-width: 4 !important;
  filter: drop-shadow(0 0 8px rgba(25, 118, 210, 0.5));
  animation: pulse 1.5s ease-in-out infinite;
}

.node-rect.executed {
  opacity: 0.6;
}

.node-rect.has-breakpoint {
  stroke: #f57c00 !important;
  stroke-width: 3 !important;
}

@keyframes pulse {
  0%, 100% { filter: drop-shadow(0 0 8px rgba(25, 118, 210, 0.5)); }
  50% { filter: drop-shadow(0 0 12px rgba(25, 118, 210, 0.8)); }
}

.node-type {
  font-size: 10px;
  fill: #888;
  text-anchor: middle;
}

.node-name {
  font-size: 11px;
  font-weight: 600;
  fill: #333;
  text-anchor: middle;
}

/* 图例 */
.graph-legend {
  display: flex;
  gap: 16px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #eee;
  font-size: 12px;
  color: #666;
  flex-wrap: wrap;
  justify-content: center;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  border: 2px solid;
}
.dot.start { background: #e6fffb; border-color: #13c2c2; }
.dot.llm { background: #f6ffed; border-color: #52c41a; }
.dot.function { background: #fff7e6; border-color: #fa8c16; }
.dot.human { background: #f9f0ff; border-color: #722ed1; }
.dot.parallel { background: #e6f7ff; border-color: #1890ff; }
.dot.current { background: #e3f2fd; border-color: #1976d2; box-shadow: 0 0 6px rgba(25, 118, 210, 0.5); }
.dot.breakpoint { background: #fff8e1; border-color: #f57c00; }

.edge-legend.normal { color: #999; }
.edge-legend.conditional { color: #1890ff; }
.edge-legend.back { color: #ff7875; }
</style>
