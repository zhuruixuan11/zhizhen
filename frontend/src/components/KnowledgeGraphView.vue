<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { SyndromeReport, GraphRefLabel } from '@/types'

const props = defineProps<{
  report: SyndromeReport
}>()

const router = useRouter()

interface GNode {
  id: string
  label: string
  type: GraphRefLabel
  x: number
  y: number
  primary?: boolean
}

interface GEdge {
  from: string
  to: string
}

const NODE_W = 148
const NODE_H = 34
const ROW_H = 56
const COL_X = { evidence: 84, syndrome: 300, formula: 516 }
const TOP_PAD = 44

/** 只渲染报告里真实存在的字段：辨证依据 / 证型 / 方剂 */
const layout = computed(() => {
  const evidence = (props.report.evidence || []).slice(0, 5)
  const formulas = (props.report.formula_suggestions || []).slice(0, 4)
  const rows = Math.max(evidence.length, formulas.length, 1)
  const height = TOP_PAD * 2 + (rows - 1) * ROW_H

  const centerY = TOP_PAD + ((rows - 1) * ROW_H) / 2
  const nodes: GNode[] = []
  const edges: GEdge[] = []

  // 中列：证型（唯一主节点）
  nodes.push({
    id: 'syndrome',
    label: props.report.syndrome || '未命名证型',
    type: 'Syndrome',
    x: COL_X.syndrome,
    y: centerY,
    primary: true,
  })

  // 左列：辨证依据
  evidence.forEach((e, i) => {
    const id = `ev-${i}`
    const y = TOP_PAD + i * ROW_H + ((rows - evidence.length) * ROW_H) / 2
    nodes.push({ id, label: e.description || e.source || '依据', type: 'Symptom', x: COL_X.evidence, y })
    edges.push({ from: id, to: 'syndrome' })
  })

  // 右列：方剂参考
  formulas.forEach((f, i) => {
    const id = `fm-${i}`
    const y = TOP_PAD + i * ROW_H + ((rows - formulas.length) * ROW_H) / 2
    nodes.push({ id, label: f.name || '方剂', type: 'Formula', x: COL_X.formula, y })
    edges.push({ from: 'syndrome', to: id })
  })

  return { nodes, edges, height: Math.max(height, 120), width: 660 }
})

const nodeMap = computed(() => {
  const m: Record<string, GNode> = {}
  layout.value.nodes.forEach((n) => (m[n.id] = n))
  return m
})

const typeText: Record<string, string> = {
  Formula: '方剂',
  Herb: '中药',
  Syndrome: '证型',
  Symptom: '依据',
}

const typeTarget: Record<string, string> = {
  Formula: 'formula',
  Herb: 'herb',
  Syndrome: 'syndrome',
  Symptom: 'symptom',
}

function edgePath(e: GEdge): string {
  const a = nodeMap.value[e.from]
  const b = nodeMap.value[e.to]
  if (!a || !b) return ''
  const x1 = a.x + NODE_W / 2
  const x2 = b.x - NODE_W / 2
  const mx = (x1 + x2) / 2
  return `M ${x1} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${x2} ${b.y}`
}

function navigate(n: GNode) {
  if (n.primary) return
  const target = typeTarget[n.type]
  if (target) {
    router.push({ path: '/knowledge', query: { q: n.label, type: target } })
  }
}
</script>

<template>
  <div class="kg-view">
    <svg :viewBox="`0 0 ${layout.width} ${layout.height}`" class="kg-svg" role="img">
      <g class="edges">
        <path
          v-for="(e, i) in layout.edges"
          :key="i"
          :d="edgePath(e)"
          class="edge"
        />
      </g>
      <g
        v-for="n in layout.nodes"
        :key="n.id"
        class="node-group"
        :class="[`node-${n.type.toLowerCase()}`, { primary: n.primary }]"
        :transform="`translate(${n.x}, ${n.y})`"
        @click="navigate(n)"
      >
        <title>{{ typeText[n.type] }}：{{ n.label }}</title>
        <rect
          :x="-NODE_W / 2"
          :y="-NODE_H / 2"
          :width="NODE_W"
          :height="NODE_H"
          rx="10"
          class="node-box"
        />
        <text class="node-label" text-anchor="middle" dy="0.35em">
          {{ n.label.length > 12 ? n.label.slice(0, 12) + '…' : n.label }}
        </text>
      </g>
    </svg>
    <p class="kg-hint">点击节点可跳转到知识库对应条目</p>
  </div>
</template>

<style scoped>
.kg-view {
  border: 1px solid var(--tcm-border);
  border-radius: 12px;
  background: var(--tcm-surface);
  padding: 8px 8px 0;
  overflow-x: auto;
}

.kg-svg {
  width: 100%;
  min-width: 620px;
  height: auto;
  display: block;
}

.edge {
  fill: none;
  stroke: var(--tcm-border);
  stroke-width: 1.5;
  stroke-dasharray: 4 3;
}

.node-group {
  cursor: pointer;
}

.node-group.primary {
  cursor: default;
}

.node-box {
  fill: var(--tcm-surface-2, #faf6f1);
  stroke: var(--tcm-border);
  stroke-width: 1.2;
  transition: stroke 0.18s ease, fill 0.18s ease;
}

.node-group:hover .node-box {
  stroke: var(--tcm-primary);
}

.node-syndrome .node-box {
  fill: var(--tcm-primary);
  stroke: var(--tcm-primary-deep);
}

.node-formula .node-box {
  fill: rgba(47, 82, 51, 0.1);
  stroke: rgba(47, 82, 51, 0.45);
}

.node-label {
  font-size: 12px;
  fill: var(--tcm-text);
  pointer-events: none;
  user-select: none;
}

.node-syndrome .node-label {
  fill: #fff;
  font-weight: 600;
}

.kg-hint {
  margin: 0;
  padding: 6px 4px 8px;
  font-size: 12px;
  color: var(--tcm-text-faint);
  text-align: center;
}
</style>
