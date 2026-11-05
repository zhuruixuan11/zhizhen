<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  /** 已收集的槽位快照（来自上一条 assistant 消息的 meta.slots） */
  slots?: Record<string, unknown>
  /** 是否问诊完成（不再追问） */
  ready?: boolean
}>()

// 四诊核心要素：名称 → 槽位 key 映射
const FIELDS: Array<{ key: string; label: string; icon?: string }> = [
  { key: 'complaint', label: '主诉', icon: '主诉' },
  { key: 'cold_hot', label: '寒热', icon: '寒' },
  { key: 'diet', label: '饮食', icon: '食' },
  { key: 'sleep', label: '睡眠', icon: '眠' },
  { key: 'stool_urine', label: '二便', icon: '便' },
  { key: 'emotion', label: '情志', icon: '情' },
]

const filledCount = computed(() => {
  const s = props.slots || {}
  return FIELDS.filter(f => {
    const v = s[f.key]
    if (v === undefined || v === null) return false
    if (typeof v === 'string') return v.trim().length > 0
    if (Array.isArray(v)) return v.length > 0
    return true
  }).length
})

const _slotIsFilled = (key: string): boolean => {
  const v = props.slots?.[key]
  if (v === undefined || v === null) return false
  if (typeof v === 'string') return v.trim().length > 0
  if (Array.isArray(v)) return v.length > 0
  return true
}

const total = FIELDS.length
const percent = computed(() => Math.round((filledCount.value / total) * 100))
</script>

<template>
  <div class="inquiry-progress" :class="{ ready: ready }">
    <div class="progress-header">
      <span class="progress-title">四诊采集进度</span>
      <span class="progress-count">
        {{ filledCount }}/{{ total }}
        <template v-if="ready" class="ready-tag">· 信息充足</template>
      </span>
    </div>
    <div class="progress-bar">
      <div class="progress-fill" :style="{ width: percent + '%' }" />
    </div>
    <div class="progress-fields">
      <div
        v-for="f in FIELDS"
        :key="f.key"
        class="field-chip"
        :class="{ filled: _slotIsFilled(f.key) }"
      >
        <span class="chip-icon" v-if="f.icon">{{ f.icon }}</span>
        <span class="chip-label">{{ f.label }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inquiry-progress {
  background: var(--tcm-bg-soft, #f5efe6);
  border: 1px solid var(--tcm-border-soft, #e3d6c3);
  border-radius: 10px;
  padding: 14px 16px;
  margin: 12px 0;
  font-size: 13px;
  color: var(--tcm-text-dim, #7a6f5e);
  transition: border-color .3s;
}
.inquiry-progress.ready {
  border-color: var(--tcm-success, #3a7a3f);
  background: #f0f5ed;
}
.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.progress-title {
  font-weight: 600;
  color: var(--tcm-text, #3a342a);
}
.progress-count { font-variant-numeric: tabular-nums; }
.ready-tag {
  color: var(--tcm-success, #3a7a3f);
  margin-left: 4px;
}
.progress-bar {
  height: 6px;
  background: #e3d6c3;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 10px;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--tcm-primary, #a63d40), var(--tcm-gold, #c8963a));
  border-radius: 3px;
  transition: width .4s ease;
}
.progress-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.field-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 14px;
  border: 1px solid var(--tcm-border-soft, #e3d6c3);
  background: #fff;
  font-size: 12px;
  color: #a89a84;
  transition: all .25s;
}
.field-chip.filled {
  border-color: var(--tcm-primary, #a63d40);
  background: #faf0ec;
  color: var(--tcm-primary, #a63d40);
}
.chip-icon {
  font-weight: 700;
  font-size: 11px;
  opacity: .7;
}
</style>
